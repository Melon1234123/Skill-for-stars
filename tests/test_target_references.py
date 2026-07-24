from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from starskill.schemas import (
    AstronomicalRelationshipResult,
    AstronomicalRelationshipSample,
    AstronomicalRelationshipTask,
    TargetRef,
)


@pytest.fixture
def valid_observer() -> dict:
    return {
        "location_name": "Beijing",
        "longitude": 116.4074,
        "latitude": 39.9042,
        "timezone": "Asia/Shanghai",
    }


def test_target_ref_accepts_each_supported_kind() -> None:
    adapter = TypeAdapter(TargetRef)

    assert adapter.validate_python({"kind": "solar_system", "body": "Mars"}).body == "mars"
    assert adapter.validate_python({"kind": "simbad", "name": "M31"}).name == "M31"
    assert adapter.validate_python(
        {
            "kind": "coordinates",
            "label": "Andromeda center",
            "ra_deg": 10.684708,
            "dec_deg": 41.26875,
        }
    ).ra_deg == 10.684708


def test_coordinates_and_general_relationship_reject_invalid_contracts(
    valid_observer: dict,
) -> None:
    with pytest.raises(ValidationError, match="ra_deg"):
        TypeAdapter(TargetRef).validate_python(
            {"kind": "coordinates", "label": "x", "ra_deg": 360, "dec_deg": 0}
        )

    task = AstronomicalRelationshipTask.model_validate(
        {
            "task_type": "astronomical_relationship",
            "primary": {"kind": "coordinates", "label": "A", "ra_deg": 0, "dec_deg": 0},
            "secondary": {"kind": "coordinates", "label": "B", "ra_deg": 1, "dec_deg": 1},
            "observer": valid_observer,
            "time_range": {
                "start": "2026-01-10T18:00:00+08:00",
                "end": "2026-01-10T18:20:00+08:00",
            },
        }
    )

    assert task.interval_minutes == 20


def test_general_relationship_result_records_apparent_altaz_provenance(
    valid_observer: dict,
) -> None:
    result = AstronomicalRelationshipResult.model_validate(
        {
            "task": {
                "task_type": "astronomical_relationship",
                "primary": {"kind": "solar_system", "body": "moon"},
                "secondary": {"kind": "simbad", "name": "M31"},
                "observer": valid_observer,
                "time_range": {
                    "start": "2026-01-10T10:00:00+00:00",
                    "end": "2026-01-10T10:20:00+00:00",
                },
            },
            "settings": {
                "calculated_at": datetime(2026, 1, 10, tzinfo=timezone.utc),
                "astropy_version": "7.0.0",
            },
            "primary": {
                "label": "Moon",
                "kind": "solar_system",
                "motion": "dynamic",
                "ra_deg": 10,
                "dec_deg": 1,
                "source": {
                    "provider": "astropy_builtin_ephemeris",
                    "from_cache": False,
                    "accessed_at": "2026-01-10T10:00:00+00:00",
                },
            },
            "secondary": {
                "label": "M31",
                "kind": "simbad",
                "motion": "fixed_icrs",
                "ra_deg": 10.684708,
                "dec_deg": 41.26875,
                "source": {
                    "provider": "simbad_cache",
                    "from_cache": True,
                    "accessed_at": "2026-01-10T10:00:00+00:00",
                },
                "catalog_target": {
                    "input_name": "M31",
                    "query_name": "M31",
                    "canonical_name": "M 31",
                    "ra_deg": 10.684708,
                    "dec_deg": 41.26875,
                    "object_type": "Galaxy",
                    "aliases": ["Andromeda Galaxy"],
                    "source": {
                        "database": "SIMBAD",
                        "service_url": "https://simbad.cds.unistra.fr/",
                        "accessed_at": "2026-01-10T10:00:00+00:00",
                        "from_cache": True,
                    },
                },
            },
            "samples": [
                {
                    "timestamp_local": "2026-01-10T18:00:00+08:00",
                    "timestamp_utc": "2026-01-10T10:00:00+00:00",
                    "primary_altitude_deg": 20,
                    "primary_azimuth_deg": 100,
                    "primary_is_above_horizon": True,
                    "secondary_altitude_deg": -2,
                    "secondary_azimuth_deg": 270,
                    "secondary_is_above_horizon": False,
                    "angular_separation_deg": 85,
                }
            ],
        }
    )

    assert result.settings.schema_version == "2.0"
    assert result.settings.time_scale == "UTC"
    assert result.settings.horizontal_frame == "AltAz"
    assert result.settings.solar_system_ephemeris == "builtin"
    assert result.settings.atmospheric_refraction is False
    assert result.settings.iers_auto_download is False


@pytest.mark.parametrize(
    ("altitude_field", "horizon_field", "altitude_deg", "is_above_horizon"),
    [
        ("primary_altitude_deg", "primary_is_above_horizon", 20, False),
        ("secondary_altitude_deg", "secondary_is_above_horizon", -2, True),
    ],
)
def test_relationship_sample_rejects_contradictory_horizon_state(
    altitude_field: str,
    horizon_field: str,
    altitude_deg: float,
    is_above_horizon: bool,
) -> None:
    sample = {
        "timestamp_local": "2026-01-10T18:00:00+08:00",
        "timestamp_utc": "2026-01-10T10:00:00+00:00",
        "primary_altitude_deg": 20,
        "primary_azimuth_deg": 100,
        "primary_is_above_horizon": True,
        "secondary_altitude_deg": -2,
        "secondary_azimuth_deg": 270,
        "secondary_is_above_horizon": False,
        "angular_separation_deg": 85,
    }
    sample[altitude_field] = altitude_deg
    sample[horizon_field] = is_above_horizon

    with pytest.raises(ValidationError, match=horizon_field):
        AstronomicalRelationshipSample.model_validate(sample)
