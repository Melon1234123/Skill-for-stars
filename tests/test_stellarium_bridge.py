from datetime import datetime, timezone

import pytest
from astropy.time import Time

from starskill.schemas import Observer, StellariumSyncRequest
from starskill.stellarium_bridge import StellariumBridge


class StaticJsonBackend:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def get_json(
        self, url: str, *, timeout_seconds: int, max_bytes: int
    ) -> dict[str, object]:
        self.calls.append({"method": "GET", "url": url})
        return self.payload

    def post_form(
        self,
        url: str,
        form: dict[str, str],
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, object]:
        self.calls.append({"method": "POST", "url": url, "form": form})
        return self.payload


class FailingJsonBackend(StaticJsonBackend):
    def get_json(
        self, url: str, *, timeout_seconds: int, max_bytes: int
    ) -> dict[str, object]:
        raise ConnectionError("Stellarium is not running")


def make_request() -> StellariumSyncRequest:
    return StellariumSyncRequest(
        observer=Observer(
            location_name="Beijing",
            longitude=116.4074,
            latitude=39.9042,
            timezone="Asia/Shanghai",
        ),
        timestamp=datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc),
        target="M 42",
    )


def test_bridge_rejects_non_loopback_addresses() -> None:
    with pytest.raises(ValueError, match="loopback"):
        StellariumBridge(
            base_url="http://192.168.1.8:8090", backend=StaticJsonBackend({})
        )


def test_bridge_rejects_non_default_port_without_explicit_override() -> None:
    with pytest.raises(ValueError, match="8090"):
        StellariumBridge(
            base_url="http://127.0.0.1:8091", backend=StaticJsonBackend({})
        )


def test_bridge_uses_only_fixed_remote_control_endpoints_and_form_data() -> None:
    backend = StaticJsonBackend({"ok": True})
    bridge = StellariumBridge(backend=backend)

    result = bridge.sync(make_request())

    timestamp = make_request().timestamp
    assert result == {
        "ok": True,
        "base_url": "http://127.0.0.1:8090",
        "operations": ["status", "location", "time", "focus"],
        "error": None,
    }
    assert backend.calls == [
        {"method": "GET", "url": "http://127.0.0.1:8090/api/main/status"},
        {
            "method": "POST",
            "url": "http://127.0.0.1:8090/api/location/setlocationfields",
            "form": {
                "latitude": "39.9042",
                "longitude": "116.4074",
                "name": "Beijing",
                "planet": "Earth",
            },
        },
        {
            "method": "POST",
            "url": "http://127.0.0.1:8090/api/main/time",
            "form": {"time": str(Time(timestamp).jd), "timerate": "0"},
        },
        {
            "method": "POST",
            "url": "http://127.0.0.1:8090/api/main/focus",
            "form": {"target": "M 42", "mode": "center"},
        },
    ]


def test_bridge_returns_a_structured_failure_for_connection_errors() -> None:
    result = StellariumBridge(backend=FailingJsonBackend({})).sync(make_request())

    assert result == {
        "ok": False,
        "base_url": "http://127.0.0.1:8090",
        "operations": [],
        "error": "connection_error",
    }
