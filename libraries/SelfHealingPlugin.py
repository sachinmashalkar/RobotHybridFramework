"""SeleniumLibrary plugin that overrides the core locator keywords with
fingerprint-based self-healing.

Register by passing ``plugins=`` on the SeleniumLibrary import::

    Library    SeleniumLibrary    timeout=20s    implicit_wait=2s
    ...    plugins=libraries.SelfHealingPlugin.SelfHealingPlugin

With the plugin active, the following existing SeleniumLibrary keywords are
transparently replaced with self-healing variants — callers keep using plain
SeleniumLibrary syntax, no ``Heal.`` prefix required:

* ``Click Element``
* ``Input Text`` / ``Input Password``
* ``Get Text`` / ``Get Value`` / ``Get WebElement``
* ``Element Should Be Visible``
* ``Wait Until Element Is Visible`` / ``Wait Until Element Is Enabled``

Flow:
  1. On first successful resolution, the element's "fingerprint" (tag,
     visible text, curated attribute subset, absolute XPath) is cached under
     ``results/healing/cache.json`` keyed by the locator string itself.
  2. If the same locator later fails to resolve anything, every candidate on
     the page sharing the cached tag is scored against the stored fingerprint;
     the highest-scoring match above the configured threshold (default 0.6)
     is used transparently.
  3. Each healing event is appended to ``results/healing/events.jsonl`` and
     the cached XPath is refreshed so subsequent runs pick up the new
     location directly.

Two additional keywords are exposed for operators:

* ``Prime Heal Cache    broken_locator    template_locator`` — resolves
  ``template_locator`` and stores its fingerprint under ``broken_locator``.
  Useful for seeding the cache in demos or after intentional renames.
* ``Write Healing Report    path=results/healing/report.html`` — renders an
  HTML summary of healing events from the JSONL log.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from robot.utils import timestr_to_secs

from SeleniumLibrary.base import LibraryComponent, keyword
from SeleniumLibrary.errors import ElementNotFound
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

TRACKED_ATTRS: tuple[str, ...] = (
    "id",
    "name",
    "class",
    "placeholder",
    "aria-label",
    "href",
    "type",
    "role",
    "data-testid",
    "title",
    "alt",
)

DEFAULT_CACHE = Path("results/healing/cache.json")
DEFAULT_EVENTS = Path("results/healing/events.jsonl")

DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_LLM_MAX_HTML_CHARS = 12000
DEFAULT_LLM_TIMEOUT_SECS = 20.0

_LLM_SYSTEM_PROMPT = (
    "You are a Selenium locator expert. Given a pruned HTML fragment and a "
    "description of the element that needs to be found, respond with exactly "
    "one CSS selector or XPath that uniquely identifies that element. "
    "Prefix the answer with 'css=' or 'xpath='. Do not include any other text, "
    "markdown, or explanation."
)

_SELECTOR_RESPONSE = re.compile(r"(?P<kind>css|xpath)\s*=\s*(?P<val>.+)", re.I)
_SCRIPT_STYLE_STRIP = re.compile(
    r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>",
    re.I | re.S,
)
_HTML_COMMENT_STRIP = re.compile(r"<!--.*?-->", re.S)


@dataclass
class Fingerprint:
    """Serializable snapshot of a DOM element used to drive healing."""

    tag: str
    text: str = ""
    attrs: dict[str, str] = field(default_factory=dict)
    xpath: str = ""
    original_locator: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "text": self.text,
            "attrs": dict(self.attrs),
            "xpath": self.xpath,
            "original_locator": self.original_locator,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Fingerprint":
        return cls(
            tag=payload.get("tag", ""),
            text=payload.get("text", "") or "",
            attrs=dict(payload.get("attrs", {}) or {}),
            xpath=payload.get("xpath", "") or "",
            original_locator=payload.get("original_locator", "") or "",
        )


def score_fingerprints(primary: Fingerprint, candidate: Fingerprint) -> float:
    """Score how similar ``candidate`` is to ``primary`` in the range [0.0, 1.0]."""
    score = 0.0
    if primary.tag and primary.tag == candidate.tag:
        score += 0.2
    for key, value in primary.attrs.items():
        if key == "class":
            a = set(value.split()) if value else set()
            b = set((candidate.attrs.get("class") or "").split())
            if a or b:
                score += 0.15 * (len(a & b) / max(1, len(a | b)))
        elif value and candidate.attrs.get(key) == value:
            score += 0.2
    if primary.text and primary.text == candidate.text:
        score += 0.25
    elif primary.text and candidate.text and primary.text in candidate.text:
        score += 0.1
    return min(score, 1.0)


_LOCATOR_PREFIXES = {
    "xpath": By.XPATH,
    "css": By.CSS_SELECTOR,
    "id": By.ID,
    "name": By.NAME,
    "link": By.LINK_TEXT,
    "partial link": By.PARTIAL_LINK_TEXT,
    "tag": By.TAG_NAME,
    "class": By.CLASS_NAME,
}


def split_locator(locator: str) -> tuple[str, str]:
    """Parse a SeleniumLibrary-style locator into a ``(By, value)`` pair."""
    if "=" in locator:
        prefix, value = locator.split("=", 1)
        key = prefix.strip().lower()
        if key in _LOCATOR_PREFIXES:
            return _LOCATOR_PREFIXES[key], value
    if locator.startswith(("//", "(", "./")):
        return By.XPATH, locator
    return By.CSS_SELECTOR, locator


def prune_dom_html(html: str, max_chars: int = DEFAULT_LLM_MAX_HTML_CHARS) -> str:
    """Trim ``html`` for LLM prompts — drop scripts/styles/comments, cap length."""
    if not html:
        return ""
    cleaned = _SCRIPT_STYLE_STRIP.sub("", html)
    cleaned = _HTML_COMMENT_STRIP.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_chars:
        half = max_chars // 2
        cleaned = cleaned[:half] + " <!-- …truncated… --> " + cleaned[-half:]
    return cleaned


def parse_llm_selector(response: str) -> tuple[str, str] | None:
    """Parse an LLM response of form ``css=…`` / ``xpath=…`` into ``(By, value)``."""
    if not response:
        return None
    text = response.strip().strip("`").splitlines()[0].strip()
    match = _SELECTOR_RESPONSE.fullmatch(text)
    if not match:
        return None
    value = match.group("val").strip()
    if not value:
        return None
    return split_locator(f"{match.group('kind').lower()}={value}")


def build_llm_messages(
    locator: str,
    fingerprint: Fingerprint | None,
    dom_html: str,
) -> list[dict[str, str]]:
    """Assemble the chat payload sent to the LLM."""
    fp_summary: dict[str, Any] = {}
    if fingerprint is not None:
        fp_summary = {
            "tag": fingerprint.tag,
            "text": fingerprint.text,
            "attrs": fingerprint.attrs,
            "previous_xpath": fingerprint.xpath,
        }
    user = (
        f"Original locator that no longer resolves: {locator}\n"
        f"Known fingerprint of the target element: {json.dumps(fp_summary, sort_keys=True)}\n"
        f"Current pruned DOM:\n{dom_html}"
    )
    return [
        {"role": "system", "content": _LLM_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _extract_llm_content(payload: dict[str, Any]) -> str:
    """Pull ``choices[0].message.content`` out of an OpenAI-compatible response.

    Tolerates the three error shapes real providers return on failure:
    ``{"choices": []}``, ``{"choices": null}``, ``{"choices": [null]}``.
    """
    choices = payload.get("choices") or []
    if not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = (message or {}).get("content") or ""
    return content


_GET_XPATH_JS = """
const getXPath = (el) => {
  if (el && el.id) return \"//*[@id='\" + el.id + \"']\";
  const parts = [];
  while (el && el.nodeType === 1) {
    let idx = 1, sib = el.previousSibling;
    while (sib) {
      if (sib.nodeType === 1 && sib.nodeName === el.nodeName) idx++;
      sib = sib.previousSibling;
    }
    parts.unshift(el.nodeName.toLowerCase() + '[' + idx + ']');
    el = el.parentNode;
  }
  return '/' + parts.join('/');
};
"""

_FINGERPRINT_JS = (
    _GET_XPATH_JS
    + """
const el = arguments[0];
const attrs = {};
if (el && el.attributes) {
  for (const a of el.attributes) attrs[a.name] = a.value;
}
return {
  tag: el ? el.tagName.toLowerCase() : '',
  text: (el && el.innerText) ? el.innerText.trim().slice(0, 200) : '',
  attrs: attrs,
  xpath: getXPath(el),
};
"""
)

_ABS_XPATH_JS = _GET_XPATH_JS + "return getXPath(arguments[0]);"


class SelfHealingPlugin(LibraryComponent):
    """SeleniumLibrary plugin that wires self-healing into the core keywords."""

    ROBOT_LIBRARY_VERSION = "1.0.0"

    def __init__(
        self,
        ctx,  # noqa: ANN001
        cache_path: str = str(DEFAULT_CACHE),
        events_path: str = str(DEFAULT_EVENTS),
        threshold: float = 0.6,
        llm_model: str = DEFAULT_LLM_MODEL,
        llm_base_url: str = DEFAULT_LLM_BASE_URL,
        llm_api_key_env: str = DEFAULT_LLM_API_KEY_ENV,
        llm_max_html_chars: int = DEFAULT_LLM_MAX_HTML_CHARS,
        llm_timeout_secs: float = DEFAULT_LLM_TIMEOUT_SECS,
    ) -> None:
        LibraryComponent.__init__(self, ctx)
        self._cache_path = Path(cache_path)
        self._events_path = Path(events_path)
        self._threshold = float(threshold)
        self._cache: dict[str, dict[str, Any]] = self._load_cache()
        self._llm_model = llm_model
        self._llm_base_url = llm_base_url.rstrip("/")
        self._llm_api_key_env = llm_api_key_env
        self._llm_max_html_chars = int(llm_max_html_chars)
        self._llm_timeout_secs = float(llm_timeout_secs)

    # ---------------- overridden SeleniumLibrary keywords ---------------
    @keyword
    def click_element(self, locator, modifier=False, action_chain=False):  # noqa: ANN001
        """Heal-aware override of ``Click Element``."""
        element = self._resolve(locator)
        if action_chain:
            ActionChains(self.driver).click(element).perform()
        elif modifier:
            mod = getattr(Keys, str(modifier).upper(), modifier)
            (
                ActionChains(self.driver)
                .key_down(mod)
                .click(element)
                .key_up(mod)
                .perform()
            )
        else:
            element.click()

    @keyword
    def input_text(self, locator, text, clear=True):  # noqa: ANN001
        """Heal-aware override of ``Input Text``."""
        element = self._resolve(locator)
        if clear:
            element.clear()
        element.send_keys(str(text))

    @keyword
    def input_password(self, locator, password, clear=True):  # noqa: ANN001
        """Heal-aware override of ``Input Password``."""
        element = self._resolve(locator)
        if clear:
            element.clear()
        element.send_keys(str(password))

    @keyword
    def get_text(self, locator):  # noqa: ANN001
        """Heal-aware override of ``Get Text``."""
        return self._resolve(locator).text

    @keyword
    def get_value(self, locator):  # noqa: ANN001
        """Heal-aware override of ``Get Value``."""
        return self._resolve(locator).get_attribute("value") or ""

    @keyword
    def get_webelement(self, locator):  # noqa: ANN001
        """Heal-aware override of ``Get WebElement``."""
        return self._resolve(locator)

    @keyword
    def element_should_be_visible(self, locator, message=None):  # noqa: ANN001
        """Heal-aware override of ``Element Should Be Visible``."""
        element = self._resolve(locator)
        if not element.is_displayed():
            raise AssertionError(message or f"Element '{locator}' is not visible")

    @keyword
    def wait_until_element_is_visible(self, locator, timeout=None, error=None):  # noqa: ANN001
        """Heal-aware override of ``Wait Until Element Is Visible``."""
        deadline = timestr_to_secs(timeout) if timeout else self._timeout_secs()
        by_val = split_locator(locator)
        try:
            WebDriverWait(self.driver, deadline).until(
                EC.visibility_of_element_located(by_val)
            )
        except TimeoutException:
            element = self._heal_fallback(locator)
            if element is None or not element.is_displayed():
                raise AssertionError(
                    error or f"Element '{locator}' not visible in {deadline}s"
                )
            return
        element = self.driver.find_element(*by_val)
        self._update_fingerprint(locator, element)

    @keyword
    def wait_until_element_is_enabled(self, locator, timeout=None, error=None):  # noqa: ANN001
        """Heal-aware override of ``Wait Until Element Is Enabled``."""
        deadline = timestr_to_secs(timeout) if timeout else self._timeout_secs()
        by_val = split_locator(locator)
        try:
            WebDriverWait(self.driver, deadline).until(
                EC.element_to_be_clickable(by_val)
            )
        except TimeoutException:
            element = self._heal_fallback(locator)
            if element is None or not element.is_enabled():
                raise AssertionError(
                    error or f"Element '{locator}' not enabled in {deadline}s"
                )
            return
        element = self.driver.find_element(*by_val)
        self._update_fingerprint(locator, element)

    # ---------------- additional plugin keywords -----------------------
    @keyword
    def prime_heal_cache(self, locator, template_locator):  # noqa: ANN001
        """Store the fingerprint of ``template_locator`` under ``locator``.

        Useful for seeding the cache in demos or right after a known locator
        rename, so the next run resolves ``locator`` via the fingerprint.
        """
        by, val = split_locator(template_locator)
        element = self.driver.find_element(by, val)
        self._update_fingerprint(locator, element)

    @keyword
    def write_healing_report(self, path="results/healing/report.html"):  # noqa: ANN001
        """Render the healing events JSONL as a single HTML table."""
        events = self._read_events()
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = "\n".join(
            "<tr><td>{ts}</td><td>{source}</td><td><code>{locator}</code></td>"
            "<td><code>{healed}</code></td><td>{score:.2f}</td></tr>".format(
                ts=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event["ts"])),
                source=event.get("source", "fingerprint"),
                locator=event["locator"],
                healed=event.get("healed_xpath", ""),
                score=float(event.get("score") or 0.0),
            )
            for event in events
        )
        html = (
            "<!doctype html><meta charset=\"utf-8\">"
            "<title>Self-Healing Locator Report</title>"
            "<style>body{font-family:sans-serif;max-width:1100px;margin:2em auto;color:#222}"
            "table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left;font-size:14px;"
            "vertical-align:top}"
            "th{background:#1f4e78;color:#fff}"
            "tr:nth-child(even){background:#f7f7f7}"
            "code{font-family:monospace;font-size:12px;white-space:pre-wrap}</style>"
            "<h1>Self-Healing Locator Report</h1>"
            f"<p>Healing events: <strong>{len(events)}</strong></p>"
            "<table><thead><tr><th>timestamp</th><th>source</th><th>locator</th>"
            "<th>healed xpath</th><th>score</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        out.write_text(html, encoding="utf-8")
        self.info(f"[Heal] Wrote report with {len(events)} events -> {out}")
        return str(out)

    @keyword
    def clear_healing_cache(self):
        """Drop the in-memory healing cache and delete the JSON file."""
        self._cache = {}
        if self._cache_path.exists():
            self._cache_path.unlink()

    @keyword
    def healing_cache_size(self) -> int:
        """Return the number of locators currently tracked in the heal cache."""
        return len(self._cache)

    # ---------------- internals ----------------------------------------
    def _timeout_secs(self) -> float:
        ctx_timeout = getattr(self.ctx, "timeout", 10.0)
        try:
            return timestr_to_secs(ctx_timeout)
        except (TypeError, ValueError):
            return 10.0

    def _resolve(self, locator: str) -> WebElement:
        try:
            by, val = split_locator(locator)
            elements = self.driver.find_elements(by, val)
            if elements:
                self._update_fingerprint(locator, elements[0])
                return elements[0]
        except WebDriverException:
            pass
        element = self._heal_fallback(locator)
        if element is not None:
            return element
        raise ElementNotFound(
            f"Element with locator '{locator}' not found "
            f"(fingerprint scorer below threshold {self._threshold}; "
            f"LLM heal unavailable or failed)"
        )

    def _heal_fallback(self, locator: str) -> WebElement | None:
        """Try tier 2 (fingerprint) then tier 3 (LLM). Shared by all overrides."""
        element = self._heal_from_cache(locator)
        if element is not None:
            return element
        return self._heal_via_llm(locator)

    def _heal_from_cache(self, locator: str) -> WebElement | None:
        fp_dict = self._cache.get(locator)
        if not fp_dict:
            return None
        fp = Fingerprint.from_dict(fp_dict)
        healed = self._score_best(fp)
        if healed is None:
            return None
        try:
            new_xpath = self.driver.execute_script(_ABS_XPATH_JS, healed["element"])
        except WebDriverException:
            new_xpath = ""
        self._record_event(
            {
                "ts": time.time(),
                "locator": locator,
                "healed_xpath": new_xpath,
                "score": healed["score"],
                "source": "fingerprint",
            }
        )
        self.info(
            f"[Heal] Healed '{locator}' score={healed['score']:.2f} -> xpath='{new_xpath}'"
        )
        if new_xpath:
            self._cache[locator]["xpath"] = new_xpath
            self._save_cache()
        return healed["element"]

    def _score_best(self, fp: Fingerprint) -> dict[str, Any] | None:
        if not fp.tag:
            return None
        candidates = self.driver.find_elements(By.XPATH, f"//{fp.tag}")
        best: tuple[float, WebElement] | None = None
        for candidate in candidates:
            try:
                raw = self._build_fingerprint(candidate)
            except StaleElementReferenceException:
                continue
            c_fp = Fingerprint(
                tag=raw.get("tag", ""),
                text=raw.get("text") or "",
                attrs={k: v for k, v in (raw.get("attrs") or {}).items() if k in TRACKED_ATTRS},
            )
            score = score_fingerprints(fp, c_fp)
            if best is None or score > best[0]:
                best = (score, candidate)
        if best is None or best[0] < self._threshold:
            return None
        return {"element": best[1], "score": best[0]}

    # ---------------- LLM heal tier ------------------------------------
    def _heal_via_llm(self, locator: str) -> WebElement | None:
        api_key = os.environ.get(self._llm_api_key_env)
        if not api_key:
            return None
        fp_dict = self._cache.get(locator)
        fp = Fingerprint.from_dict(fp_dict) if fp_dict else None
        try:
            raw_html = self.driver.execute_script(
                "return document.body ? document.body.outerHTML : '';"
            ) or ""
        except WebDriverException:
            raw_html = ""
        dom = prune_dom_html(raw_html, self._llm_max_html_chars)
        messages = build_llm_messages(locator, fp, dom)
        try:
            response, usage = self._call_llm(messages, api_key)
        except requests.RequestException as exc:
            self.warn(f"[Heal] LLM request failed for '{locator}': {exc}")
            return None
        parsed = parse_llm_selector(response)
        if parsed is None:
            self.warn(
                f"[Heal] LLM response not a selector for '{locator}': {response!r}"
            )
            return None
        by, val = parsed
        kind = "xpath" if by == By.XPATH else "css"
        canonical = f"{kind}={val}"
        try:
            elements = self.driver.find_elements(by, val)
        except WebDriverException as exc:
            self.warn(f"[Heal] LLM selector '{canonical}' rejected by driver: {exc}")
            return None
        if len(elements) != 1:
            self.warn(
                f"[Heal] LLM selector '{canonical}' matched {len(elements)} elements; discarding"
            )
            return None
        element = elements[0]
        try:
            new_xpath = self.driver.execute_script(_ABS_XPATH_JS, element)
        except WebDriverException:
            new_xpath = ""
        self._record_event(
            {
                "ts": time.time(),
                "locator": locator,
                "healed_xpath": new_xpath,
                "score": 0.0,
                "llm_selector": canonical,
                "llm_model": self._llm_model,
                "llm_usage": usage,
                "source": "llm",
            }
        )
        self.info(
            f"[Heal] LLM healed '{locator}' -> '{canonical}' "
            f"(model={self._llm_model}, usage={usage})"
        )
        self._update_fingerprint(locator, element)
        return element

    def _call_llm(
        self,
        messages: list[dict[str, str]],
        api_key: str,
    ) -> tuple[str, dict[str, int]]:
        """POST to the chat-completions endpoint; return (content, usage)."""
        response = requests.post(
            f"{self._llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._llm_model,
                "messages": messages,
                "temperature": 0,
                "max_tokens": 200,
            },
            timeout=self._llm_timeout_secs,
        )
        response.raise_for_status()
        payload = response.json() or {}
        content = _extract_llm_content(payload)
        usage = payload.get("usage") or {}
        return content, {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

    def _update_fingerprint(self, locator: str, element: WebElement) -> None:
        data = self._build_fingerprint(element)
        payload = {
            "tag": data.get("tag", ""),
            "text": data.get("text") or "",
            "attrs": {
                k: v for k, v in (data.get("attrs") or {}).items() if k in TRACKED_ATTRS
            },
            "xpath": data.get("xpath") or "",
            "original_locator": locator,
        }
        if self._cache.get(locator) == payload:
            return
        self._cache[locator] = payload
        self._save_cache()

    def _build_fingerprint(self, element: WebElement) -> dict[str, Any]:
        return self.driver.execute_script(_FINGERPRINT_JS, element) or {
            "tag": "",
            "text": "",
            "attrs": {},
            "xpath": "",
        }

    # ---------------- cache IO -----------------------------------------
    def _load_cache(self) -> dict[str, dict[str, Any]]:
        if self._cache_path.exists():
            try:
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                self.warn(f"[Heal] Cache at {self._cache_path} is corrupt; starting fresh")
        return {}

    def _save_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(self._cache, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _record_event(self, event: dict[str, Any]) -> None:
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        with self._events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")

    def _read_events(self) -> list[dict[str, Any]]:
        if not self._events_path.exists():
            return []
        return [
            json.loads(line)
            for line in self._events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
