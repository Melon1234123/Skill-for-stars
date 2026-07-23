"""Bounded JSON transport and short-lived cache records for public services."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


USER_AGENT = "StarSkill/0.1 (+educational astronomy workflow)"


class ExternalDataError(RuntimeError):
    code = "external_data_error"


class ExternalDataNetworkError(ExternalDataError):
    code = "external_data_network_error"


class ExternalDataSizeError(ExternalDataError):
    code = "external_data_size_limit"


class ExternalDataFormatError(ExternalDataError):
    code = "external_data_invalid_response"


class JsonBackend(Protocol):
    def fetch_json(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, Any]: ...


class UrlJsonBackend:
    """Fetch one JSON object using a bounded, retry-limited urllib request."""

    def __init__(self, opener: Callable[..., Any] = urlopen) -> None:
        self._opener = opener

    def fetch_json(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )

        for attempt in range(2):
            try:
                with self._opener(request, timeout=timeout_seconds) as response:
                    content_length = response.headers.get("Content-Length")
                    if content_length is not None and int(content_length) > max_bytes:
                        raise ExternalDataSizeError(
                            "external response exceeds the byte limit"
                        )
                    content_type = response.headers.get_content_type()
                    content = response.read(max_bytes + 1)
            except HTTPError as exc:
                if exc.code in (502, 503, 504) and attempt == 0:
                    continue
                raise ExternalDataNetworkError(
                    f"external service HTTP error: {exc.code}"
                ) from exc
            except URLError as exc:
                if attempt == 0:
                    continue
                raise ExternalDataNetworkError("external data request failed") from exc
            except ValueError as exc:
                raise ExternalDataFormatError("invalid response content length") from exc

            if len(content) > max_bytes:
                raise ExternalDataSizeError("external response exceeds the byte limit")
            if content_type.lower() != "application/json":
                raise ExternalDataFormatError(
                    "external response content type is not application/json"
                )
            try:
                payload = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExternalDataFormatError("external response is not valid JSON") from exc
            if not isinstance(payload, dict):
                raise ExternalDataFormatError("external response must be a JSON object")
            return payload

        raise AssertionError("retry loop must return or raise")


def read_cache_record(
    path: Path,
    now: datetime,
    ttl: timedelta,
) -> dict[str, Any] | None:
    """Read a valid unexpired object payload, treating invalid records as misses."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            return None
        cached_at = datetime.fromisoformat(record["cached_at"])
        payload = record["payload"]
        if cached_at.tzinfo is None or cached_at.utcoffset() is None:
            return None
        if now.tzinfo is None or now.utcoffset() is None:
            return None
        if not isinstance(payload, dict) or now - cached_at >= ttl:
            return None
    except (KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    return payload


def write_cache_record(path: Path, payload: dict[str, Any], cached_at: datetime) -> None:
    """Persist one object payload with its cache timestamp as sorted UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"cached_at": cached_at.isoformat(), "payload": payload}
    path.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
