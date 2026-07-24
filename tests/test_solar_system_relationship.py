import csv
import json

import pytest
from pydantic import ValidationError

import starskill
import starskill.schemas as schemas


def make_task() -> "schemas.SolarSystemRelationshipTask":
    return schemas.SolarSystemRelationshipTask.model_validate(
        {
            "task_type": "solar_system_relationship",
            "targets": ["moon", "jupiter"],
            "observer": {
                "location_name": "Shanghai",
                "longitude": 121.4737,
                "latitude": 31.2304,
                "timezone": "Asia/Shanghai",
            },
            "time_range": {
                "start": "2026-03-20 19:00:00",
                "end": "2026-03-20 23:00:00",
            },
            "interval_minutes": 20,
        }
    )


def test_relationship_task_requires_exact_moon_and_jupiter_pair() -> None:
    assert hasattr(
        schemas, "SolarSystemRelationshipTask"
    ), "relationship task schema is missing"

    with pytest.raises(ValidationError, match="targets"):
        schemas.SolarSystemRelationshipTask.model_validate(
            {
                "task_type": "solar_system_relationship",
                "targets": ["moon", "moon"],
                "observer": {
                    "location_name": "Shanghai",
                    "longitude": 121.4737,
                    "latitude": 31.2304,
                    "timezone": "Asia/Shanghai",
                },
                "time_range": {
                    "start": "2026-03-20 19:00:00",
                    "end": "2026-03-20 23:00:00",
                },
            }
        )


def test_calculate_relationship_matches_skyfield_at_three_times() -> None:
    assert hasattr(
        starskill, "calculate_solar_system_relationship"
    ), "relationship calculator is missing"

    result = starskill.calculate_solar_system_relationship(make_task())

    assert len(result.samples) == 13
    assert result.settings.solar_system_ephemeris == "builtin"
    assert result.settings.atmospheric_refraction is False
    expected = {
        0: (5.226868701, 278.228209117, 81.491364406, 166.807294251, 87.920582853),
        6: (-18.169945910, 294.638591320, 63.828750666, 258.415630364, 86.663460480),
        12: (-37.708083618, 317.933613805, 38.217140899, 275.880689761, 85.230403124),
    }
    for index, reference in expected.items():
        sample = result.samples[index]
        actual = (
            sample.moon_altitude_deg,
            sample.moon_azimuth_deg,
            sample.jupiter_altitude_deg,
            sample.jupiter_azimuth_deg,
            sample.angular_separation_deg,
        )
        tolerances = (0.002, 0.001, 0.006, 0.04, 0.006)
        for value, expected_value, tolerance in zip(
            actual, reference, tolerances, strict=True
        ):
            assert value == pytest.approx(expected_value, abs=tolerance)


def test_legacy_moon_jupiter_fields_are_adapted_from_v2() -> None:
    assert hasattr(
        starskill.solar_system_relationship, "calculate_astronomical_relationship"
    ), "generic relationship calculator is missing"
    legacy_task = make_task()
    generic_task = schemas.AstronomicalRelationshipTask.model_validate(
        {
            "task_type": "astronomical_relationship",
            "primary": {"kind": "solar_system", "body": "moon"},
            "secondary": {"kind": "solar_system", "body": "jupiter"},
            "observer": legacy_task.observer.model_dump(),
            "time_range": legacy_task.time_range.model_dump(),
            "interval_minutes": legacy_task.interval_minutes,
        }
    )

    legacy = starskill.calculate_solar_system_relationship(legacy_task)
    generic = starskill.solar_system_relationship.calculate_astronomical_relationship(
        generic_task
    )

    assert len(legacy.samples) == len(generic.samples)
    for legacy_sample, generic_sample in zip(
        legacy.samples, generic.samples, strict=True
    ):
        assert legacy_sample.moon_altitude_deg == pytest.approx(
            generic_sample.primary_altitude_deg
        )
        assert legacy_sample.moon_azimuth_deg == pytest.approx(
            generic_sample.primary_azimuth_deg
        )
        assert legacy_sample.jupiter_altitude_deg == pytest.approx(
            generic_sample.secondary_altitude_deg
        )
        assert legacy_sample.jupiter_azimuth_deg == pytest.approx(
            generic_sample.secondary_azimuth_deg
        )
        assert legacy_sample.angular_separation_deg == pytest.approx(
            generic_sample.angular_separation_deg
        )


def test_relationship_writers_use_stable_contract(tmp_path) -> None:
    assert hasattr(
        starskill, "write_relationship_csv"
    ), "relationship CSV writer is missing"
    assert hasattr(
        starskill, "write_relationship_json"
    ), "relationship JSON writer is missing"
    result = starskill.calculate_solar_system_relationship(make_task())
    csv_path = tmp_path / "relationship.csv"
    json_path = tmp_path / "relationship.json"

    starskill.write_relationship_csv(result, csv_path)
    starskill.write_relationship_json(result, json_path)

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert list(rows[0]) == [
        "timestamp_local",
        "timestamp_utc",
        "moon_altitude_deg",
        "moon_azimuth_deg",
        "jupiter_altitude_deg",
        "jupiter_azimuth_deg",
        "angular_separation_deg",
    ]
    assert len(rows) == 13
    assert rows[0]["angular_separation_deg"] == "87.917"
    assert payload["task"]["targets"] == ["moon", "jupiter"]
    assert len(payload["samples"]) == 13
