"""Unit tests for libraries.CdpConnector helpers.

The tests cover pure-Python pieces of the connector — address parsing,
startup polling, and target switching — without booting a real Chromium
instance.
"""
from __future__ import annotations

import http.server
import socket
import threading
from typing import Any, Callable

import pytest

from libraries.CdpConnector import CdpConnector


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _VersionHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if self.path == "/json/version":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"Browser": "Chrome/120.0.0.0"}')
        elif self.path == "/json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'[{"id": "abc", "url": "app://main"}]')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: D401
        """Silence the default stderr logging during tests."""
        return


class _CdpServer:
    def __init__(self) -> None:
        self.port = _free_port()
        self._httpd = http.server.HTTPServer(("127.0.0.1", self.port), _VersionHandler)
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
        assert targets == [{"id": "abc", "url": "app://main"}]


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
