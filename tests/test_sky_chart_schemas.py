from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from starskill.schemas import (
    SkyChartExportMetadata,
    SkyChartRequest,
    SkyChartRenderResponse,
)


def valid_request() -> dict[str, object]:
    return {
        "observer": {
            "location_name": "北京",
            "longitude": 116.4074,
            "latitude": 39.9042,
            "timezone": "Asia/Shanghai",
        },
        "timestamp_local": "2026-01-10T20:00:00+08:00",
        "target": {"mode": "name", "name": "M42"},
        "catalog_mode": "auto",
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("observer.longitude", 180.1),
        ("observer.latitude", -90.1),
        ("target.name", " "),
        ("target.name", "M42;rm"),
        ("target.name", "https://example.test/M42"),
        ("catalog_mode", "remote"),
    ],
)
def test_request_rejects_invalid_sky_chart_values(path: str, value: object) -> None:
    payload = valid_request()
    container, key = path.rsplit(".", 1) if "." in path else ("", path)
    target = payload if not container else payload[container]  # type: ignore[index]
    target[key] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        SkyChartRequest.model_validate(payload)


def test_request_forbids_unknown_fields_and_client_dimensions() -> None:
    payload = valid_request()
    payload["width_px"] = 1200
    with pytest.raises(ValidationError, match="width_px"):
        SkyChartRequest.model_validate(payload)


def test_timestamp_offset_must_match_named_timezone() -> None:
    payload = valid_request()
    payload["timestamp_local"] = "2026-01-10T20:00:00+00:00"
    with pytest.raises(ValidationError, match="offset"):
        SkyChartRequest.model_validate(payload)


def test_coordinate_mode_requires_ra_and_dec_and_forbids_name() -> None:
    payload = valid_request()
    payload["target"] = {
        "mode": "coordinates",
        "ra_deg": 83.822083,
        "dec_deg": -5.391111,
        "name": "M42",
    }
    with pytest.raises(ValidationError, match="coordinates"):
        SkyChartRequest.model_validate(payload)


def valid_metadata() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "render_id": "opaque_url_safe_id",
        "created_at_utc": "2026-07-23T12:00:00Z",
        "request": {
            "observer": {
                "location_name": "北京",
                "longitude": 116.4074,
                "latitude": 39.9042,
                "timezone": "Asia/Shanghai",
            },
            "timestamp_local": "2026-07-23T20:00:00+08:00",
            "timestamp_utc": "2026-07-23T12:00:00Z",
            "target": {"mode": "name", "input": "M42", "resolved": None},
            "catalog_mode_requested": "auto",
            "catalog_mode_used": "bundled",
        },
        "render": {
            "projection": "azimuthal_equidistant_zenith",
            "width_px": 1200,
            "height_px": 900,
            "layer_order": [
                "background",
                "horizon_grid",
                "constellations",
                "stars",
                "moon",
                "planets",
                "target",
                "footer",
            ],
            "png_sha256": "a" * 64,
        },
        "objects": {
            "moon": {
                "label": "Moon",
                "icrs": None,
                "altaz": {"altitude_deg": 10, "azimuth_deg": 20},
                "visible": True,
                "drawn": True,
            },
            "planets": [],
            "target": None,
            "stars_drawn": 0,
            "constellation_segments_drawn": 0,
        },
        "catalog": {
            "dataset_id": "bundled-bright-stars",
            "version": "2026.07.23",
            "source_url": "https://example.test/catalog",
            "license": "CC-BY-4.0",
            "sha256": "b" * 64,
            "status": "available",
        },
        "calculation": {
            "time_scale": "UTC",
            "horizontal_frame": "AltAz",
            "atmospheric_refraction": False,
            "solar_system_ephemeris": "builtin",
            "iers_auto_download": False,
        },
        "dependencies": {
            "python": "3.11.0",
            "astropy": "7.2.0",
            "matplotlib": "3.10.9",
            "tzdata": "2025.2",
        },
        "warnings": [],
    }


def test_export_metadata_enforces_fixed_calculation_provenance() -> None:
    metadata = SkyChartExportMetadata.model_validate(valid_metadata())
    assert metadata.render.width_px == 1200
    assert metadata.calculation.time_scale == "UTC"
    assert metadata.model_dump(mode="json")["created_at_utc"] == "2026-07-23T12:00:00Z"

    payload = valid_metadata()
    payload["render"]["png_sha256"] = "A" * 64  # type: ignore[index]
    with pytest.raises(ValidationError, match="png_sha256"):
        SkyChartExportMetadata.model_validate(payload)

    payload = valid_metadata()
    payload["calculation"]["iers_auto_download"] = True  # type: ignore[index]
    with pytest.raises(ValidationError, match="iers_auto_download"):
        SkyChartExportMetadata.model_validate(payload)


def test_render_response_exposes_only_urls_and_layer_status() -> None:
    response = SkyChartRenderResponse(
        render_id="opaque_url_safe_id",
        png_url="/v1/sky-chart/renders/opaque_url_safe_id.png",
        json_url="/v1/sky-chart/renders/opaque_url_safe_id.json",
        catalog_mode_used="bundled",
        catalog_status="available",
        warnings=[],
    )
    assert response.model_dump() == {
        "render_id": "opaque_url_safe_id",
        "png_url": "/v1/sky-chart/renders/opaque_url_safe_id.png",
        "json_url": "/v1/sky-chart/renders/opaque_url_safe_id.json",
        "catalog_mode_used": "bundled",
        "catalog_status": "available",
        "warnings": [],
    }
