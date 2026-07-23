"""Auditable Open-Meteo weather forecast provider."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .external_data import (
    ExternalDataError,
    ExternalDataFormatError,
    JsonBackend,
    UrlJsonBackend,
    read_cache_record,
    write_cache_record,
)
from .schemas import (
    ExternalSource,
    ObservingConditionsRequest,
    WeatherForecast,
    WeatherSample,
)


OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
WEATHER_CACHE_TTL = timedelta(minutes=30)
WEATHER_TIMEOUT_SECONDS = 10
WEATHER_MAX_BYTES = 1_000_000
HOURLY_FIELDS = "cloud_cover,precipitation,wind_speed_10m,visibility"


class OpenMeteoWeatherProvider:
    """Fetch short-lived hourly forecasts without treating them as safety evidence."""

    def __init__(
        self,
        *,
        backend: JsonBackend | None = None,
        cache_dir: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._backend = backend or UrlJsonBackend()
        self._cache_dir = cache_dir
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_forecast(self, request: ObservingConditionsRequest) -> WeatherForecast:
        now = self._clock()
        source_url = self._build_url(request)
        cache_path = self._cache_dir / f"{sha256(source_url.encode('utf-8')).hexdigest()}.json"
        payload = read_cache_record(cache_path, now, WEATHER_CACHE_TTL)

        if payload is not None:
            try:
                samples = self._map_samples(payload, request.observer.timezone)
            except ExternalDataError as error:
                return self._unavailable(source_url, now, True, error.code)
            return WeatherForecast(
                samples=samples,
                source=self._source(source_url, now, from_cache=True, availability="cached"),
            )

        try:
            payload = self._backend.fetch_json(
                source_url,
                timeout_seconds=WEATHER_TIMEOUT_SECONDS,
                max_bytes=WEATHER_MAX_BYTES,
            )
            samples = self._map_samples(payload, request.observer.timezone)
        except ExternalDataError as error:
            return self._unavailable(source_url, now, False, error.code)

        write_cache_record(cache_path, payload, now)
        return WeatherForecast(
            samples=samples,
            source=self._source(source_url, now, from_cache=False, availability="fresh"),
        )

    @staticmethod
    def _build_url(request: ObservingConditionsRequest) -> str:
        timezone_name = request.observer.timezone
        observer_timezone = ZoneInfo(timezone_name)
        start = request.time_range.start
        end = request.time_range.end
        if start.tzinfo is not None and start.utcoffset() is not None:
            start = start.astimezone(observer_timezone)
        if end.tzinfo is not None and end.utcoffset() is not None:
            end = end.astimezone(observer_timezone)
        query = urlencode(
            {
                "latitude": request.observer.latitude,
                "longitude": request.observer.longitude,
                "timezone": timezone_name,
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
                "hourly": HOURLY_FIELDS,
            }
        )
        return f"{OPEN_METEO_ENDPOINT}?{query}"

    @staticmethod
    def _map_samples(payload: dict[str, Any], timezone_name: str) -> list[WeatherSample]:
        try:
            hourly = payload["hourly"]
            if not isinstance(hourly, dict):
                raise TypeError
            fields = [
                hourly["time"],
                hourly["cloud_cover"],
                hourly["precipitation"],
                hourly["wind_speed_10m"],
                hourly["visibility"],
            ]
            if not all(isinstance(values, list) for values in fields):
                raise TypeError
            if len({len(values) for values in fields}) != 1:
                raise ValueError
            observer_timezone = ZoneInfo(timezone_name)
            samples = []
            for timestamp, cloud_cover, precipitation, wind_speed, visibility in zip(
                *fields, strict=True
            ):
                parsed_timestamp = datetime.fromisoformat(timestamp)
                if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
                    parsed_timestamp = parsed_timestamp.replace(tzinfo=observer_timezone)
                samples.append(
                    WeatherSample(
                        timestamp_local=parsed_timestamp,
                        cloud_cover_percent=cloud_cover,
                        precipitation_mm=precipitation,
                        wind_speed_kmh=wind_speed,
                        visibility_m=visibility,
                    )
                )
            return samples
        except (KeyError, TypeError, ValidationError, ValueError) as exc:
            raise ExternalDataFormatError("invalid Open-Meteo hourly forecast response") from exc

    @staticmethod
    def _source(
        source_url: str,
        accessed_at: datetime,
        *,
        from_cache: bool,
        availability: str,
        issue_code: str | None = None,
    ) -> ExternalSource:
        return ExternalSource(
            provider="Open-Meteo",
            source_url=source_url,
            accessed_at=accessed_at,
            from_cache=from_cache,
            availability=availability,
            issue_code=issue_code,
        )

    def _unavailable(
        self,
        source_url: str,
        accessed_at: datetime,
        from_cache: bool,
        issue_code: str,
    ) -> WeatherForecast:
        return WeatherForecast(
            samples=[],
            source=self._source(
                source_url,
                accessed_at,
                from_cache=from_cache,
                availability="unavailable",
                issue_code=issue_code,
            ),
        )
