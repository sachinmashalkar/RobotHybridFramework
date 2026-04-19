"""Miscellaneous helpers (timestamps, random data, retry)."""
from __future__ import annotations

import random
import string
import time
from datetime import datetime, timezone
from typing import Callable, TypeVar

from faker import Faker
from robot.api import logger
from robot.api.deco import keyword, library

_T = TypeVar("_T")
_FAKE = Faker()


@library(scope="GLOBAL", auto_keywords=False)
class Utils:
    ROBOT_LIBRARY_VERSION = "1.0.0"

    @keyword("Now Iso")
    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    @keyword("Random String")
    def random_string(self, length: int = 8, prefix: str = "") -> str:
        body = "".join(random.choices(string.ascii_lowercase + string.digits, k=int(length)))
        return f"{prefix}{body}"

    @keyword("Random Email")
    def random_email(self) -> str:
        return _FAKE.unique.email()

    @keyword("Fake Person")
    def fake_person(self) -> dict[str, str]:
        return {
            "first_name": _FAKE.first_name(),
            "last_name": _FAKE.last_name(),
            "email": _FAKE.unique.email(),
            "phone": _FAKE.phone_number(),
            "street": _FAKE.street_address(),
            "city": _FAKE.city(),
            "zipcode": _FAKE.postcode(),
        }

    @keyword("Wait Until True")
    def wait_until_true(
        self,
        predicate: Callable[[], _T],
        timeout: float = 10.0,
        interval: float = 0.5,
        message: str = "Condition not satisfied",
    ) -> _T:
        """Poll ``predicate`` until it returns a truthy value or timeout fires."""
        deadline = time.time() + float(timeout)
        last_exc: Exception | None = None
        while time.time() < deadline:
            try:
                value = predicate()
                if value:
                    return value
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.debug(f"Predicate raised: {exc!r}")
            time.sleep(float(interval))
        if last_exc is not None:
            raise AssertionError(f"{message} (last error: {last_exc!r})")
        raise AssertionError(message)
