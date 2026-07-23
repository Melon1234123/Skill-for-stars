"""A deliberately bounded bridge to a local Stellarium RemoteControl service."""

import json
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from astropy.time import Time

from starskill.schemas import StellariumSyncRequest


DEFAULT_BASE_URL = "http://127.0.0.1:8090"
_TIMEOUT_SECONDS = 5
_MAX_BYTES = 1_000_000


class RemoteControlBackend(Protocol):
    def get_json(
        self, url: str, *, timeout_seconds: int, max_bytes: int
    ) -> dict[str, object]: ...

    def post_form(
        self,
        url: str,
        form: dict[str, str],
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, object]: ...


class RemoteControlConnectionError(RuntimeError):
    pass


class UrlRemoteControlBackend:
    """Issue bounded JSON requests to a previously validated RemoteControl URL."""

    def get_json(
        self, url: str, *, timeout_seconds: int, max_bytes: int
    ) -> dict[str, object]:
        return self._request(url, None, timeout_seconds, max_bytes)

    def post_form(
        self,
        url: str,
        form: dict[str, str],
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, object]:
        return self._request(url, form, timeout_seconds, max_bytes)

    @staticmethod
    def _request(
        url: str,
        form: dict[str, str] | None,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, object]:
        data = urlencode(form).encode("utf-8") if form is not None else None
        request = Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                **({"Content-Type": "application/x-www-form-urlencoded"} if data else {}),
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                content = response.read(max_bytes + 1)
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            raise RemoteControlConnectionError("remote control request failed") from exc
        if len(content) > max_bytes:
            raise RemoteControlConnectionError("remote control response exceeded byte limit")
        if not content:
            return {}
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteControlConnectionError("remote control response was invalid") from exc
        if not isinstance(payload, dict):
            raise RemoteControlConnectionError("remote control response was not an object")
        return payload


class StellariumBridge:
    """Synchronize only fixed operations with an explicitly local endpoint by default."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        backend: RemoteControlBackend | None = None,
        allow_non_loopback: bool = False,
    ) -> None:
        self._base_url = _validate_base_url(base_url, allow_non_loopback)
        self._backend = backend or UrlRemoteControlBackend()

    def sync(self, request: StellariumSyncRequest) -> dict[str, object]:
        operations: list[str] = []
        try:
            self._backend.get_json(
                f"{self._base_url}/api/main/status",
                timeout_seconds=_TIMEOUT_SECONDS,
                max_bytes=_MAX_BYTES,
            )
            operations.append("status")
            self._backend.post_form(
                f"{self._base_url}/api/location/setlocationfields",
                {
                    "latitude": str(request.observer.latitude),
                    "longitude": str(request.observer.longitude),
                    "name": request.observer.location_name,
                    "planet": "Earth",
                },
                timeout_seconds=_TIMEOUT_SECONDS,
                max_bytes=_MAX_BYTES,
            )
            operations.append("location")
            self._backend.post_form(
                f"{self._base_url}/api/main/time",
                {"time": str(Time(request.timestamp).jd), "timerate": "0"},
                timeout_seconds=_TIMEOUT_SECONDS,
                max_bytes=_MAX_BYTES,
            )
            operations.append("time")
            self._backend.post_form(
                f"{self._base_url}/api/main/focus",
                {"target": request.target, "mode": "center"},
                timeout_seconds=_TIMEOUT_SECONDS,
                max_bytes=_MAX_BYTES,
            )
            operations.append("focus")
        except (RemoteControlConnectionError, ConnectionError, OSError, TimeoutError):
            return {
                "ok": False,
                "base_url": self._base_url,
                "operations": operations,
                "error": "connection_error",
            }
        return {
            "ok": True,
            "base_url": self._base_url,
            "operations": operations,
            "error": None,
        }


def _validate_base_url(base_url: str, allow_non_loopback: bool) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base_url must be an HTTP origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("base_url must specify a valid port") from exc
    if port is None:
        raise ValueError("base_url must specify port 8090")
    if not allow_non_loopback and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("base_url must use a loopback address")
    if not allow_non_loopback and port != 8090:
        raise ValueError("base_url must use port 8090")
    return f"http://{parsed.netloc}"
