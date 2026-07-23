import copy
import gzip
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
from typing import Iterable, Mapping
import zlib

import pytest

import starskill.sky_chart_catalog as catalog_module
from starskill.sky_chart_catalog import (
    CatalogDownloadError,
    FullCatalogCache,
    FullCatalogUnavailableError,
    HygSource,
    load_bundled_catalog,
    load_hyg_source,
    select_catalog,
)


class FakeFetcher:
    def __init__(
        self,
        *,
        status: int = 200,
        chunks: Iterable[bytes] = (),
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self.chunks = chunks
        self.headers = headers if headers is not None else {}
        self.urls: list[str] = []

    def stream(self, url: str, *, max_bytes: int) -> tuple[int, Mapping[str, str], Iterable[bytes]]:
        self.urls.append(url)
        return self.status, self.headers, self.chunks


class RaisingFetcher:
    def stream(self, url: str, *, max_bytes: int) -> tuple[int, Mapping[str, str], Iterable[bytes]]:
        raise RuntimeError("fixture fetcher failure")


@pytest.fixture
def hyg_csv_bytes() -> bytes:
    return Path("tests/fixtures/sky_chart/hyg-valid.csv").read_bytes()


def test_bundled_catalog_is_available_from_installed_package_data() -> None:
    catalog = load_bundled_catalog()

    assert len(catalog.stars) >= 100
    assert catalog.metadata.dataset_id == "bundled-bright-stars"
    assert len(catalog.metadata.sha256) == 64
    assert len(catalog.segment_metadata.sha256) == 64
    assert catalog.segment_metadata.sha256 != catalog.metadata.sha256
    assert all(-90 <= star.dec_deg <= 90 and 0 <= star.ra_deg < 360 for star in catalog.stars)
    assert files("starskill").joinpath("data/bright_stars.json").is_file()


def test_constellation_segments_reference_known_bundled_stars() -> None:
    catalog = load_bundled_catalog()
    ids = {star.star_id for star in catalog.stars}

    assert catalog.segments
    assert all(
        segment.start_star_id in ids and segment.end_star_id in ids
        for segment in catalog.segments
    )


def test_hyg_source_has_verified_fixed_metadata() -> None:
    source = load_hyg_source()

    assert source.version == "4.1"
    assert source.url.startswith("https://")
    assert len(source.compressed_sha256) == 64
    assert source.license


def test_bundled_catalog_rejects_canonical_hash_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _catalog_resources()
    resources["bright_stars.json"]["records"][0]["name"] = "tampered"
    _replace_catalog_resources(monkeypatch, resources)

    with pytest.raises(ValueError, match="records SHA-256"):
        load_bundled_catalog()


def test_bundled_catalog_rejects_duplicate_star_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _catalog_resources()
    records = resources["bright_stars.json"]["records"]
    records[1]["star_id"] = records[0]["star_id"]
    _refresh_records_digest(resources["bright_stars.json"])
    _replace_catalog_resources(monkeypatch, resources)

    with pytest.raises(ValueError, match="duplicate star IDs"):
        load_bundled_catalog()


def test_bundled_catalog_rejects_unknown_segment_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _catalog_resources()
    resources["constellation_segments.json"]["records"][0]["end_star_id"] = "hr-unknown"
    _refresh_records_digest(resources["constellation_segments.json"])
    _replace_catalog_resources(monkeypatch, resources)

    with pytest.raises(ValueError, match="references a star absent"):
        load_bundled_catalog()


def test_hyg_source_rejects_malformed_fixed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _catalog_resources()
    resources["hyg_v4_1_source.json"]["compressed_sha256"] = "A" * 64
    _replace_catalog_resources(monkeypatch, resources)

    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        load_hyg_source()


def test_catalog_resource_replacement_does_not_read_existing_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _catalog_resources()

    def unexpected_read_json(name: str) -> object:
        raise AssertionError(f"attempted to read original resource {name}")

    monkeypatch.setattr(catalog_module, "_read_json", unexpected_read_json)
    _replace_catalog_resources(monkeypatch, resources)

    assert len(load_bundled_catalog().stars) == 100


def test_auto_uses_bundled_when_no_full_cache(tmp_path: Path) -> None:
    selection = select_catalog("auto", load_bundled_catalog(), FullCatalogCache(tmp_path, load_hyg_source()))

    assert selection.mode_used == "bundled"
    assert selection.status == "degraded"


def test_bundled_mode_is_available_without_a_full_cache(tmp_path: Path) -> None:
    selection = select_catalog(
        "bundled", load_bundled_catalog(), FullCatalogCache(tmp_path, load_hyg_source())
    )

    assert selection.mode_used == "bundled"
    assert selection.status == "available"


def test_full_rejects_missing_cache_without_network(tmp_path: Path) -> None:
    with pytest.raises(FullCatalogUnavailableError, match="--download-catalog"):
        select_catalog("full", load_bundled_catalog(), FullCatalogCache(tmp_path, load_hyg_source()))


def test_download_publishes_verified_full_catalog(tmp_path: Path, hyg_csv_bytes: bytes) -> None:
    archive = gzip.compress(hyg_csv_bytes)
    source = _test_source(archive)
    fetcher = FakeFetcher(chunks=[archive], headers={"ETag": '"fixture"'})
    cache = FullCatalogCache(tmp_path, source)

    summary = cache.download_and_publish(fetcher)
    catalog = cache.load_valid()

    assert fetcher.urls == [source.url]
    assert summary.row_count == 100_001
    assert catalog is not None
    assert len(catalog.stars) == 100_001
    assert catalog.stars[0].ra_deg == 0.0
    assert catalog.stars[0].name == "Fixture Star 1"
    assert select_catalog("full", load_bundled_catalog(), cache).mode_used == "full"
    assert select_catalog("auto", load_bundled_catalog(), cache).mode_used == "full"


def test_download_rejects_non_200_response(tmp_path: Path) -> None:
    cache = FullCatalogCache(tmp_path, load_hyg_source())

    with pytest.raises(CatalogDownloadError, match="status 404"):
        cache.download_and_publish(FakeFetcher(status=404))

    assert not cache.catalog_path.exists()
    assert not cache.manifest_path.exists()


def test_download_rejects_stream_larger_than_fixed_limit(tmp_path: Path) -> None:
    def chunks() -> Iterable[bytes]:
        for _ in range(2_049):
            yield b"x" * 65_536

    cache = FullCatalogCache(tmp_path, load_hyg_source())

    with pytest.raises(CatalogDownloadError, match="maximum size"):
        cache.download_and_publish(FakeFetcher(chunks=chunks()))

    assert not cache.catalog_path.exists()
    assert not cache.manifest_path.exists()


def test_download_rejects_bad_compressed_source_hash(tmp_path: Path, hyg_csv_bytes: bytes) -> None:
    archive = gzip.compress(hyg_csv_bytes)
    source = HygSource(
        url="https://example.test/hygdata_v41.csv.gz",
        asset_name="hygdata_v41.csv.gz",
        version="4.1",
        license="fixture license",
        compressed_sha256="0" * 64,
    )

    with pytest.raises(CatalogDownloadError, match="SHA-256"):
        FullCatalogCache(tmp_path, source).download_and_publish(FakeFetcher(chunks=[archive]))


def test_download_rejects_bad_csv_headers(tmp_path: Path) -> None:
    archive = gzip.compress(b"id,ra,dec,proper\n1,0,0,No magnitude\n")
    cache = FullCatalogCache(tmp_path, _test_source(archive))

    with pytest.raises(CatalogDownloadError, match="required headers"):
        cache.download_and_publish(FakeFetcher(chunks=[archive]))

    assert not cache.catalog_path.exists()
    assert not cache.manifest_path.exists()


def test_download_rejects_csv_with_fewer_than_minimum_rows(tmp_path: Path) -> None:
    archive = gzip.compress(b"id,ra,dec,mag,proper\n1,0,0,1,Only star\n")
    cache = FullCatalogCache(tmp_path, _test_source(archive))

    with pytest.raises(CatalogDownloadError, match="at least 100001"):
        cache.download_and_publish(FakeFetcher(chunks=[archive]))


def test_load_valid_rejects_tampered_published_csv(tmp_path: Path, hyg_csv_bytes: bytes) -> None:
    cache = _publish_valid_cache(tmp_path, hyg_csv_bytes)
    cache.catalog_path.write_bytes(hyg_csv_bytes + b"# tampered\n")

    assert cache.load_valid() is None


def test_invalid_download_keeps_prior_valid_cache(tmp_path: Path, hyg_csv_bytes: bytes) -> None:
    cache = _publish_valid_cache(tmp_path, hyg_csv_bytes)
    before_catalog = cache.catalog_path.read_bytes()
    before_manifest = cache.manifest_path.read_bytes()

    with pytest.raises(CatalogDownloadError):
        cache.download_and_publish(FakeFetcher(chunks=[b"bad,csv\n"]))

    assert cache.catalog_path.read_bytes() == before_catalog
    assert cache.manifest_path.read_bytes() == before_manifest
    assert cache.load_valid() is not None


def test_manifest_publish_failure_rolls_back_prior_cache(
    tmp_path: Path, hyg_csv_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior_cache = _publish_valid_cache(tmp_path, hyg_csv_bytes)
    before_catalog = prior_cache.catalog_path.read_bytes()
    before_manifest = prior_cache.manifest_path.read_bytes()
    replacement_csv = hyg_csv_bytes.replace(b"Fixture Star 1", b"Replacement Star", 1)
    archive = gzip.compress(replacement_csv)
    cache = FullCatalogCache(tmp_path, _test_source(archive))
    real_replace = catalog_module.os.replace
    manifest_replace_failed = False

    def fail_manifest_replace(source: Path | str, destination: Path | str) -> None:
        nonlocal manifest_replace_failed
        if Path(destination) == cache.manifest_path and not manifest_replace_failed:
            manifest_replace_failed = True
            raise OSError("fixture manifest rename failure")
        real_replace(source, destination)

    monkeypatch.setattr(catalog_module.os, "replace", fail_manifest_replace)

    with pytest.raises(CatalogDownloadError):
        cache.download_and_publish(FakeFetcher(chunks=[archive]))

    assert cache.catalog_path.read_bytes() == before_catalog
    assert cache.manifest_path.read_bytes() == before_manifest
    assert prior_cache.load_valid() is not None


def test_manifest_publish_failure_on_fresh_cache_leaves_no_artifacts(
    tmp_path: Path, hyg_csv_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = gzip.compress(hyg_csv_bytes)
    cache = FullCatalogCache(tmp_path, _test_source(archive))
    real_replace = catalog_module.os.replace

    def fail_manifest_replace(source: Path | str, destination: Path | str) -> None:
        if Path(destination) == cache.manifest_path:
            raise OSError("fixture manifest rename failure")
        real_replace(source, destination)

    monkeypatch.setattr(catalog_module.os, "replace", fail_manifest_replace)

    with pytest.raises(CatalogDownloadError, match="could not be validated"):
        cache.download_and_publish(FakeFetcher(chunks=[archive]))

    assert not cache.catalog_path.exists()
    assert not cache.manifest_path.exists()
    assert list(cache.cache_root.glob("*.tmp")) == []


def test_download_converts_fetcher_and_chunk_failures_and_cleans_up(
    tmp_path: Path, hyg_csv_bytes: bytes
) -> None:
    archive = gzip.compress(hyg_csv_bytes)
    cache = FullCatalogCache(tmp_path, _test_source(archive))

    with pytest.raises(CatalogDownloadError, match="could not be validated"):
        cache.download_and_publish(RaisingFetcher())

    def interrupted_chunks() -> Iterable[bytes]:
        yield archive[:16]
        raise RuntimeError("fixture chunk iteration failure")

    with pytest.raises(CatalogDownloadError, match="could not be validated"):
        cache.download_and_publish(FakeFetcher(chunks=interrupted_chunks()))

    assert not cache.catalog_path.exists()
    assert not cache.manifest_path.exists()
    assert list(cache.cache_root.glob("*.tmp")) == []


def test_gzip_filename_cannot_change_fixed_catalog_path(tmp_path: Path, hyg_csv_bytes: bytes) -> None:
    archive = _gzip_with_filename(hyg_csv_bytes, "../../outside/catalog.csv")
    cache = FullCatalogCache(tmp_path, _test_source(archive))

    cache.download_and_publish(FakeFetcher(chunks=[archive]))

    assert cache.catalog_path.read_bytes() == hyg_csv_bytes
    assert not (tmp_path / "outside" / "catalog.csv").exists()


def test_failed_download_never_publishes_partial_cache(tmp_path: Path) -> None:
    archive = gzip.compress(b"id,ra,dec,proper\n1,0,0,missing magnitude\n")
    cache = FullCatalogCache(tmp_path, _test_source(archive))

    with pytest.raises(CatalogDownloadError):
        cache.download_and_publish(FakeFetcher(chunks=[archive]))

    assert not cache.catalog_path.exists()
    assert not cache.manifest_path.exists()
    assert list(cache.cache_root.glob("*.tmp")) == []


def _catalog_resources() -> dict[str, object]:
    return {
        name: json.loads(files("starskill").joinpath("data", name).read_text(encoding="utf-8"))
        for name in (
            "bright_stars.json",
            "constellation_segments.json",
            "hyg_v4_1_source.json",
        )
    }


def _replace_catalog_resources(
    monkeypatch: pytest.MonkeyPatch, resources: dict[str, object]
) -> None:
    original_read_json = catalog_module._read_json

    def read_json(name: str) -> object:
        if name in resources:
            return copy.deepcopy(resources[name])
        return original_read_json(name)

    monkeypatch.setattr(catalog_module, "_read_json", read_json)


def _refresh_records_digest(envelope: dict[str, object]) -> None:
    records = envelope["records"]
    envelope["sha256"] = sha256(
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _test_source(archive: bytes) -> HygSource:
    return HygSource(
        url="https://example.test/hygdata_v41.csv.gz",
        asset_name="hygdata_v41.csv.gz",
        version="4.1",
        license="fixture license",
        compressed_sha256=sha256(archive).hexdigest(),
    )


def _publish_valid_cache(tmp_path: Path, hyg_csv_bytes: bytes) -> FullCatalogCache:
    archive = gzip.compress(hyg_csv_bytes)
    cache = FullCatalogCache(tmp_path, _test_source(archive))
    cache.download_and_publish(FakeFetcher(chunks=[archive]))
    return cache


def _gzip_with_filename(data: bytes, filename: str) -> bytes:
    compressed = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    deflated = compressed.compress(data) + compressed.flush()
    return (
        b"\x1f\x8b\x08\x08\x00\x00\x00\x00\x00\xff"
        + filename.encode("latin-1")
        + b"\x00"
        + deflated
        + zlib.crc32(data).to_bytes(4, "little")
        + (len(data) & 0xFFFFFFFF).to_bytes(4, "little")
    )
