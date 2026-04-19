"""Robot Framework listener for screenshots + run metadata.

Attach via ``--listener libraries/CustomListener.py``. Captures a screenshot
when a UI test fails, writes run-level metadata (browser, env), and logs
useful information to the console.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from robot.api import logger
from robot.libraries.BuiltIn import BuiltIn


class CustomListener:
    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self, screenshots_dir: str = "results/screenshots") -> None:
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._start_time = 0.0

    # --- suite ---------------------------------------------------------
    def start_suite(self, suite, result) -> None:  # noqa: D401, ANN001
        if suite.parent is None:  # root suite
            self._start_time = time.time()
            suite.metadata["Environment"] = os.environ.get("TEST_ENV", "dev")
            suite.metadata["Browser"] = os.environ.get("BROWSER", "chrome")
            suite.metadata["Grid"] = os.environ.get("USE_GRID", "false")
            logger.console(
                f"\n[CustomListener] Starting run | env={suite.metadata['Environment']} "
                f"browser={suite.metadata['Browser']} grid={suite.metadata['Grid']}"
            )

    def end_suite(self, suite, result) -> None:  # noqa: ANN001
        if suite.parent is None:
            elapsed = time.time() - self._start_time
            stats = getattr(result, "statistics", None)
            passed = getattr(stats, "passed", "?") if stats is not None else "?"
            failed = getattr(stats, "failed", "?") if stats is not None else "?"
            logger.console(
                f"[CustomListener] Run complete in {elapsed:.1f}s | "
                f"passed={passed} failed={failed}"
            )

    # --- test ----------------------------------------------------------
    def end_test(self, test, result) -> None:  # noqa: ANN001
        if result.status != "FAIL":
            return
        try:
            selenium = BuiltIn().get_library_instance("SeleniumLibrary")
        except Exception:  # noqa: BLE001 - SeleniumLibrary not loaded (API-only test)
            return
        if not self._has_active_driver(selenium):
            return
        filename = self.screenshots_dir / f"fail_{self._slug(test.name)}_{int(time.time())}.png"
        try:
            selenium.capture_page_screenshot(str(filename))
            result.message = f"{result.message}\n[Screenshot] {filename}"
            logger.console(f"[CustomListener] Saved failure screenshot: {filename}")
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"[CustomListener] Screenshot capture failed: {exc}")

    @staticmethod
    def _has_active_driver(selenium) -> bool:  # noqa: ANN001
        for attr in ("_drivers", "driver_cache"):
            cache = getattr(selenium, attr, None)
            if cache is not None and getattr(cache, "active_drivers", None):
                return True
        return False

    @staticmethod
    def _slug(name: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in name)[:60]
