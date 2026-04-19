"""Environment and browser configuration loader.

Reads YAML config files from ``config/`` and exposes their contents as
Robot Framework keywords so suites can fetch environment-specific values
without hard-coding anything.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from robot.api.deco import keyword, library

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


@library(scope="GLOBAL", auto_keywords=False)
class ConfigManager:
    """Load environment + browser configuration once per suite run."""

    ROBOT_LIBRARY_VERSION = "1.0.0"

    def __init__(self, environment: str | None = None) -> None:
        env = environment or os.environ.get("TEST_ENV", "dev")
        self._env_name = env
        self._env_cfg = self._load_yaml(CONFIG_DIR / "environments" / f"{env}.yaml")
        self._browser_cfg = self._load_yaml(CONFIG_DIR / "browsers.yaml")

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    @keyword("Get Environment")
    def get_environment(self) -> str:
        return self._env_name

    @keyword("Get Config Value")
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """Dot-notation lookup into the environment config.

        Example: ``Get Config Value    default_user.username``
        """
        node: Any = self._env_cfg
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @keyword("Get Browser Config")
    def get_browser_config(self, browser: str | None = None) -> dict[str, Any]:
        browser = browser or os.environ.get("BROWSER") or self._browser_cfg.get("default", "chrome")
        browsers = self._browser_cfg.get("browsers", {})
        if browser not in browsers:
            raise ValueError(f"Unknown browser '{browser}'. Known: {sorted(browsers)}")
        cfg = dict(browsers[browser])
        cfg["_id"] = browser
        cfg["grid_url"] = self._browser_cfg.get("grid_url")
        return cfg

    @keyword("Get Base Url")
    def get_base_url(self) -> str:
        return self.get_config_value("base_url")

    @keyword("Get Api Base Url")
    def get_api_base_url(self) -> str:
        return self.get_config_value("api_base_url")
