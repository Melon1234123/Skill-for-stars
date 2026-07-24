import csv
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from starskill import schemas
from starskill import solar_system_relationship as relationship


class StaticSimbadBackend:
    service_url = "https://example.test/simbad"

    _records = {
        "M 31": {
            "canonical_name": "M 31",
            "ra_deg": 10.684708,
            "dec_deg": 41.26875,
            "object_type": "Galaxy",
            "aliases": ["M 31", "NGC 224"],
        },
        "M 42": {
            "canonical_name": "M 42",
            "ra_deg": 83.822083,
            "dec_deg": -5.391111,
            "object_type": "HII region",
            "aliases": ["M 42", "NGC 1976"],
        },
    }

    def query_object(self, query_name: str) -> dict[str, object] | None:
        return self._records.get(query_name)


FIXED_NOW = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_NOW


def make_task(
    primary: dict[str, Any], secondary: dict[str, Any]
) -> schemas.AstronomicalRelationshipTask:
    return schemas.AstronomicalRelationshipTask.model_validate(
        {
            "task_type": "astronomical_relationship",
            "primary": primary,
            "secondary": secondary,
            "observer": {
                "location_name": "Shanghai",
                "longitude": 121.4737,
                "latitude": 31.2304,
                "timezone": "Asia/Shanghai",
            },
            "time_range": {
                "start": "2026-01-10T18:00:00+08:00",
                "end": "2026-01-10T18:20:00+08:00",
            },
            "interval_minutes": 20,
        }
    )


def generic_calculator() -> Callable[..., schemas.AstronomicalRelationshipResult]:
    assert hasattr(
        relationship, "calculate_astronomical_relationship"
    ), "generic relationship calculator is missing"
    return relationship.calculate_astronomical_relationship


def generic_csv_writer() -> Callable[
    [schemas.AstronomicalRelationshipResult, Path], None
]:
    assert hasattr(
        relationship, "write_astronomical_relationship_csv"
    ), "generic relationship CSV writer is missing"
    return relationship.write_astronomical_relationship_csv


@pytest.mark.parametrize(
    ("primary", "secondary"),
    [
        (
            {"kind": "solar_system", "body": "mars"},
            {"kind": "solar_system", "body": "saturn"},
        ),
        (
            {"kind": "solar_system", "body": "mars"},
            {"kind": "simbad", "name": "M31"},
        ),
        (
            {"kind": "solar_system", "body": "mars"},
            {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20},
        ),
        (
            {"kind": "simbad", "name": "M31"},
            {"kind": "solar_system", "body": "mars"},
        ),
        (
            {"kind": "simbad", "name": "M31"},
            {"kind": "simbad", "name": "M42"},
        ),
        (
            {"kind": "simbad", "name": "M31"},
            {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20},
        ),
        (
            {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20},
            {"kind": "solar_system", "body": "mars"},
        ),
        (
            {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20},
            {"kind": "simbad", "name": "M31"},
        ),
        (
            {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20},
            {"kind": "coordinates", "label": "D", "ra_deg": 11, "dec_deg": 21},
        ),
    ],
)
def test_all_ordered_target_kinds_produce_apparent_altaz(
    primary: dict[str, Any], secondary: dict[str, Any]
) -> None:
    result = generic_calculator()(
        make_task(primary, secondary),
        target_backend=StaticSimbadBackend(),
        clock=fixed_clock,
    )

    assert result.settings.schema_version == "2.0"
    assert len(result.samples) == 2
    assert all(0 <= sample.angular_separation_deg <= 180 for sample in result.samples)
    assert all(
        sample.primary_is_above_horizon == (sample.primary_altitude_deg >= 0)
        for sample in result.samples
    )
    assert all(
        sample.secondary_is_above_horizon == (sample.secondary_altitude_deg >= 0)
        for sample in result.samples
    )


def test_v2_csv_uses_primary_secondary_fields_and_stable_values(tmp_path: Path) -> None:
    result = generic_calculator()(
        make_task(
            {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20},
            {"kind": "coordinates", "label": "D", "ra_deg": 11, "dec_deg": 21},
        ),
        clock=fixed_clock,
    )
    output_path = tmp_path / "relationship-v2.csv"

    generic_csv_writer()(result, output_path)

    with output_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "timestamp_local",
        "timestamp_utc",
        "primary_altitude_deg",
        "primary_azimuth_deg",
        "primary_is_above_horizon",
        "secondary_altitude_deg",
        "secondary_azimuth_deg",
        "secondary_is_above_horizon",
        "angular_separation_deg",
    ]
    assert len(rows) == 2
    assert rows[0]["primary_altitude_deg"] == (
        f"{result.samples[0].primary_altitude_deg:.3f}"
    )
    assert rows[0]["primary_is_above_horizon"] == str(
        result.samples[0].primary_is_above_horizon
    )


def test_v2_json_includes_target_refs_and_resolved_provenance() -> None:
    result = generic_calculator()(
        make_task(
            {"kind": "solar_system", "body": "mars"},
            {"kind": "simbad", "name": "M31"},
        ),
        target_backend=StaticSimbadBackend(),
        clock=fixed_clock,
    )

    payload = json.loads(result.model_dump_json())

    assert payload["task"]["primary"] == {"kind": "solar_system", "body": "mars"}
    assert payload["task"]["secondary"] == {"kind": "simbad", "name": "M31"}
    assert payload["primary"]["source"]["provider"] == "astropy_builtin_ephemeris"
    assert payload["secondary"]["source"]["provider"] == "simbad"
    assert payload["secondary"]["catalog_target"]["source"]["service_url"] == (
        StaticSimbadBackend.service_url
    )
