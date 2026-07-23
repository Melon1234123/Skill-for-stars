from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from starskill.external_data import ExternalDataNetworkError


class StaticJsonBackend:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def fetch_json(self, url: str, *, timeout_seconds: int, max_bytes: int) -> dict:
        self.calls.append(
            {"url": url, "timeout_seconds": timeout_seconds, "max_bytes": max_bytes}
        )
        return self.payload


class FailingJsonBackend:
    def fetch_json(self, url: str, *, timeout_seconds: int, max_bytes: int) -> dict:
        raise ExternalDataNetworkError("service unavailable")


class OSErrorJsonBackend:
    def fetch_json(self, url: str, *, timeout_seconds: int, max_bytes: int) -> dict:
        raise OSError("connection reset")


def fixed_clock() -> datetime:
    return datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def test_apod_provider_reads_its_key_and_cache_directory_from_environment(
    monkeypatch, tmp_path: Path
) -> None:
    from starskill.nasa import NasaApodProvider

    monkeypatch.setenv("STARSKILL_NASA_API_KEY", "test-key")
    monkeypatch.setenv("STARSKILL_NASA_CACHE_DIR", str(tmp_path / "nasa-cache"))

    provider = NasaApodProvider.from_environment()

    assert provider._api_key == "test-key"
    assert provider._cache_dir == tmp_path / "nasa-cache"


def test_apod_never_calls_network_without_a_key(tmp_path: Path) -> None:
    from starskill.nasa import NasaApodProvider

    backend = StaticJsonBackend({})
    result = NasaApodProvider(
        api_key=None, backend=backend, cache_dir=tmp_path, clock=fixed_clock
    ).get_feature(None)

    assert (result.source.issue_code, len(backend.calls)) == ("nasa_api_key_missing", 0)
    assert result.source.provider == "NASA APOD"
    assert result.source.source_url == "https://api.nasa.gov/planetary/apod"
    assert result.source.accessed_at == fixed_clock()
    assert result.source.from_cache is False
    assert result.source.availability == "unavailable"


def test_apod_maps_response_and_reuses_a_24_hour_cache(tmp_path: Path) -> None:
    from starskill.nasa import NasaApodProvider

    backend = StaticJsonBackend(
        {
            "date": "2026-01-10",
            "title": "A Test Nebula",
            "media_type": "image",
            "url": "https://apod.nasa.gov/apod/image/test.jpg",
            "explanation": "A deterministic test response.",
            "copyright": "NASA",
        }
    )
    provider = NasaApodProvider(
        api_key="test-key", backend=backend, cache_dir=tmp_path, clock=fixed_clock
    )

    fresh = provider.get_feature("2026-01-10")
    cached = provider.get_feature("2026-01-10")

    assert fresh.date == "2026-01-10"
    assert fresh.title == "A Test Nebula"
    assert fresh.media_type == "image"
    assert fresh.media_url == "https://apod.nasa.gov/apod/image/test.jpg"
    assert fresh.explanation == "A deterministic test response."
    assert fresh.copyright == "NASA"
    assert fresh.source.provider == "NASA APOD"
    assert fresh.source.source_url == "https://api.nasa.gov/planetary/apod?date=2026-01-10"
    assert fresh.source.accessed_at == fixed_clock()
    assert fresh.source.from_cache is False
    assert fresh.source.availability == "fresh"
    assert cached.source.from_cache is True
    assert cached.source.availability == "cached"
    assert len(backend.calls) == 1

    request_query = parse_qs(urlparse(backend.calls[0]["url"]).query)
    assert request_query == {"api_key": ["test-key"], "date": ["2026-01-10"]}


def test_apod_refreshes_cache_at_the_24_hour_boundary(tmp_path: Path) -> None:
    from starskill.nasa import NasaApodProvider

    backend = StaticJsonBackend(
        {
            "date": "2026-01-10",
            "title": "A Test Nebula",
            "media_type": "image",
            "url": "https://apod.nasa.gov/apod/image/test.jpg",
        }
    )
    NasaApodProvider(
        api_key="test-key", backend=backend, cache_dir=tmp_path, clock=fixed_clock
    ).get_feature("2026-01-10")
    refreshed = NasaApodProvider(
        api_key="test-key",
        backend=backend,
        cache_dir=tmp_path,
        clock=lambda: fixed_clock() + timedelta(hours=24),
    ).get_feature("2026-01-10")

    assert refreshed.source.availability == "fresh"
    assert refreshed.source.from_cache is False
    assert len(backend.calls) == 2


def test_apod_malformed_or_failed_response_is_unavailable(tmp_path: Path) -> None:
    from starskill.nasa import NasaApodProvider

    malformed = NasaApodProvider(
        api_key="test-key", backend=StaticJsonBackend({}), cache_dir=tmp_path, clock=fixed_clock
    ).get_feature(None)
    failed = NasaApodProvider(
        api_key="test-key", backend=FailingJsonBackend(), cache_dir=tmp_path, clock=fixed_clock
    ).get_feature(None)

    assert malformed.source.availability == "unavailable"
    assert malformed.source.issue_code == "external_data_invalid_response"
    assert failed.source.availability == "unavailable"
    assert failed.source.issue_code == "external_data_network_error"


def test_apod_maps_backend_os_error_to_an_unavailable_result(tmp_path: Path) -> None:
    from starskill.nasa import NasaApodProvider

    result = NasaApodProvider(
        api_key="test-key",
        backend=OSErrorJsonBackend(),
        cache_dir=tmp_path,
        clock=fixed_clock,
    ).get_feature("2026-01-10")

    assert result.source.provider == "NASA APOD"
    assert result.source.source_url == "https://api.nasa.gov/planetary/apod?date=2026-01-10"
    assert result.source.accessed_at == fixed_clock()
    assert result.source.from_cache is False
    assert result.source.availability == "unavailable"
    assert result.source.issue_code == "external_data_network_error"
