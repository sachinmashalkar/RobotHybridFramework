"""Unit tests for libraries.CdpConnector helpers.

The tests cover pure-Python pieces of the connector — address parsing,
startup polling, and target switching — without booting a real Chromium
instance.
"""
from __future__ import annotations

import http.server
import json
import socket
import threading
from typing import Any, Callable

import pytest

from libraries.CdpConnector import _BROWSER_ALIASES, CdpConnector


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _CdpServer:
    """In-process HTTP server that mimics the CDP ``/json/*`` endpoints.

    Tests can swap the ``targets`` attribute at runtime to simulate the
    desktop app gradually exposing new targets (splash → main window).
    """

    def __init__(self, targets: list[dict[str, Any]] | None = None) -> None:
        self.port = _free_port()
        self.targets: list[dict[str, Any]] = list(
            targets if targets is not None else [{"id": "abc", "type": "page", "url": "app://main"}]
        )

        server = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(inner) -> None:  # noqa: N802 - stdlib name
                if inner.path == "/json/version":
                    body = b'{"Browser": "Chrome/120.0.0.0"}'
                elif inner.path == "/json":
                    body = json.dumps(server.targets).encode("utf-8")
                else:
                    inner.send_response(404)
                    inner.end_headers()
                    return
                inner.send_response(200)
                inner.send_header("Content-Type", "application/json")
                inner.end_headers()
                inner.wfile.write(body)

            def log_message(inner, *_args: Any, **_kwargs: Any) -> None:  # noqa: D401
                """Silence the default stderr logging during tests."""
                return

        self._httpd = http.server.HTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> "_CdpServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._httpd.shutdown()
        self._thread.join(timeout=5)
        self._httpd.server_close()


class _FakeDriver:
    def __init__(self, handles_to_urls: dict[str, str]) -> None:
        self._urls = handles_to_urls
        self.window_handles = list(handles_to_urls.keys())
        self._current: str | None = None
        self.cdp_calls: list[tuple[str, str, dict[str, Any]]] = []

        connector = self

        class _SwitchTo:
            def window(self, handle: str) -> None:
                connector._current = handle

        self.switch_to = _SwitchTo()

    @property
    def current_url(self) -> str:
        if self._current is None:
            raise RuntimeError("switch_to.window was never called")
        return self._urls[self._current]

    @property
    def current_window_handle(self) -> str:
        if self._current is None:
            raise RuntimeError("switch_to.window was never called")
        return self._current

    def execute_cdp_cmd(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self._current is not None, "Must switch to a window before sending CDP"
        self.cdp_calls.append((self._current, method, params))
        return {}


def test_split_address_parses_host_and_port() -> None:
    assert CdpConnector._split_address("localhost:9222") == ("localhost", 9222)
    assert CdpConnector._split_address("127.0.0.1:12345") == ("127.0.0.1", 12345)


@pytest.mark.parametrize("bad", ["9222", "localhost", ":9222", "localhost:"])
def test_split_address_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        CdpConnector._split_address(bad)


def test_version_url_shape() -> None:
    assert CdpConnector._version_url("h", 1) == "http://h:1/json/version"


def test_cdp_is_ready_true_when_endpoint_responds() -> None:
    with _CdpServer() as server:
        connector = CdpConnector()
        assert connector.cdp_is_ready(host="127.0.0.1", port=server.port, timeout=2.0) is True


def test_cdp_is_ready_false_when_endpoint_unreachable() -> None:
    connector = CdpConnector()
    assert connector.cdp_is_ready(host="127.0.0.1", port=_free_port(), timeout=0.5) is False


def test_wait_for_cdp_returns_when_endpoint_live() -> None:
    with _CdpServer() as server:
        connector = CdpConnector()
        connector._wait_for_cdp("127.0.0.1", server.port, timeout=5.0)


def test_wait_for_cdp_raises_on_timeout() -> None:
    connector = CdpConnector()
    with pytest.raises(RuntimeError, match="did not respond"):
        connector._wait_for_cdp("127.0.0.1", _free_port(), timeout=1.0)


def test_list_cdp_targets_returns_payload() -> None:
    with _CdpServer() as server:
        connector = CdpConnector()
        targets = connector.list_cdp_targets(host="127.0.0.1", port=server.port, timeout=2.0)
        assert targets == [{"id": "abc", "type": "page", "url": "app://main"}]


def test_wait_for_target_returns_matching_page() -> None:
    with _CdpServer(
        targets=[
            {"id": "s", "type": "page", "url": "app://splash"},
            {"id": "m", "type": "page", "url": "app://main/home"},
        ]
    ) as server:
        connector = CdpConnector()
        matched = connector._wait_for_target("127.0.0.1", server.port, "main", timeout=5.0)
        assert matched["url"] == "app://main/home"


def test_wait_for_target_ignores_non_page_types() -> None:
    with _CdpServer(
        targets=[{"id": "w", "type": "service_worker", "url": "app://main"}]
    ) as server:
        connector = CdpConnector()
        with pytest.raises(RuntimeError, match="No CDP page target"):
            connector._wait_for_target("127.0.0.1", server.port, "main", timeout=1.0)


def test_wait_for_target_appears_after_delay() -> None:
    with _CdpServer(
        targets=[{"id": "s", "type": "page", "url": "app://splash"}]
    ) as server:
        connector = CdpConnector()

        def add_main() -> None:
            import time as _t

            _t.sleep(0.4)
            server.targets.append({"id": "m", "type": "page", "url": "app://main"})

        threading.Thread(target=add_main, daemon=True).start()
        matched = connector._wait_for_target("127.0.0.1", server.port, "main", timeout=5.0)
        assert matched["id"] == "m"


@pytest.mark.parametrize(
    "name,expected",
    [
        ("chrome", "chrome"),
        ("Chrome", "chrome"),
        ("chromium", "chrome"),
        ("edge", "edge"),
        ("Edge", "edge"),
        ("MSEdge", "edge"),
        ("WebView2", "edge"),
    ],
)
def test_browser_aliases_normalise_to_supported_kind(name: str, expected: str) -> None:
    assert _BROWSER_ALIASES[name.strip().lower()] == expected


def test_stop_loading_on_all_handles_sends_page_stop_loading() -> None:
    driver = _FakeDriver({"h1": "app://splash", "h2": "app://main"})
    driver.switch_to.window("h1")
    CdpConnector._stop_loading_on_all_handles(driver)
    methods = [(handle, method) for handle, method, _ in driver.cdp_calls]
    assert ("h1", "Page.stopLoading") in methods
    assert ("h2", "Page.stopLoading") in methods
    assert driver.current_window_handle == "h1"


def test_switch_to_target_picks_matching_url() -> None:
    driver = _FakeDriver({"h1": "app://splash", "h2": "app://main/dashboard"})
    CdpConnector._switch_to_target(driver, "main")
    assert driver.current_url == "app://main/dashboard"


def test_switch_to_target_raises_when_no_match() -> None:
    driver = _FakeDriver({"h1": "app://splash"})
    with pytest.raises(AssertionError, match="No CDP target URL contains"):
        CdpConnector._switch_to_target(driver, "dashboard")


def test_launch_app_raises_for_missing_executable(tmp_path: Any) -> None:
    connector = CdpConnector()
    missing = tmp_path / "does-not-exist.exe"
    with pytest.raises(FileNotFoundError):
        connector._launch_app(str(missing), "", 9222)


def test_launch_app_spawns_process(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_exe = tmp_path / "fake.exe"
    fake_exe.write_text("#!/bin/sh\nexit 0\n")
    fake_exe.chmod(0o755)

    recorded: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, cmd: list[str], **kwargs: Any) -> None:
            recorded["cmd"] = cmd
            recorded["kwargs"] = kwargs

        def terminate(self) -> None:  # pragma: no cover - not exercised here
            recorded["terminated"] = True

    monkeypatch.setattr("libraries.CdpConnector.subprocess.Popen", _FakePopen)

    connector = CdpConnector()
    connector._launch_app(str(fake_exe), "--flag=value --other", 9222)

    assert recorded["cmd"][0] == str(fake_exe)
    assert "--remote-debugging-port=9222" in recorded["cmd"]
    assert "--flag=value" in recorded["cmd"]
    assert "--other" in recorded["cmd"]
