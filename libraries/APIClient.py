"""Thin wrapper around ``requests`` exposing retry + JSON helpers as keywords.

RequestsLibrary already covers most API needs, so this library focuses on
niceties that are awkward in pure Robot syntax: automatic retries for
idempotent verbs, schema validation, and bearer-token auth.
"""
from __future__ import annotations

from typing import Any

import requests
from robot.api import logger
from robot.api.deco import keyword, library
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _build_session(retries: int) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD", "OPTIONS", "PUT", "DELETE"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


@library(scope="SUITE", auto_keywords=False)
class APIClient:
    ROBOT_LIBRARY_VERSION = "1.0.0"

    def __init__(self, base_url: str = "", retries: int = 3) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = _build_session(retries)
        self._default_headers: dict[str, str] = {"Accept": "application/json"}

    @keyword("Set Base Url")
    def set_base_url(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    @keyword("Set Bearer Token")
    def set_bearer_token(self, token: str) -> None:
        self._default_headers["Authorization"] = f"Bearer {token}"

    @keyword("Send Request")
    def send_request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected_status: int | None = None,
    ) -> requests.Response:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        merged_headers = {**self._default_headers, **(headers or {})}
        logger.info(f"{method.upper()} {url} payload={payload} params={params}")
        response = self._session.request(
            method=method.upper(),
            url=url,
            json=payload if isinstance(payload, (dict, list)) else None,
            data=payload if isinstance(payload, (str, bytes)) else None,
            params=params,
            headers=merged_headers,
            timeout=30,
        )
        logger.info(f"-> {response.status_code} {response.text[:500]}")
        if expected_status is not None and response.status_code != int(expected_status):
            raise AssertionError(
                f"Expected status {expected_status} but got {response.status_code}: {response.text}"
            )
        return response

    @keyword("Response Json Should Contain Key")
    def response_json_should_contain_key(self, response: requests.Response, key: str) -> None:
        body = response.json()
        if key not in body:
            raise AssertionError(f"Key '{key}' missing from response body: {body}")
