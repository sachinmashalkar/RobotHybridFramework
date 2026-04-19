"""WebDriver factory with local + Selenium Grid support.

Exposes a single Robot Framework keyword, ``Open Configured Browser``,
that reads ``config/browsers.yaml`` and the ``BROWSER`` / ``USE_GRID``
environment variables to decide how to instantiate the driver.
"""
from __future__ import annotations

import os
from typing import Any

from robot.api import logger
from robot.api.deco import keyword, library
from robot.libraries.BuiltIn import BuiltIn
from selenium.webdriver import ChromeOptions, EdgeOptions, FirefoxOptions

from .ConfigManager import ConfigManager

_OPTION_CLASSES = {
    "chrome": ChromeOptions,
    "firefox": FirefoxOptions,
    "edge": EdgeOptions,
}


@library(scope="GLOBAL", auto_keywords=False)
class BrowserFactory:
    ROBOT_LIBRARY_VERSION = "1.0.0"

    def __init__(self) -> None:
        self._config = ConfigManager()

    @keyword("Open Configured Browser")
    def open_configured_browser(self, url: str | None = None, browser: str | None = None, alias: str | None = None) -> str:
        """Open a browser using the active environment + browser config.

        Returns the SeleniumLibrary browser alias/id.
        """
        selenium = BuiltIn().get_library_instance("SeleniumLibrary")
        browser_cfg = self._config.get_browser_config(browser)
        base_url = url or self._config.get_base_url()

        options = self._build_options(browser_cfg)
        use_grid = os.environ.get("USE_GRID", "false").lower() in {"1", "true", "yes"}

        if use_grid:
            grid_url = browser_cfg.get("grid_url")
            logger.info(f"Opening remote browser {browser_cfg['_id']} on grid {grid_url}")
            browser_alias = selenium.open_browser(
                url=base_url,
                browser=browser_cfg["name"],
                alias=alias,
                remote_url=grid_url,
                options=options,
            )
        else:
            logger.info(f"Opening local browser {browser_cfg['_id']}")
            browser_alias = selenium.open_browser(
                url=base_url,
                browser=browser_cfg["name"],
                alias=alias,
                options=options,
            )

        implicit_wait = self._config.get_config_value("implicit_wait", 5)
        selenium.set_selenium_implicit_wait(f"{implicit_wait}s")
        selenium.set_selenium_timeout(f"{self._config.get_config_value('timeout', 20)}s")
        selenium.maximize_browser_window()
        return browser_alias

    @staticmethod
    def _build_options(browser_cfg: dict[str, Any]) -> str:
        """Build a SeleniumLibrary ``options`` string.

        SeleniumLibrary accepts a string like
        ``add_argument("--headless"); add_argument("--no-sandbox")``.
        """
        name = browser_cfg["name"]
        option_cls = _OPTION_CLASSES.get(name)
        if option_cls is None:
            return ""
        parts: list[str] = []
        for arg in browser_cfg.get("options", []) or []:
            parts.append(f'add_argument("{arg}")')
        prefs = browser_cfg.get("prefs") or {}
        if prefs:
            prefs_inner = ", ".join(f'"{k}": {v!r}' for k, v in prefs.items())
            parts.append(f"add_experimental_option(\"prefs\", {{{prefs_inner}}})")
        return "; ".join(parts)
