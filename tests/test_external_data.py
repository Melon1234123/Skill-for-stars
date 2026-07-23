import json
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from starskill.external_data import (
    ExternalDataFormatError,
    ExternalDataNetworkError,
    ExternalDataSizeError,
    UrlJsonBackend,
    read_cache_record,
    write_cache_record,
)


class FakeResponse:
    def __init__(self, content: bytes, content_type: str = "application/json") -> None:
        self.content = content
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.read_limit: int | None = None

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_limit = size
        return self.content if size < 0 else self.content[:size]


def test_cache_expires_without_returning_stale_payload(tmp_path: Path) -> None:
    path = tmp_path / "weather.json"
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    payload = {"hourly": {"time": []}}

    write_cache_record(path, payload, now)

    assert read_cache_record(path, now + timedelta(minutes=29), timedelta(minutes=30)) == payload
    assert read_cache_record(path, now + timedelta(minutes=30), timedelta(minutes=30)) is None
    assert read_cache_record(path, now + timedelta(minutes=31), timedelta(minutes=30)) is None


@pytest.mark.parametrize(
    "record",
    [
        "[]",
        '{"cached_at": "not-a-date", "payload": {}}',
        '{"cached_at": "2026-07-23T00:00:00", "payload": {}}',
        '{"cached_at": "2026-07-23T00:00:00+00:00", "payload": []}',
    ],
)
def test_cache_ignores_invalid_records(tmp_path: Path, record: str) -> None:
    path = tmp_path / "cache" / "record.json"
    path.parent.mkdir()
    path.write_text(record, encoding="utf-8")

    assert read_cache_record(path, datetime(2026, 7, 23, tzinfo=timezone.utc), timedelta(hours=1)) is None


def test_cache_writer_creates_sorted_utf8_record(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "record.json"
    now = datetime(2026, 7, 23, 10, 30, tzinfo=timezone.utc)

    write_cache_record(path, {"z": 1, "a": "星"}, now)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "cached_at": "2026-07-23T10:30:00+00:00",
        "payload": {"a": "星", "z": 1},
    }
    assert '"a": "星"' in path.read_text(encoding="utf-8")


def test_backend_rejects_a_non_object_json_response() -> None:
    backend = UrlJsonBackend(opener=lambda request, timeout: FakeResponse(b"[]"))

    with pytest.raises(ExternalDataFormatError, match="JSON object"):
        backend.fetch_json("https://example.test", timeout_seconds=1, max_bytes=100)


def test_backend_sends_json_headers_and_uses_bounded_read() -> None:
    response = FakeResponse(b'{"result": true}', "application/json; charset=utf-8")
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return response

    result = UrlJsonBackend(opener=opener).fetch_json(
        "https://example.test/data", timeout_seconds=4, max_bytes=100
    )

    assert result == {"result": True}
    assert captured["request"].get_header("Accept") == "application/json"
    assert captured["request"].get_header("User-agent") == "StarSkill/0.1 (+educational astronomy workflow)"
    assert captured["timeout"] == 4
    assert response.read_limit == 101


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(b'{"result": true}', "text/html"),
        FakeResponse(b"not json"),
    ],
)
def test_backend_rejects_invalid_content(response: FakeResponse) -> None:
    backend = UrlJsonBackend(opener=lambda request, timeout: response)

    with pytest.raises(ExternalDataFormatError):
        backend.fetch_json("https://example.test", timeout_seconds=1, max_bytes=100)


def test_backend_rejects_declared_and_actual_oversize_responses() -> None:
    declared = FakeResponse(b"{}")
    declared.headers["Content-Length"] = "101"
    actual = FakeResponse(b"x" * 101)

    for response in (declared, actual):
        backend = UrlJsonBackend(opener=lambda request, timeout, response=response: response)
        with pytest.raises(ExternalDataSizeError):
            backend.fetch_json("https://example.test", timeout_seconds=1, max_bytes=100)


def test_backend_retries_one_transient_url_error() -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("temporary outage")
        return FakeResponse(b'{"ok": true}')

    assert UrlJsonBackend(opener=opener).fetch_json(
        "https://example.test", timeout_seconds=1, max_bytes=100
    ) == {"ok": True}
    assert calls == 2


def test_backend_retries_one_transient_http_error_then_maps_exhaustion() -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError("https://example.test", 503, "unavailable", {}, None)

    with pytest.raises(ExternalDataNetworkError) as error:
        UrlJsonBackend(opener=opener).fetch_json(
            "https://example.test", timeout_seconds=1, max_bytes=100
        )

    assert error.value.code == "external_data_network_error"
    assert calls == 2


def test_backend_does_not_retry_non_transient_http_errors() -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError("https://example.test", 404, "not found", {}, None)

    with pytest.raises(ExternalDataNetworkError):
        UrlJsonBackend(opener=opener).fetch_json(
            "https://example.test", timeout_seconds=1, max_bytes=100
        )

    assert calls == 1
