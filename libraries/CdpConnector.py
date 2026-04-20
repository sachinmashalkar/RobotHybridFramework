"""Attach Selenium to a Chromium-based desktop app via CDP.

Context
-------
Chromium-based desktop apps (Electron, CEF, Tauri/Chromium,
custom-built Chromium distros shipped as ``.exe``) can expose a
DevTools Protocol endpoint either because they were launched with
``--remote-debugging-port=<port>`` or because the app does it itself.

Why the splash screen hangs
---------------------------
By default Selenium uses ``pageLoadStrategy="normal"``, which blocks
every subsequent command until ``document.readyState == "complete"``
on the attached target. Desktop Chromium apps routinely:

* show a splash window that navigates away **before** the first load
  event fires, so ``readyState`` never reaches ``complete``;
* expose several CDP targets (splash, main window, DevTools, service
  workers) and chromedriver attaches to whichever happens to be first,
  which is often the one that is about to be destroyed;
* ship a Chromium build whose version does not match the system
  ``chromedriver``, so the driver reports "handshake failed" or hangs.

This library produces a deterministic attach:

* ``page_load_strategy="none"`` by default so ``Create Webdriver``
  returns as soon as the CDP handshake succeeds — no waiting for
  splash navigation to "complete";
* optional ``target_url_contains`` to switch to the real app window
  after attach, bypassing the splash/DevTools targets;
* optional ``chromedriver_path`` so callers can pin a driver whose
  version matches the app's embedded Chromium;
* optional app-launch mode that spawns the executable with
  ``--remote-debugging-port`` and waits for ``/json/version`` before
  the handshake even starts.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

import requests
from robot.api import logger
from robot.api.deco import keyword, library
from robot.libraries.BuiltIn import BuiltIn
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9222
DEFAULT_STARTUP_TIMEOUT = 60.0
DEFAULT_POLL_INTERVAL = 0.5


@library(scope="GLOBAL", auto_keywords=False)
class CdpConnector:
    """Attach Selenium to a Chromium-based desktop app exposing CDP."""

    ROBOT_LIBRARY_VERSION = "1.0.0"

    def __init__(self) -> None:
        self._launched_process: subprocess.Popen[bytes] | None = None
        self._debugger_address: str | None = None
        self._session_alias: str | None = None

    @keyword("Connect To CDP App")
    def connect_to_cdp_app(
        self,
        debugger_address: str | None = None,
        app_path: str | None = None,
        app_args: str = "",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        startup_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        page_load_strategy: str = "none",
        chromedriver_path: str | None = None,
        wait_for_target_contains: str | None = None,
        target_wait_timeout: float = DEFAULT_STARTUP_TIMEOUT,
        target_url_contains: str | None = None,
        post_attach_stop_loading: bool = True,
        alias: str | None = None,
        extra_chrome_args: list[str] | None = None,
    ) -> str:
        """Attach a SeleniumLibrary session to a Chromium-based app over CDP.

        Returns the SeleniumLibrary session alias created via
        ``Create Webdriver``.

        Arguments:

        - ``debugger_address``: ``host:port`` of an already-running
          Chromium with ``--remote-debugging-port``. If omitted, built
          from ``host`` and ``port``.
        - ``app_path``: optional path to a Chromium-based executable.
          When provided the library launches it with
          ``--remote-debugging-port=<port>`` before attaching. Use this
          when Robot Framework should own the app lifecycle. If the app
          is already running, leave this empty.
        - ``app_args``: extra CLI arguments passed to the executable
          when ``app_path`` is set. Parsed with ``shlex`` (Windows mode
          on ``nt``).
        - ``startup_timeout``: seconds to wait for
          ``http://host:port/json/version`` to become reachable.
        - ``page_load_strategy``: ``none`` (default, recommended for
          splash-heavy apps), ``eager``, or ``normal``.
        - ``chromedriver_path``: optional path to a ``chromedriver``
          binary that matches the app's embedded Chromium version.
        - ``wait_for_target_contains``: optional URL substring; before
          attaching chromedriver, poll ``/json`` until a ``page`` target
          whose URL contains this substring exists. Use when the app
          shows a splash/loader target first and chromedriver attaching
          to it freezes the renderer. This delays attach until the real
          window is live.
        - ``target_wait_timeout``: seconds to wait for
          ``wait_for_target_contains`` to succeed.
        - ``target_url_contains``: optional substring; after attach the
          library iterates all window handles and switches to the first
          whose URL contains this string. Useful when the app exposes a
          splash plus a main window.
        - ``post_attach_stop_loading``: when true (default), the library
          sends ``Page.stopLoading`` via CDP to every window handle
          after attach. This unsticks Electron/CEF renderers that end
          up in a "loading forever" state because chromedriver's attach
          handshake interrupted their document parser.
        - ``alias``: SeleniumLibrary alias for the session.
        - ``extra_chrome_args``: extra ``options.add_argument`` values.
        """
        addr = debugger_address or f"{host}:{port}"
        host_part, port_part = self._split_address(addr)

        if app_path:
            self._launch_app(app_path, app_args, port_part)

        self._wait_for_cdp(host_part, port_part, float(startup_timeout))

        if wait_for_target_contains:
            self._wait_for_target(
                host_part, port_part, wait_for_target_contains, float(target_wait_timeout)
            )

        options = ChromeOptions()
        options.add_experimental_option("debuggerAddress", addr)
        options.page_load_strategy = page_load_strategy
        for arg in extra_chrome_args or []:
            options.add_argument(arg)

        service = (
            ChromeService(executable_path=chromedriver_path) if chromedriver_path else ChromeService()
        )

        selenium = BuiltIn().get_library_instance("SeleniumLibrary")
        browser_alias = selenium.create_webdriver(
            "Chrome",
            alias=alias,
            options=options,
            service=service,
        )
        self._debugger_address = addr
        self._session_alias = browser_alias
        logger.info(
            f"Attached SeleniumLibrary session '{browser_alias}' to CDP app at {addr} "
            f"(pageLoadStrategy={page_load_strategy})"
        )

        if post_attach_stop_loading:
            self._stop_loading_on_all_handles(selenium.driver)

        if target_url_contains:
            self._switch_to_target(selenium.driver, target_url_contains)

        return browser_alias

    @keyword("Detach From CDP App")
    def detach_from_cdp_app(self, stop_app: bool = False) -> None:
        """Close only the CDP Selenium session without killing the Chromium app.

        Other SeleniumLibrary sessions (e.g. one opened via
        ``Open Configured Browser``) are left untouched. Set
        ``stop_app=True`` to also terminate the executable if it was
        started by ``Connect To CDP App`` via ``app_path``.
        """
        selenium = BuiltIn().get_library_instance("SeleniumLibrary")
        if self._session_alias is not None:
            try:
                selenium.switch_browser(self._session_alias)
                selenium.close_browser()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warn(f"Error closing CDP Selenium session {self._session_alias!r}: {exc}")
        else:
            logger.info("Detach From CDP App called with no active CDP session; nothing to close.")

        if stop_app and self._launched_process is not None:
            try:
                self._launched_process.terminate()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warn(f"Error terminating launched app: {exc}")
            self._launched_process = None

        self._debugger_address = None
        self._session_alias = None

    @keyword("Cdp Is Ready")
    def cdp_is_ready(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 2.0,
    ) -> bool:
        """Return ``True`` if ``http://host:port/json/version`` responds."""
        try:
            response = requests.get(self._version_url(host, port), timeout=float(timeout))
            response.raise_for_status()
        except Exception:
            return False
        return True

    @keyword("List Cdp Targets")
    def list_cdp_targets(
        self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 5.0
    ) -> list[dict[str, Any]]:
        """Return the raw target list from ``http://host:port/json``."""
        response = requests.get(f"http://{host}:{port}/json", timeout=float(timeout))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected /json payload: {payload!r}")
        return payload

    @keyword("Wait For Cdp Target")
    def wait_for_cdp_target(
        self,
        url_contains: str,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_STARTUP_TIMEOUT,
    ) -> dict[str, Any]:
        """Poll ``/json`` until a ``page`` target's URL contains ``url_contains``.

        Returns the matched target descriptor. Use this before
        ``Connect To CDP App`` (or rely on its ``wait_for_target_contains``
        argument) when the app shows a splash screen that chromedriver
        must not attach to.
        """
        return self._wait_for_target(host, int(port), url_contains, float(timeout))

    @keyword("Stop Loading On All Cdp Windows")
    def stop_loading_on_all_cdp_windows(self) -> None:
        """Send ``Page.stopLoading`` to every window handle on the CDP session.

        Useful when an Electron/CEF renderer is wedged in a "loading
        forever" state after attach. Has no effect on a fully loaded
        page.
        """
        selenium = BuiltIn().get_library_instance("SeleniumLibrary")
        self._stop_loading_on_all_handles(selenium.driver)

    def _launch_app(self, app_path: str, app_args: str, port: int) -> None:
        exe = Path(app_path)
        if not exe.exists():
            raise FileNotFoundError(f"App executable not found: {app_path}")

        is_windows = os.name == "nt"
        parsed_args = shlex.split(app_args, posix=not is_windows) if app_args else []
        cmd = [str(exe), f"--remote-debugging-port={port}", *parsed_args]
        logger.info(f"Launching CDP app: {cmd}")

        kwargs: dict[str, Any] = {"close_fds": True}
        if is_windows:
            # Detach so a Robot teardown failure does not also kill the app.
            creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            kwargs["creationflags"] = creation_flags
        else:
            kwargs["start_new_session"] = True

        # Intentionally do NOT pipe stdout/stderr: some Electron apps
        # deadlock waiting for a pipe reader that Robot never attaches.
        self._launched_process = subprocess.Popen(cmd, **kwargs)

    @staticmethod
    def _stop_loading_on_all_handles(driver: Any) -> None:
        original = None
        try:
            original = driver.current_window_handle
        except Exception:  # pragma: no cover - defensive
            original = None
        for handle in list(driver.window_handles):
            try:
                driver.switch_to.window(handle)
                driver.execute_cdp_cmd("Page.stopLoading", {})
                logger.info(f"Page.stopLoading sent to handle {handle}")
            except Exception as exc:  # pragma: no cover - defensive
                logger.info(f"Page.stopLoading failed on handle {handle}: {exc}")
        if original is not None:
            try:
                driver.switch_to.window(original)
            except Exception:  # pragma: no cover - defensive
                pass

    def _wait_for_target(
        self, host: str, port: int, url_contains: str, timeout: float
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_seen: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            try:
                targets = self.list_cdp_targets(host=host, port=port, timeout=2.0)
            except Exception as exc:
                logger.info(f"/json fetch failed while waiting for target: {exc}")
                time.sleep(DEFAULT_POLL_INTERVAL)
                continue
            last_seen = targets
            for target in targets:
                if target.get("type") != "page":
                    continue
                url = target.get("url", "")
                if url_contains in url:
                    logger.info(f"CDP target matched {url_contains!r}: {url}")
                    return target
            time.sleep(DEFAULT_POLL_INTERVAL)
        summary = [
            {"type": t.get("type"), "url": t.get("url")} for t in last_seen
        ] or "<empty>"
        raise RuntimeError(
            f"No CDP page target whose URL contains {url_contains!r} appeared within "
            f"{timeout}s. Last seen targets: {summary}"
        )

    def _wait_for_cdp(self, host: str, port: int, timeout: float) -> None:
        url = self._version_url(host, port)
        deadline = time.monotonic() + timeout
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = requests.get(url, timeout=2.0)
                response.raise_for_status()
                logger.info(f"CDP endpoint reachable: {url}")
                return
            except Exception as exc:
                last_err = exc
                time.sleep(DEFAULT_POLL_INTERVAL)
        raise RuntimeError(
            f"CDP endpoint {url} did not respond within {timeout}s: {last_err!r}. "
            "Verify the app was launched with --remote-debugging-port and that no "
            "firewall blocks the port."
        )

    @staticmethod
    def _switch_to_target(driver: Any, url_substring: str) -> None:
        for handle in list(driver.window_handles):
            driver.switch_to.window(handle)
            try:
                current = driver.current_url
            except Exception:
                continue
            if url_substring in current:
                logger.info(f"Switched to CDP target: {current}")
                return
        raise AssertionError(
            f"No CDP target URL contains {url_substring!r}. "
            f"Open handles: {list(driver.window_handles)}"
        )

    @staticmethod
    def _split_address(addr: str) -> tuple[str, int]:
        if ":" not in addr:
            raise ValueError(f"debugger_address must be host:port, got {addr!r}")
        host, port = addr.rsplit(":", 1)
        if not host or not port:
            raise ValueError(f"debugger_address must be host:port, got {addr!r}")
        return host, int(port)

    @staticmethod
    def _version_url(host: str, port: int) -> str:
        return f"http://{host}:{port}/json/version"
