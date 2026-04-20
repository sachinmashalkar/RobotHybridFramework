# RobotHybridFramework

Hybrid Robot Framework + SeleniumLibrary automation framework with
fingerprint-based self-healing locators (delivered as a SeleniumLibrary
plugin so the core keywords auto-heal in place), data-driven tests,
Selenium Grid, parallel execution via pabot, and a full GitHub Actions CI
pipeline.

## Self-Healing Locators

`libraries/SelfHealingPlugin.py` is a `SeleniumLibrary.base.LibraryComponent`
subclass registered via the `plugins=` argument on the `SeleniumLibrary`
import in `resources/common/imports.resource`:

```robotframework
Library    SeleniumLibrary    timeout=20s    implicit_wait=2s
...        plugins=libraries.SelfHealingPlugin.SelfHealingPlugin
```

Because SeleniumLibrary plugin keywords with matching names override the
shipped keywords, **the following built-in keywords are transparently replaced
with self-healing variants** — no call-site changes required, no `Heal.`
prefix:

* `Click Element`
* `Input Text` / `Input Password`
* `Get Text` / `Get Value` / `Get WebElement`
* `Element Should Be Visible`
* `Wait Until Element Is Visible`
* `Wait Until Element Is Enabled`

### How it works

Resolution walks three tiers in order. The first tier to return a matching
element wins; later tiers only run when earlier ones fail.

1. **Tier 1 — primary locator.** Plain SeleniumLibrary resolution via
   `driver.find_elements()`. On success the element's **fingerprint** (tag,
   visible text, a curated attribute subset — `id`, `name`, `class`,
   `placeholder`, `aria-label`, `href`, `type`, `role`, `data-testid`,
   `title`, `alt` — and an absolute XPath) is cached under
   `results/healing/cache.json`, keyed by the locator string itself.
2. **Tier 2 — fingerprint scorer.** If the locator resolves to nothing, every
   candidate on the page sharing the cached tag is scored against the stored
   fingerprint by a pure-Python similarity function (`score_fingerprints`).
   Weighting: tag match 0.2, each exact tracked-attribute match 0.2, class
   Jaccard 0.15, exact text 0.25, substring text 0.1; capped at 1.0. The
   highest-scoring candidate above the threshold (default `0.6`) is returned.
3. **Tier 3 — LLM-synthesised locator.** If the fingerprint scorer can't
   decide (no cache entry, or best score below threshold), the plugin asks
   an OpenAI-compatible chat model to synthesise a fresh locator from a
   pruned copy of the current DOM plus the cached fingerprint. The response
   must be `css=…` or `xpath=…` and must resolve to **exactly one** element
   — otherwise it's discarded as untrusted. This tier is opt-in and stays
   dormant unless `OPENAI_API_KEY` (configurable via `llm_api_key_env`) is
   set in the environment.

Every healing event is appended to `results/healing/events.jsonl` with its
source (`fingerprint` or `llm`), score / token usage, and healed XPath, and
the cached XPath is refreshed so later runs pick up the new location
directly.

### Additional plugin keywords

| Keyword                                              | Purpose |
| ---------------------------------------------------- | ------- |
| `Prime Heal Cache    broken_locator    template_locator` | Resolve `template_locator` and store its fingerprint under `broken_locator`. Useful for seeding the cache in demos or right after an intentional locator rename. |
| `Write Healing Report    path=…/report.html`         | Render the HTML summary from `events.jsonl`. |
| `Clear Healing Cache`                                | Drop the in-memory cache and delete the JSON file. |
| `Healing Cache Size`                                 | Return the number of locators currently tracked. |

### Example

```robotframework
*** Settings ***
Resource    resources/common/imports.resource

*** Test Cases ***
Submit Login With Broken Xpath
    Open Login Page
    Prime Heal Cache    css=button[data-devin="missing"]    css=button[type="submit"]
    Input Text    id=username                         tomsmith
    Input Password    id=password                     SuperSecretPassword!
    Click Element    css=button[data-devin="missing"]
    Element Should Be Visible    id=flash
```

The demo suite `tests/ui/self_healing_login.robot` primes the cache against
the real submit button, then clicks via the broken CSS selector and asserts
the login still lands on `/secure`.

### Tuning

Pass constructor arguments on the `plugins=` reference (comma-separated after
the class name) to override the cache path, events path, similarity
threshold, or any of the LLM knobs:

```robotframework
Library    SeleniumLibrary    timeout=20s    implicit_wait=2s
...        plugins=libraries.SelfHealingPlugin.SelfHealingPlugin;results/shared/cache.json;results/shared/events.jsonl;0.55
```

Positional args (in order): `cache_path`, `events_path`, `threshold`,
`llm_model`, `llm_base_url`, `llm_api_key_env`, `llm_max_html_chars`,
`llm_timeout_secs`. Defaults target OpenAI's `gpt-4o-mini` at
`https://api.openai.com/v1`; point `llm_base_url` at an OpenAI-compatible
endpoint (Azure OpenAI, OpenRouter, Ollama, vLLM, Groq, …) to swap providers
without code changes.

### Enabling the LLM tier

Tier 3 runs only when the environment variable named by `llm_api_key_env`
(default `OPENAI_API_KEY`) is populated. Export it in your shell or CI
secrets and the plugin will route unresolved locators through the chat
completions endpoint after the fingerprint scorer fails. Skip it and the
plugin keeps working with tiers 1 and 2 only — no network calls are made.

### Unit tests

Pure-Python tests for the scorer + locator parser live under
`tests/unit/test_self_healing_scorer.py`, and the LLM-tier helpers (DOM
pruning, selector parsing, prompt assembly) are covered by
`tests/unit/test_self_healing_llm.py`. Both run via `pytest`, do not require
a browser, and are executed as part of CI (`unit-tests` job).

## Connecting to a Chromium-based Desktop App (CDP)

`libraries/CdpConnector.py` attaches a SeleniumLibrary session to a
Chromium-based desktop app (Electron, CEF, Tauri/Chromium, any `.exe`
that exposes `--remote-debugging-port=<port>`). It solves the common
"the app launches but Robot hangs on the splash / loading screen until
it times out" symptom.

### Why the splash hangs

The default Selenium `pageLoadStrategy` is `normal`, which blocks every
subsequent command until `document.readyState == "complete"`. Desktop
Chromium apps routinely:

1. show a splash window that navigates away **before** the first
   `load` event fires, so `readyState` never reaches `complete`;
2. expose multiple CDP targets (splash, main window, DevTools, service
   workers) and `chromedriver` attaches to whichever happens to be
   first — often the one that is about to be destroyed;
3. ship a Chromium version that does not match the system
   `chromedriver`, so the driver hangs during the handshake.

There is also a fourth, subtler failure mode specific to desktop
Chromium runtimes: if `chromedriver` attaches **while the splash
target is still the only `page` target**, the attach handshake can
leave the splash renderer wedged in a "loading forever" state, so the
main window never appears. Symptom: the window shows the loading
animation, the DOM never renders, and the Robot script times out
regardless of any `Wait Until ...` values.

`CdpConnect.Connect To CDP App` addresses all four:

| Cause | Knob |
| ----- | ---- |
| Splash `readyState` never reaches `complete` | `page_load_strategy=none` (default) |
| Chromedriver attached to splash / DevTools target | `target_url_contains=<substring>` to switch to the real window post-attach |
| Chromedriver / Chromium version mismatch | `chromedriver_path=<path to matching chromedriver>` |
| Chromedriver attached too early — splash renderer never resumes | `wait_for_target_contains=<substring>` + `post_attach_stop_loading=True` (default) |

### Usage

```robotframework
*** Settings ***
Resource    resources/common/imports.resource

Suite Teardown    CdpConnect.Detach From CDP App    stop_app=False

*** Test Cases ***
Attach To Running Chromium App
    # App is already running with --remote-debugging-port=9222
    CdpConnect.Connect To CDP App
    ...    debugger_address=127.0.0.1:9222
    ...    target_url_contains=app://main
    SeleniumLibrary.Get Location

Launch And Attach
    # Robot Framework owns the app lifecycle
    CdpConnect.Connect To CDP App
    ...    app_path=C:\\Program Files\\MyApp\\MyApp.exe
    ...    app_args=--some-flag
    ...    port=9222
    ...    startup_timeout=90
    ...    target_url_contains=app://main
    ...    chromedriver_path=C:\\Tools\\chromedriver-120\\chromedriver.exe
    SeleniumLibrary.Get Location
```

Arguments (all optional unless noted):

| Arg | Default | Purpose |
| --- | ------- | ------- |
| `debugger_address` | built from `host:port` | `host:port` of the running Chromium DevTools endpoint |
| `app_path` | _none_ | Executable to launch with `--remote-debugging-port=<port>` |
| `app_args` | `""` | Extra CLI args for `app_path`; parsed with `shlex` |
| `host` / `port` | `127.0.0.1` / `9222` | Used when `debugger_address` is omitted |
| `startup_timeout` | `60` | Seconds to wait for `/json/version` to respond |
| `page_load_strategy` | `none` | Override to `eager` or `normal` if your app has no splash |
| `chromedriver_path` | _auto_ | Pin a chromedriver that matches the app's embedded Chromium |
| `wait_for_target_contains` | _none_ | Poll `/json` for a `page` target matching this substring **before** attaching chromedriver. Use when the splash target would otherwise be attached to and freeze. |
| `target_wait_timeout` | `60` | Seconds to wait for `wait_for_target_contains` |
| `target_url_contains` | _none_ | After attach, switch to the first window handle whose URL matches |
| `post_attach_stop_loading` | `True` | Send `Page.stopLoading` via CDP to every window handle right after attach, which unsticks renderers left in a "loading forever" state by the attach handshake |
| `alias` | _none_ | SeleniumLibrary session alias |
| `extra_chrome_args` | `[]` | Additional `options.add_argument(...)` values |

### Diagnosing a hung loading screen

If the splash never renders the DOM, first confirm the app is
actually exposing CDP and inspect its targets **without letting
chromedriver attach**:

```robotframework
${ready}=    CdpConnect.Cdp Is Ready    host=127.0.0.1    port=9222
Should Be True    ${ready}
${targets}=    CdpConnect.List Cdp Targets
Log    ${targets}    level=WARN
```

From `${targets}`, pick the `type=page` entry whose `url` matches
the real window (not the splash or a `chrome-extension://` entry),
then pass a distinctive substring as `wait_for_target_contains` *and*
`target_url_contains`. You can also do this manually in a browser by
opening `http://127.0.0.1:9222/json` on the same machine.

If `chromedriver --version` is more than one major version away from
the `Browser` field reported by `http://127.0.0.1:9222/json/version`,
pin a matching binary via `chromedriver_path=` — a mismatch is the
single most common cause of a frozen renderer during attach.

Supporting keywords:

* `CdpConnect.Detach From CDP App    stop_app=False` — closes the
  Selenium session without killing the app. Pass `stop_app=True` to
  also terminate an app started via `app_path`.
* `CdpConnect.Cdp Is Ready    host=... port=... timeout=2.0` — boolean
  probe of the `/json/version` endpoint.
* `CdpConnect.List Cdp Targets    host=... port=...` — returns the raw
  `/json` target list for debugging multi-window apps.
* `CdpConnect.Wait For Cdp Target    url_contains=app://main    timeout=60` —
  poll `/json` until a matching `page` target appears. Use this
  standalone before `Connect To CDP App` if you want full manual
  control of the wait.
* `CdpConnect.Stop Loading On All Cdp Windows` — resend
  `Page.stopLoading` to every window handle after attach if a
  renderer is still wedged.

### Unit tests

Pure-Python helpers (address parsing, CDP polling, target switching,
launch-command assembly) are covered by
`tests/unit/test_cdp_connector.py` and run as part of the CI
`unit-tests` job — no real Chromium required.

## Local commands

```bash
make install      # pip install -r requirements.txt
make dev-install  # + pre-commit hooks
make lint         # robocop
make format       # robotidy
make test-unit    # pytest tests/unit
make dry-run      # robot --dryrun tests/
make test         # headless chrome UI + API suites
make grid-up      # docker-compose selenium grid (hub + chrome + firefox nodes)
```

See `config/environments/` for per-environment YAML (dev/staging/prod), and
`docs/manual-tests/` for the manual test case exports (Markdown / XLSX /
Xray-Zephyr CSV).
