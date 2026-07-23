"""NASA Astronomy Picture of the Day provider with credential-safe caching."""

from collections.abc import Callable
from datetime import date as calendar_date
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .external_data import (
    ExternalDataError,
    ExternalDataFormatError,
    ExternalDataNetworkError,
    JsonBackend,
    UrlJsonBackend,
    read_cache_record,
    write_cache_record,
)
from .schemas import ExternalSource, NasaFeature


NASA_APOD_ENDPOINT = "https://api.nasa.gov/planetary/apod"
NASA_APOD_CACHE_TTL = timedelta(hours=24)
NASA_APOD_TIMEOUT_SECONDS = 10
NASA_APOD_MAX_BYTES = 1_000_000


class NasaApodProvider:
    """Fetch NASA APOD data while keeping the caller-provided key out of outputs."""

    def __init__(
        self,
        *,
        api_key: str | None,
        cache_dir: Path,
        backend: JsonBackend | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._api_key = api_key
        self._cache_dir = cache_dir
        self._backend = backend or UrlJsonBackend()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_feature(self, date: str | None) -> NasaFeature:
        now = self._clock()
        try:
            source_url = self._source_url(date)
        except ValueError:
            return self._unavailable(NASA_APOD_ENDPOINT, now, False, "nasa_apod_date_invalid")
        if not self._api_key:
            return self._unavailable(source_url, now, False, "nasa_api_key_missing")

        cache_path = self._cache_dir / f"{sha256(source_url.encode('utf-8')).hexdigest()}.json"
        payload = read_cache_record(cache_path, now, NASA_APOD_CACHE_TTL)
        if payload is not None:
            try:
                return self._feature(payload, source_url, now, from_cache=True, availability="cached")
            except ExternalDataError as error:
                return self._unavailable(source_url, now, True, error.code)

        request_url = f"{NASA_APOD_ENDPOINT}?{urlencode({'api_key': self._api_key, **({'date': date} if date else {})})}"
        try:
            payload = self._backend.fetch_json(
                request_url,
                timeout_seconds=NASA_APOD_TIMEOUT_SECONDS,
                max_bytes=NASA_APOD_MAX_BYTES,
            )
            feature = self._feature(payload, source_url, now, from_cache=False, availability="fresh")
        except OSError:
            return self._unavailable(
                source_url,
                now,
                False,
                ExternalDataNetworkError.code,
            )
        except ExternalDataError as error:
            return self._unavailable(source_url, now, False, error.code)

        try:
            write_cache_record(cache_path, payload, now)
        except OSError:
            pass
        return feature

    @staticmethod
    def _source_url(requested_date: str | None) -> str:
        if requested_date is None:
            return NASA_APOD_ENDPOINT
        parsed_date = calendar_date.fromisoformat(requested_date)
        if parsed_date.isoformat() != requested_date:
            raise ValueError("invalid APOD date")
        return f"{NASA_APOD_ENDPOINT}?{urlencode({'date': requested_date})}"

    @staticmethod
    def _feature(
        payload: dict[str, Any],
        source_url: str,
        accessed_at: datetime,
        *,
        from_cache: bool,
        availability: str,
    ) -> NasaFeature:
        try:
            required = ("date", "title", "media_type", "url")
            if not isinstance(payload, dict) or not all(
                isinstance(payload[key], str) and payload[key] for key in required
            ):
                raise TypeError
            for optional_key in ("explanation", "copyright"):
                if optional_key in payload and payload[optional_key] is not None and not isinstance(payload[optional_key], str):
                    raise TypeError
        except (KeyError, TypeError) as exc:
            raise ExternalDataFormatError("invalid NASA APOD response") from exc
        return NasaFeature(
            date=payload["date"],
            title=payload["title"],
            media_type=payload["media_type"],
            media_url=payload["url"],
            explanation=payload.get("explanation"),
            copyright=payload.get("copyright"),
            source=ExternalSource(
                provider="NASA APOD",
                source_url=source_url,
                accessed_at=accessed_at,
                from_cache=from_cache,
                availability=availability,
            ),
        )

    @staticmethod
    def _unavailable(
        source_url: str,
        accessed_at: datetime,
        from_cache: bool,
        issue_code: str,
    ) -> NasaFeature:
        return NasaFeature(
            source=ExternalSource(
                provider="NASA APOD",
                source_url=source_url,
                accessed_at=accessed_at,
                from_cache=from_cache,
                availability="unavailable",
                issue_code=issue_code,
            )
        )
