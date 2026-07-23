from importlib.resources import files

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
