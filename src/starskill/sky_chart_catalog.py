"""Offline, integrity-checked catalog data for the local sky chart."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
import json
import re
from typing import Any, Literal


_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_DATASET_ID = "bundled-bright-stars"


@dataclass(frozen=True)
class CatalogStar:
    star_id: str
    name: str
    ra_deg: float
    dec_deg: float
    magnitude: float


@dataclass(frozen=True)
class ConstellationSegment:
    constellation: str
    start_star_id: str
    end_star_id: str


@dataclass(frozen=True)
class CatalogMetadata:
    dataset_id: str
    version: str
    source_url: str
    license: str
    sha256: str


@dataclass(frozen=True)
class BundledCatalog:
    stars: tuple[CatalogStar, ...]
    segments: tuple[ConstellationSegment, ...]
    metadata: CatalogMetadata


@dataclass(frozen=True)
class HygSource:
    url: str
    asset_name: str
    version: Literal["4.1"]
    license: str
    compressed_sha256: str


def load_bundled_catalog() -> BundledCatalog:
    """Load only the JSON catalogs packaged with this distribution."""
    source = load_hyg_source()
    stars_envelope = _load_envelope("bright_stars.json")
    segments_envelope = _load_envelope("constellation_segments.json")
    metadata = _metadata_from(stars_envelope)
    segments_metadata = _metadata_from(segments_envelope)
    _validate_shared_provenance(metadata, segments_metadata, source)

    stars = tuple(_star_from(record) for record in stars_envelope["records"])
    star_ids = {star.star_id for star in stars}
    if len(star_ids) != len(stars):
        raise ValueError("bundled bright-star catalog contains duplicate star IDs")

    segments = tuple(_segment_from(record) for record in segments_envelope["records"])
    if any(
        segment.start_star_id not in star_ids or segment.end_star_id not in star_ids
        for segment in segments
    ):
        raise ValueError("constellation segment references a star absent from the catalog")

    return BundledCatalog(stars=stars, segments=segments, metadata=metadata)


def load_hyg_source() -> HygSource:
    """Load fixed HYG v4.1 provenance, never a downloader configuration."""
    data = _read_json("hyg_v4_1_source.json")
    if not isinstance(data, dict):
        raise ValueError("HYG source metadata must be an object")

    url = _require_string(data, "url")
    asset_name = _require_string(data, "asset_name")
    version = _require_string(data, "version")
    license_name = _require_string(data, "license")
    compressed_sha256 = _require_string(data, "compressed_sha256")
    if not url.startswith("https://"):
        raise ValueError("HYG source URL must use HTTPS")
    if version != "4.1":
        raise ValueError("only HYG v4.1 source metadata is supported")
    if not _DIGEST_RE.fullmatch(compressed_sha256):
        raise ValueError("HYG compressed SHA-256 must be lowercase hexadecimal")

    return HygSource(
        url=url,
        asset_name=asset_name,
        version="4.1",
        license=license_name,
        compressed_sha256=compressed_sha256,
    )


def _load_envelope(name: str) -> dict[str, Any]:
    data = _read_json(name)
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be a JSON object")
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError(f"{name} records must be a JSON array")
    metadata = _metadata_from(data)
    if metadata.dataset_id != _DATASET_ID:
        raise ValueError(f"{name} has an unexpected dataset ID")
    actual_digest = sha256(
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if actual_digest != metadata.sha256:
        raise ValueError(f"{name} records SHA-256 does not match metadata")
    return data


def _read_json(name: str) -> Any:
    return json.loads(files("starskill").joinpath("data", name).read_text(encoding="utf-8"))


def _metadata_from(data: dict[str, Any]) -> CatalogMetadata:
    return CatalogMetadata(
        dataset_id=_require_string(data, "dataset_id"),
        version=_require_string(data, "version"),
        source_url=_require_string(data, "source_url"),
        license=_require_string(data, "license"),
        sha256=_require_string(data, "sha256"),
    )


def _validate_shared_provenance(
    metadata: CatalogMetadata, segments_metadata: CatalogMetadata, source: HygSource
) -> None:
    if not metadata.source_url.startswith("https://"):
        raise ValueError("catalog source URL must use HTTPS")
    if not _DIGEST_RE.fullmatch(metadata.sha256):
        raise ValueError("catalog SHA-256 must be lowercase hexadecimal")
    if (
        metadata.source_url != source.url
        or metadata.license != source.license
        or segments_metadata.source_url != source.url
        or segments_metadata.license != source.license
    ):
        raise ValueError("catalog provenance does not match fixed HYG source metadata")


def _star_from(record: Any) -> CatalogStar:
    if not isinstance(record, dict):
        raise ValueError("bright-star record must be an object")
    star = CatalogStar(
        star_id=_require_string(record, "star_id"),
        name=_require_string(record, "name"),
        ra_deg=_require_number(record, "ra_deg"),
        dec_deg=_require_number(record, "dec_deg"),
        magnitude=_require_number(record, "magnitude"),
    )
    if not 0 <= star.ra_deg < 360 or not -90 <= star.dec_deg <= 90:
        raise ValueError(f"star {star.star_id} has invalid equatorial coordinates")
    return star


def _segment_from(record: Any) -> ConstellationSegment:
    if not isinstance(record, dict):
        raise ValueError("constellation segment record must be an object")
    return ConstellationSegment(
        constellation=_require_string(record, "constellation"),
        start_star_id=_require_string(record, "start_star_id"),
        end_star_id=_require_string(record, "end_star_id"),
    )


def _require_string(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value


def _require_number(data: dict[str, Any], field: str) -> float:
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be numeric")
    return float(value)
