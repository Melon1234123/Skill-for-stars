import copy
from hashlib import sha256
from importlib.resources import files
import json

import pytest

import starskill.sky_chart_catalog as catalog_module
from starskill.sky_chart_catalog import load_bundled_catalog, load_hyg_source


def test_bundled_catalog_is_available_from_installed_package_data() -> None:
    catalog = load_bundled_catalog()

    assert len(catalog.stars) >= 100
    assert catalog.metadata.dataset_id == "bundled-bright-stars"
    assert len(catalog.metadata.sha256) == 64
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
        return copy.deepcopy(resources.get(name, original_read_json(name)))

    monkeypatch.setattr(catalog_module, "_read_json", read_json)


def _refresh_records_digest(envelope: dict[str, object]) -> None:
    records = envelope["records"]
    envelope["sha256"] = sha256(
        json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
