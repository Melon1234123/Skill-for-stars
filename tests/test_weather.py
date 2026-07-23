from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from starskill.external_data import ExternalDataFormatError, ExternalDataNetworkError
from starskill.schemas import ObservingConditionsRequest


class StaticJsonBackend:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def fetch_json(self, url: str, *, timeout_seconds: int, max_bytes: int) -> dict:
        self.calls.append(
            {
                "url": url,
                "timeout_seconds": timeout_seconds,
                "max_bytes": max_bytes,
            }
        )
        return self.payload


class FailingJsonBackend:
    def fetch_json(self, url: str, *, timeout_seconds: int, max_bytes: int) -> dict:
        raise ExternalDataNetworkError("service unavailable")


def make_conditions_request() -> ObservingConditionsRequest:
    return ObservingConditionsRequest.model_validate(
        {
            "observer": {
                "location_name": "Beijing",
                "longitude": 116.4074,
                "latitude": 39.9042,
                "timezone": "Asia/Shanghai",
            },
            "time_range": {
                "start": "2026-01-10T20:00:00+08:00",
                "end": "2026-01-11T02:00:00+08:00",
            },
        }
    )


def fixed_clock() -> datetime:
    return datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def test_weather_provider_maps_hourly_values_and_reuses_cache(tmp_path: Path) -> None:
    from starskill.weather import OpenMeteoWeatherProvider

    backend = StaticJsonBackend(
        {
            "hourly": {
                "time": ["2026-01-10T20:00"],
                "cloud_cover": [24],
                "precipitation": [0.0],
                "wind_speed_10m": [7.2],
                "visibility": [12000],
            }
        }
    )
    provider = OpenMeteoWeatherProvider(
        backend=backend, cache_dir=tmp_path, clock=fixed_clock
    )

    fresh = provider.get_forecast(make_conditions_request())
    cached = provider.get_forecast(make_conditions_request())

    assert fresh.samples[0].timestamp_local.isoformat() == "2026-01-10T20:00:00+08:00"
    assert fresh.samples[0].cloud_cover_percent == 24
    assert fresh.samples[0].precipitation_mm == 0.0
    assert fresh.samples[0].wind_speed_kmh == 7.2
    assert fresh.samples[0].visibility_m == 12000
    assert fresh.source.provider == "Open-Meteo"
    assert fresh.source.source_url == backend.calls[0]["url"]
    assert fresh.source.accessed_at == fixed_clock()
    assert fresh.source.from_cache is False
    assert fresh.source.availability == "fresh"
    assert cached.source.source_url == fresh.source.source_url
    assert cached.source.accessed_at == fixed_clock()
    assert cached.source.from_cache is True
    assert cached.source.availability == "cached"
    assert len(backend.calls) == 1

    query = parse_qs(urlparse(backend.calls[0]["url"]).query)
    assert query == {
        "latitude": ["39.9042"],
        "longitude": ["116.4074"],
        "timezone": ["Asia/Shanghai"],
        "start_date": ["2026-01-10"],
        "end_date": ["2026-01-11"],
        "hourly": ["cloud_cover,precipitation,wind_speed_10m,visibility"],
    }


def test_weather_provider_maps_missing_hourly_values_to_none(tmp_path: Path) -> None:
    from starskill.weather import OpenMeteoWeatherProvider

    provider = OpenMeteoWeatherProvider(
        backend=StaticJsonBackend(
            {
                "hourly": {
                    "time": ["2026-01-10T20:00"],
                    "cloud_cover": [None],
                    "precipitation": [None],
                    "wind_speed_10m": [None],
                    "visibility": [None],
                }
            }
        ),
        cache_dir=tmp_path,
        clock=fixed_clock,
    )

    sample = provider.get_forecast(make_conditions_request()).samples[0]

    assert sample.cloud_cover_percent is None
    assert sample.precipitation_mm is None
    assert sample.wind_speed_kmh is None
    assert sample.visibility_m is None


def test_weather_provider_only_attaches_observer_timezone_to_naive_timestamps(
    tmp_path: Path,
) -> None:
    from starskill.weather import OpenMeteoWeatherProvider

    provider = OpenMeteoWeatherProvider(
        backend=StaticJsonBackend(
            {
                "hourly": {
                    "time": ["2026-01-10T12:00:00+00:00"],
                    "cloud_cover": [24],
                    "precipitation": [0.0],
                    "wind_speed_10m": [7.2],
                    "visibility": [12000],
                }
            }
        ),
        cache_dir=tmp_path,
        clock=fixed_clock,
    )

    timestamp = provider.get_forecast(make_conditions_request()).samples[0].timestamp_local

    assert timestamp == datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def test_weather_provider_reports_a_network_failure_as_unavailable(tmp_path: Path) -> None:
    from starskill.weather import OpenMeteoWeatherProvider

    result = OpenMeteoWeatherProvider(
        backend=FailingJsonBackend(), cache_dir=tmp_path, clock=fixed_clock
    ).get_forecast(make_conditions_request())

    assert result.samples == []
    assert result.source.provider == "Open-Meteo"
    assert result.source.source_url is not None
    assert result.source.accessed_at == fixed_clock()
    assert result.source.from_cache is False
    assert result.source.availability == "unavailable"
    assert result.source.issue_code == "external_data_network_error"


def test_weather_provider_reports_mismatched_hourly_arrays_as_unavailable(
    tmp_path: Path,
) -> None:
    from starskill.weather import OpenMeteoWeatherProvider

    result = OpenMeteoWeatherProvider(
        backend=StaticJsonBackend(
            {
                "hourly": {
                    "time": ["2026-01-10T20:00"],
                    "cloud_cover": [24, 25],
                    "precipitation": [0.0],
                    "wind_speed_10m": [7.2],
                    "visibility": [12000],
                }
            }
        ),
        cache_dir=tmp_path,
        clock=fixed_clock,
    ).get_forecast(make_conditions_request())

    assert result.samples == []
    assert result.source.availability == "unavailable"
    assert result.source.issue_code == ExternalDataFormatError.code


def test_weather_provider_refreshes_an_expired_cache(tmp_path: Path) -> None:
    from starskill.weather import OpenMeteoWeatherProvider

    first_clock = lambda: datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    second_clock = lambda: first_clock() + timedelta(minutes=30)
    backend = StaticJsonBackend(
        {
            "hourly": {
                "time": ["2026-01-10T20:00"],
                "cloud_cover": [24],
                "precipitation": [0.0],
                "wind_speed_10m": [7.2],
                "visibility": [12000],
            }
        }
    )
    OpenMeteoWeatherProvider(
        backend=backend, cache_dir=tmp_path, clock=first_clock
    ).get_forecast(make_conditions_request())
    refreshed = OpenMeteoWeatherProvider(
        backend=backend, cache_dir=tmp_path, clock=second_clock
    ).get_forecast(make_conditions_request())

    assert refreshed.source.availability == "fresh"
    assert refreshed.source.from_cache is False
    assert len(backend.calls) == 2
