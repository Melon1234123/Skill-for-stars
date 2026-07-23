"""Offline, integrity-checked catalog data for the local sky chart."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from importlib.resources import files
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Literal, Mapping, Protocol


_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_DATASET_ID = "bundled-bright-stars"
_HYG_CACHE_DIRECTORY = "hyg-v4.1"
_HYG_CATALOG_FILENAME = "catalog.csv"
_HYG_MANIFEST_FILENAME = "manifest.json"
_HYG_ARCHIVE_FILENAME = "hygdata_v41.csv.gz"
MAX_HYG_DOWNLOAD_BYTES = 128 * 1024 * 1024
MIN_HYG_ROWS = 100_001
REQUIRED_HYG_COLUMNS = frozenset({"ra", "dec", "mag", "proper"})
MAX_HYG_CSV_BYTES = 256 * 1024 * 1024
CatalogMode = Literal["auto", "bundled", "full"]


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


@dataclass(frozen=True)
class FullCatalog:
    """Verified HYG records prepared for deterministic renderer selection."""

    stars: tuple[CatalogStar, ...]
    metadata: CatalogMetadata
    row_count: int


@dataclass(frozen=True)
class CatalogSelection:
    mode_used: Literal["bundled", "full"]
    status: Literal["available", "degraded"]
    catalog: BundledCatalog | FullCatalog
    constellation_segments: tuple[ConstellationSegment, ...] = ()
    constellation_stars: tuple[CatalogStar, ...] = ()


@dataclass(frozen=True)
class CatalogDownloadSummary:
    version: str
    row_count: int
    compressed_sha256: str
    csv_sha256: str
    status: Literal["available"] = "available"


class CatalogDownloadError(RuntimeError):
    """Raised when a fixed catalog download is unsafe or unverifiable."""


class FullCatalogUnavailableError(RuntimeError):
    """Raised when a caller explicitly requires a missing full catalog."""


class CatalogFetcher(Protocol):
    def stream(self, url: str, *, max_bytes: int) -> tuple[int, Mapping[str, str], Iterable[bytes]]:
        """Return a response status, response headers, and exact body chunks."""


class FullCatalogCache:
    """Manage the only permitted on-disk cache for the fixed HYG v4.1 asset."""

    def __init__(self, cache_dir: Path, source: HygSource) -> None:
        self.source = source
        self.cache_root = (Path(cache_dir) / _HYG_CACHE_DIRECTORY).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.cache_root / _HYG_CATALOG_FILENAME
        self.manifest_path = self.cache_root / _HYG_MANIFEST_FILENAME

    def load_valid(self) -> FullCatalog | None:
        """Return a full catalog only when every published artifact validates."""
        try:
            if not self.catalog_path.is_file() or not self.manifest_path.is_file():
                return None
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if not _valid_manifest(manifest, self.source):
                return None
            csv_bytes = self.catalog_path.read_bytes()
            if sha256(csv_bytes).hexdigest() != manifest["csv_sha256"]:
                return None
            stars, row_count = _parse_hyg_csv(csv_bytes)
            if row_count != manifest["row_count"]:
                return None
            return FullCatalog(
                stars=stars,
                row_count=row_count,
                metadata=CatalogMetadata(
                    dataset_id="hyg-v4.1",
                    version=self.source.version,
                    source_url=self.source.url,
                    license=self.source.license,
                    sha256=manifest["csv_sha256"],
                ),
            )
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            csv.Error,
        ):
            return None

    def download_and_publish(self, fetch: CatalogFetcher) -> CatalogDownloadSummary:
        """Download one fixed gzip asset and atomically publish verified CSV data."""
        _validate_hyg_asset(self.source)
        compressed_temp: Path | None = None
        csv_temp: Path | None = None
        manifest_temp: Path | None = None
        catalog_backup: Path | None = None
        manifest_backup: Path | None = None
        catalog_published = False
        try:
            status, headers, chunks = fetch.stream(
                self.source.url, max_bytes=MAX_HYG_DOWNLOAD_BYTES
            )
            if status != 200:
                raise CatalogDownloadError(f"catalog download returned status {status}")

            compressed_temp = _named_temp(self.cache_root, "download-")
            compressed_digest = sha256()
            total = 0
            with compressed_temp.open("wb") as output:
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise CatalogDownloadError(
                            "catalog download returned a non-bytes stream chunk"
                        )
                    total += len(chunk)
                    if total > MAX_HYG_DOWNLOAD_BYTES:
                        raise CatalogDownloadError("catalog download exceeds the maximum size")
                    compressed_digest.update(chunk)
                    output.write(chunk)
            compressed_sha256 = compressed_digest.hexdigest()
            if compressed_sha256 != self.source.compressed_sha256:
                raise CatalogDownloadError(
                    "catalog download SHA-256 does not match fixed source metadata"
                )

            csv_temp = _named_temp(self.cache_root, "catalog-")
            _extract_fixed_gzip(compressed_temp, csv_temp)
            csv_bytes = csv_temp.read_bytes()
            _, row_count = _parse_hyg_csv(csv_bytes)
            csv_sha256 = sha256(csv_bytes).hexdigest()

            manifest = canonical_manifest(
                source=self.source,
                compressed_sha256=compressed_sha256,
                csv_sha256=csv_sha256,
                row_count=row_count,
                headers=headers,
            )
            manifest_temp = _named_temp(self.cache_root, "manifest-")
            manifest_temp.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )

            catalog_backup = _copy_published_file(
                self.catalog_path, self.cache_root, "prior-catalog-"
            )
            manifest_backup = _copy_published_file(
                self.manifest_path, self.cache_root, "prior-manifest-"
            )
            os.replace(csv_temp, self.catalog_path)
            csv_temp = None
            catalog_published = True
            os.replace(manifest_temp, self.manifest_path)
            manifest_temp = None
            return CatalogDownloadSummary(
                version=self.source.version,
                row_count=row_count,
                compressed_sha256=compressed_sha256,
                csv_sha256=csv_sha256,
            )
        except CatalogDownloadError:
            if catalog_published:
                _restore_published_file(self.catalog_path, catalog_backup, self.cache_root)
                _restore_published_file(self.manifest_path, manifest_backup, self.cache_root)
            raise
        except ValueError as error:
            if catalog_published:
                _restore_published_file(self.catalog_path, catalog_backup, self.cache_root)
                _restore_published_file(self.manifest_path, manifest_backup, self.cache_root)
            raise CatalogDownloadError(str(error)) from error
        except Exception as error:
            if catalog_published:
                _restore_published_file(self.catalog_path, catalog_backup, self.cache_root)
                _restore_published_file(self.manifest_path, manifest_backup, self.cache_root)
            raise CatalogDownloadError("catalog download could not be validated") from error
        finally:
            for temporary_path in (
                compressed_temp,
                csv_temp,
                manifest_temp,
                catalog_backup,
                manifest_backup,
            ):
                if temporary_path is not None:
                    _unlink_temp(temporary_path)

def canonical_manifest(
    *,
    source: HygSource,
    compressed_sha256: str,
    csv_sha256: str,
    row_count: int,
    headers: Mapping[str, str],
) -> dict[str, object]:
    """Build the public, source-bound manifest representation."""
    manifest: dict[str, object] = {
        "accessed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "asset_name": source.asset_name,
        "compressed_sha256": compressed_sha256,
        "csv_sha256": csv_sha256,
        "row_count": row_count,
        "source_license": source.license,
        "source_url": source.url,
        "source_version": source.version,
    }
    etag = _header_value(headers, "ETag")
    last_modified = _header_value(headers, "Last-Modified")
    if etag is not None:
        manifest["response_etag"] = etag
    if last_modified is not None:
        manifest["response_last_modified"] = last_modified
    return manifest


def select_catalog(
    mode: CatalogMode, bundled: BundledCatalog, full_cache: FullCatalogCache
) -> CatalogSelection:
    """Choose a local catalog without attempting any network access."""
    if mode == "bundled":
        return CatalogSelection(
            mode_used="bundled",
            status="available",
            catalog=bundled,
            constellation_segments=bundled.segments,
            constellation_stars=bundled.stars,
        )

    full = full_cache.load_valid()
    if full is not None:
        return CatalogSelection(
            mode_used="full",
            status="available",
            catalog=full,
            constellation_segments=bundled.segments,
            constellation_stars=bundled.stars,
        )
    if mode == "auto":
        return CatalogSelection(
            mode_used="bundled",
            status="degraded",
            catalog=bundled,
            constellation_segments=bundled.segments,
            constellation_stars=bundled.stars,
        )
    if mode == "full":
        raise FullCatalogUnavailableError(
            "full catalog is unavailable; run starskill sky-chart --download-catalog"
        )
    raise ValueError("catalog mode must be auto, bundled, or full")


def _named_temp(cache_root: Path, prefix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=cache_root, prefix=prefix, suffix=".tmp", delete=False
    ) as temporary_file:
        return Path(temporary_file.name)


def _unlink_temp(path: Path) -> None:
    if path.suffix == ".tmp":
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _copy_published_file(path: Path, cache_root: Path, prefix: str) -> Path | None:
    if not path.is_file():
        return None
    backup = _named_temp(cache_root, prefix)
    shutil.copyfile(path, backup)
    return backup


def _restore_published_file(target: Path, backup: Path | None, cache_root: Path) -> None:
    if backup is not None and backup.exists():
        os.replace(backup, target)
        return
    if target.exists():
        rollback = _named_temp(cache_root, "rollback-")
        os.replace(target, rollback)
        _unlink_temp(rollback)


def _validate_hyg_asset(source: HygSource) -> None:
    if (
        source.version != "4.1"
        or source.asset_name != _HYG_ARCHIVE_FILENAME
        or not source.url.startswith("https://")
        or not _DIGEST_RE.fullmatch(source.compressed_sha256)
        or not source.license.strip()
    ):
        raise CatalogDownloadError("fixed HYG source metadata is invalid")


def _extract_fixed_gzip(compressed_path: Path, csv_path: Path) -> None:
    total = 0
    with gzip.open(compressed_path, "rb") as source_file, csv_path.open("wb") as output:
        while chunk := source_file.read(64 * 1024):
            total += len(chunk)
            if total > MAX_HYG_CSV_BYTES:
                raise CatalogDownloadError("catalog CSV exceeds the maximum size")
            output.write(chunk)


def _parse_hyg_csv(csv_bytes: bytes) -> tuple[tuple[CatalogStar, ...], int]:
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"), newline=""))
    headers = reader.fieldnames
    if not headers or any(not isinstance(header, str) or not header for header in headers):
        raise ValueError("catalog CSV has invalid headers")
    if not REQUIRED_HYG_COLUMNS.issubset(headers):
        raise ValueError("catalog CSV is missing required headers")

    stars: list[CatalogStar] = []
    row_count = 0
    for row in reader:
        row_count += 1
        star = _full_star_from_row(row, row_count)
        if star is not None:
            stars.append(star)
    if row_count < MIN_HYG_ROWS:
        raise ValueError("catalog CSV must contain at least 100001 rows")
    return tuple(stars), row_count


def _full_star_from_row(
    row: Mapping[str | None, str | None], row_number: int
) -> CatalogStar | None:
    try:
        ra_hours = float(row["ra"] or "")
        dec_deg = float(row["dec"] or "")
        magnitude = float(row["mag"] or "")
    except (KeyError, TypeError, ValueError):
        return None
    ra_deg = (ra_hours * 15.0) % 360.0
    coordinates_are_finite = all(math.isfinite(value) for value in (ra_deg, dec_deg, magnitude))
    if not coordinates_are_finite or not -90 <= dec_deg <= 90:
        return None
    raw_id = (row.get("id") or "").strip()
    star_id = f"hyg-{raw_id}" if raw_id else f"hyg-row-{row_number}"
    name = (row.get("proper") or "").strip() or (row.get("bf") or "").strip() or star_id
    return CatalogStar(
        star_id=star_id,
        name=name,
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        magnitude=magnitude,
    )


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if (
            isinstance(key, str)
            and key.lower() == name.lower()
            and isinstance(value, str)
            and value
        ):
            return value
    return None


def _valid_manifest(manifest: object, source: HygSource) -> bool:
    if not isinstance(manifest, dict):
        return False
    required_keys = {
        "accessed_at_utc",
        "asset_name",
        "compressed_sha256",
        "csv_sha256",
        "row_count",
        "source_license",
        "source_url",
        "source_version",
    }
    optional_keys = {"response_etag", "response_last_modified"}
    if not required_keys.issubset(manifest) or not set(manifest).issubset(
        required_keys | optional_keys
    ):
        return False
    if (
        manifest["asset_name"] != source.asset_name
        or manifest["compressed_sha256"] != source.compressed_sha256
        or manifest["source_license"] != source.license
        or manifest["source_url"] != source.url
        or manifest["source_version"] != source.version
    ):
        return False
    if not isinstance(manifest["csv_sha256"], str) or not _DIGEST_RE.fullmatch(
        manifest["csv_sha256"]
    ):
        return False
    if isinstance(manifest["row_count"], bool) or not isinstance(manifest["row_count"], int):
        return False
    if manifest["row_count"] < MIN_HYG_ROWS:
        return False
    if not _valid_utc_timestamp(manifest["accessed_at_utc"]):
        return False
    return all(
        key not in manifest or isinstance(manifest[key], str) and bool(manifest[key])
        for key in optional_keys
    )


def _valid_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").tzinfo == timezone.utc
    except ValueError:
        return False


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
    if asset_name != _HYG_ARCHIVE_FILENAME:
        raise ValueError("only the fixed HYG v4.1 gzip asset is supported")
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
