"""Static NASA Black Marble snapshot lookups for observing context."""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import ExternalSource, LightPollutionResult, Observer


BLACK_MARBLE_PROVIDER = "NASA Black Marble"
BLACK_MARBLE_SOURCE_URL = "https://blackmarble.gsfc.nasa.gov/"
SNAPSHOT_MAX_BYTES = 5_000_000
_SNAPSHOT_FIELDS = {
    "dataset_id",
    "dataset_version",
    "sample_period",
    "spatial_resolution",
    "unit",
    "source_url",
    "cells",
}


class BlackMarbleLightPollutionProvider:
    """Read a versioned local Black Marble snapshot without live data claims."""

    def __init__(
        self,
        *,
        snapshot_path: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._snapshot_path = snapshot_path
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def lookup(self, observer: Observer) -> LightPollutionResult:
        accessed_at = self._clock()
        try:
            snapshot = self._read_snapshot()
        except FileNotFoundError:
            return self._unavailable(accessed_at, "light_pollution_snapshot_unavailable")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            return self._unavailable(accessed_at, "light_pollution_snapshot_invalid")

        try:
            cell = min(
                snapshot["cells"],
                key=lambda item: (item["latitude"] - observer.latitude) ** 2
                + (item["longitude"] - observer.longitude) ** 2,
            )
        except (KeyError, TypeError, ValueError):
            return self._unavailable(
                accessed_at,
                "light_pollution_snapshot_invalid",
                snapshot.get("source_url", BLACK_MARBLE_SOURCE_URL),
            )

        return LightPollutionResult(
            radiance=cell["radiance"],
            unit=snapshot["unit"],
            dataset_id=snapshot["dataset_id"],
            dataset_version=snapshot["dataset_version"],
            sample_period=snapshot["sample_period"],
            spatial_resolution=snapshot["spatial_resolution"],
            interpolation="nearest_snapshot_cell",
            source=self._source(
                snapshot["source_url"], accessed_at, availability="fresh"
            ),
        )

    def _read_snapshot(self) -> dict[str, Any]:
        if self._snapshot_path.stat().st_size > SNAPSHOT_MAX_BYTES:
            raise ValueError("light pollution snapshot exceeds byte limit")
        snapshot = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or set(snapshot) != _SNAPSHOT_FIELDS:
            raise ValueError("invalid light pollution snapshot fields")
        if not all(isinstance(snapshot[field], str) and snapshot[field] for field in _SNAPSHOT_FIELDS - {"cells"}):
            raise ValueError("invalid light pollution snapshot metadata")
        cells = snapshot["cells"]
        if not isinstance(cells, list) or not cells:
            raise ValueError("light pollution snapshot cells are empty")
        for cell in cells:
            if not isinstance(cell, dict):
                raise ValueError("invalid light pollution cell")
            longitude = cell.get("longitude")
            latitude = cell.get("latitude")
            radiance = cell.get("radiance")
            if (
                isinstance(longitude, bool)
                or not isinstance(longitude, (int, float))
                or not -180 <= longitude <= 180
                or isinstance(latitude, bool)
                or not isinstance(latitude, (int, float))
                or not -90 <= latitude <= 90
                or isinstance(radiance, bool)
                or not isinstance(radiance, (int, float))
                or radiance < 0
            ):
                raise ValueError("invalid light pollution cell value")
        return snapshot

    @staticmethod
    def _source(
        source_url: str | None,
        accessed_at: datetime,
        *,
        availability: str,
        issue_code: str | None = None,
    ) -> ExternalSource:
        return ExternalSource(
            provider=BLACK_MARBLE_PROVIDER,
            source_url=source_url,
            accessed_at=accessed_at,
            from_cache=False,
            availability=availability,
            issue_code=issue_code,
        )

    def _unavailable(
        self,
        accessed_at: datetime,
        issue_code: str,
        source_url: str = BLACK_MARBLE_SOURCE_URL,
    ) -> LightPollutionResult:
        return LightPollutionResult(
            source=self._source(
                source_url,
                accessed_at,
                availability="unavailable",
                issue_code=issue_code,
            )
        )
