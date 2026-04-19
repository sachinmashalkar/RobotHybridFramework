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

1. On first successful resolution, the element's **fingerprint** — tag,
   visible text, a curated attribute subset (`id`, `name`, `class`,
   `placeholder`, `aria-label`, `href`, `type`, `role`, `data-testid`,
   `title`, `alt`), and an absolute XPath — is cached under
   `results/healing/cache.json`, keyed by the locator string itself.
2. If that same locator later fails to resolve anything, every candidate on
   the page sharing the cached tag is scored against the stored fingerprint
   using a pure-Python similarity function (`score_fingerprints`). Weighting:
   tag match 0.2, each exact tracked-attribute match 0.2, class Jaccard 0.15,
   exact text 0.25, substring text 0.1; capped at 1.0.
3. The highest-scoring candidate above the threshold (default `0.6`) is
   returned. Each healing event is appended to
   `results/healing/events.jsonl` and the cached XPath is refreshed so later
   runs pick up the new location directly.

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
the class name) to override the cache path, events path, or similarity
threshold:

```robotframework
Library    SeleniumLibrary    timeout=20s    implicit_wait=2s
...        plugins=libraries.SelfHealingPlugin.SelfHealingPlugin;results/shared/cache.json;results/shared/events.jsonl;0.55
```

### Unit tests

Pure-Python tests for the scorer + locator parser live under
`tests/unit/test_self_healing_scorer.py` and run via `pytest` — they don't
require a browser and are executed as part of CI (`unit-tests` job).

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
