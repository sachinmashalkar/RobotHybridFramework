"""Pure-Python tests for the LLM-based locator synthesis tier.

The actual HTTP call is mocked so these tests stay hermetic and browser-free.
"""
from __future__ import annotations

from selenium.webdriver.common.by import By

from libraries.SelfHealingPlugin import (
    DEFAULT_LLM_MAX_HTML_CHARS,
    Fingerprint,
    build_llm_messages,
    parse_llm_selector,
    prune_dom_html,
)


class TestPruneDomHtml:
    def test_returns_empty_for_empty_input(self) -> None:
        assert prune_dom_html("") == ""

    def test_strips_script_and_style_blocks(self) -> None:
        html = (
            "<html><head>"
            "<style>.a{color:red}</style>"
            "<script>var a = 1;</script>"
            "</head><body><button>Go</button></body></html>"
        )
        pruned = prune_dom_html(html)
        assert "<style" not in pruned
        assert "<script" not in pruned
        assert "<button>Go</button>" in pruned

    def test_strips_html_comments(self) -> None:
        html = "<div><!-- hidden --><span>x</span></div>"
        assert "<!--" not in prune_dom_html(html)

    def test_truncates_when_over_budget(self) -> None:
        html = "<div>" + ("a" * 50_000) + "</div>"
        pruned = prune_dom_html(html, max_chars=200)
        assert len(pruned) <= 300
        assert "…truncated…" in pruned

    def test_collapses_whitespace(self) -> None:
        html = "<div>   hello   \n\n  world   </div>"
        assert prune_dom_html(html) == "<div> hello world </div>"


class TestParseLlmSelector:
    def test_parses_css_response(self) -> None:
        assert parse_llm_selector("css=button.primary") == (
            By.CSS_SELECTOR,
            "button.primary",
        )

    def test_parses_xpath_response(self) -> None:
        assert parse_llm_selector("xpath=//button[@id='submit']") == (
            By.XPATH,
            "//button[@id='submit']",
        )

    def test_is_case_insensitive_on_prefix(self) -> None:
        assert parse_llm_selector("CSS=button.primary") == (
            By.CSS_SELECTOR,
            "button.primary",
        )

    def test_tolerates_surrounding_backticks(self) -> None:
        assert parse_llm_selector("`css=button.primary`") == (
            By.CSS_SELECTOR,
            "button.primary",
        )

    def test_tolerates_trailing_newline(self) -> None:
        assert parse_llm_selector("css=button.primary\n") == (
            By.CSS_SELECTOR,
            "button.primary",
        )

    def test_rejects_prose_response(self) -> None:
        assert parse_llm_selector("Sure, try button.primary") is None

    def test_rejects_empty_selector(self) -> None:
        assert parse_llm_selector("css=") is None

    def test_rejects_empty_string(self) -> None:
        assert parse_llm_selector("") is None


class TestBuildLlmMessages:
    def test_has_system_and_user_roles(self) -> None:
        messages = build_llm_messages(
            "css=button.primary",
            Fingerprint(tag="button", text="Login", attrs={"id": "submit"}),
            "<button id='submit'>Login</button>",
        )
        assert [m["role"] for m in messages] == ["system", "user"]
        assert "Selenium locator expert" in messages[0]["content"]

    def test_user_prompt_contains_locator_fingerprint_and_html(self) -> None:
        messages = build_llm_messages(
            "css=button.primary",
            Fingerprint(tag="button", text="Login", attrs={"id": "submit"}),
            "<button id='submit'>Login</button>",
        )
        user = messages[1]["content"]
        assert "css=button.primary" in user
        assert '"tag": "button"' in user
        assert '"text": "Login"' in user
        assert "<button id='submit'>Login</button>" in user

    def test_user_prompt_tolerates_missing_fingerprint(self) -> None:
        messages = build_llm_messages("css=button.primary", None, "<body></body>")
        user = messages[1]["content"]
        assert "css=button.primary" in user
        assert "fingerprint" in user.lower()


class TestDefaults:
    def test_html_char_budget_is_generous_but_bounded(self) -> None:
        assert 1000 <= DEFAULT_LLM_MAX_HTML_CHARS <= 100_000


class TestHealingReportAcceptsMixedEvents:
    """Regression: the report generator must tolerate LLM events (no score)."""

    def test_report_renders_llm_events_without_score(self, tmp_path) -> None:
        import json as _json
        import time as _time
        from unittest.mock import MagicMock

        from libraries.SelfHealingPlugin import SelfHealingPlugin

        cache_path = tmp_path / "cache.json"
        events_path = tmp_path / "events.jsonl"
        events_path.write_text(
            "\n".join(
                [
                    _json.dumps(
                        {
                            "ts": _time.time(),
                            "locator": "css=.primary",
                            "healed_xpath": "/html/body/button[1]",
                            "score": 0.82,
                            "source": "fingerprint",
                        }
                    ),
                    _json.dumps(
                        {
                            "ts": _time.time(),
                            "locator": "css=.missing",
                            "healed_xpath": "/html/body/button[2]",
                            "llm_selector": "css=button.secondary",
                            "llm_model": "gpt-4o-mini",
                            "llm_usage": {"total_tokens": 120},
                            "source": "llm",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        plugin = SelfHealingPlugin.__new__(SelfHealingPlugin)
        plugin._cache_path = cache_path
        plugin._events_path = events_path
        plugin._cache = {}
        plugin.info = MagicMock()

        report_path = tmp_path / "report.html"
        plugin.write_healing_report(str(report_path))

        html = report_path.read_text(encoding="utf-8")
        assert "fingerprint" in html
        assert "llm" in html
        assert "css=.primary" in html
        assert "css=.missing" in html
        assert "0.82" in html
