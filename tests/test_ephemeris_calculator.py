import csv
from datetime import datetime, timezone
import json
import warnings

import pytest
from astropy.utils.data import CacheMissingWarning
from pydantic import ValidationError

import starskill
import starskill.schemas as schemas


def test_ephemeris_sample_preserves_timestamp_and_degree_units() -> None:
    assert hasattr(schemas, "EphemerisSample"), "EphemerisSample schema is missing"

    sample = schemas.EphemerisSample.model_validate(
        {
            "timestamp_local": "2026-01-10T18:00:00+08:00",
            "timestamp_utc": "2026-01-10T10:00:00Z",
            "target_altitude_deg": 21.5,
            "target_azimuth_deg": 104.2,
            "sun_altitude_deg": -21.0,
            "moon_altitude_deg": -10.0,
            "moon_separation_deg": 80.0,
        }
    )

    assert sample.timestamp_local.utcoffset().total_seconds() == 8 * 3600
    assert sample.timestamp_utc == datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    assert sample.target_altitude_deg == 21.5
    assert sample.target_azimuth_deg == 104.2


@pytest.mark.parametrize("field", ["timestamp_local", "timestamp_utc"])
def test_ephemeris_sample_rejects_timezone_free_timestamp(field: str) -> None:
    payload = {
        "timestamp_local": "2026-01-10T18:00:00+08:00",
        "timestamp_utc": "2026-01-10T10:00:00Z",
        "target_altitude_deg": 21.5,
        "target_azimuth_deg": 104.2,
        "sun_altitude_deg": -21.0,
        "moon_altitude_deg": -10.0,
        "moon_separation_deg": 80.0,
    }
    payload[field] = "2026-01-10T10:00:00"

    with pytest.raises(ValidationError, match=field):
        schemas.EphemerisSample.model_validate(payload)


def test_ephemeris_sample_requires_utc_field_to_use_zero_offset() -> None:
    payload = {
        "timestamp_local": "2026-01-10T18:00:00+08:00",
        "timestamp_utc": "2026-01-10T18:00:00+08:00",
        "target_altitude_deg": 21.5,
        "target_azimuth_deg": 104.2,
        "sun_altitude_deg": -21.0,
        "moon_altitude_deg": -10.0,
        "moon_separation_deg": 80.0,
    }

    with pytest.raises(ValidationError, match="timestamp_utc"):
        schemas.EphemerisSample.model_validate(payload)


def test_time_grid_crosses_midnight_and_converts_to_utc() -> None:
    assert hasattr(starskill, "build_time_grid"), "time-grid builder is missing"

    points = starskill.build_time_grid(
        start=datetime(2026, 1, 10, 18, 0),
        end=datetime(2026, 1, 11, 2, 0),
        timezone_name="Asia/Shanghai",
        interval_minutes=10,
    )

    assert len(points) == 49
    assert points[0].local.isoformat() == "2026-01-10T18:00:00+08:00"
    assert points[0].utc == datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)
    assert points[-1].local.isoformat() == "2026-01-11T02:00:00+08:00"
    assert points[-1].utc == datetime(2026, 1, 10, 18, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("interval_minutes", [0, -10])
def test_time_grid_rejects_non_positive_interval(interval_minutes: int) -> None:
    with pytest.raises(ValueError, match="interval_minutes"):
        starskill.build_time_grid(
            start=datetime(2026, 1, 10, 19, 0),
            end=datetime(2026, 1, 10, 18, 0),
            timezone_name="Asia/Shanghai",
            interval_minutes=interval_minutes,
        )


def test_time_grid_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="end"):
        starskill.build_time_grid(
            start=datetime(2026, 1, 10, 19, 0),
            end=datetime(2026, 1, 10, 18, 0),
            timezone_name="Asia/Shanghai",
            interval_minutes=10,
        )


def make_observation_task(
    start: str = "2026-01-10 18:00:00",
    end: str = "2026-01-10 18:20:00",
) -> schemas.ObservationTask:
    return schemas.ObservationTask.model_validate(
        {
            "task_type": "observation_plan",
            "target": "M42",
            "observer": {
                "location_name": "北京",
                "longitude": 116.4074,
                "latitude": 39.9042,
                "timezone": "Asia/Shanghai",
            },
            "time_range": {"start": start, "end": end},
            "interval_minutes": 10,
        }
    )


def make_resolved_m42() -> schemas.ResolvedTarget:
    return schemas.ResolvedTarget.model_validate(
        {
            "input_name": "M42",
            "query_name": "M 42",
            "canonical_name": "M 42",
            "ra_deg": 83.8201,
            "dec_deg": -5.3876,
            "object_type": "HII",
            "aliases": ["M 42", "NGC 1976"],
            "coordinate_frame": "ICRS",
            "source": {
                "database": "SIMBAD",
                "service_url": "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
                "accessed_at": "2026-07-18T12:20:49Z",
                "from_cache": False,
            },
        }
    )


def test_calculate_ephemeris_returns_vectorized_sun_moon_and_target_samples() -> None:
    assert hasattr(starskill, "calculate_ephemeris"), "ephemeris calculator is missing"

    result = starskill.calculate_ephemeris(
        make_observation_task(),
        make_resolved_m42(),
        clock=lambda: datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc),
    )

    assert len(result.samples) == 3
    assert result.samples[0].timestamp_local.isoformat() == "2026-01-10T18:00:00+08:00"
    assert result.samples[0].timestamp_utc.isoformat() == "2026-01-10T10:00:00+00:00"
    assert result.settings.time_scale == "UTC"
    assert result.settings.horizontal_frame == "AltAz"
    assert result.settings.atmospheric_refraction is False
    assert result.settings.iers_auto_download is False
    assert result.settings.astropy_version == "7.2.0"
    for sample in result.samples:
        assert -90 <= sample.target_altitude_deg <= 90
        assert 0 <= sample.target_azimuth_deg < 360
        assert -90 <= sample.sun_altitude_deg <= 90
        assert -90 <= sample.moon_altitude_deg <= 90
        assert 0 <= sample.moon_separation_deg <= 180


def test_calculate_ephemeris_does_not_attempt_remote_cache_access() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", CacheMissingWarning)
        starskill.calculate_ephemeris(make_observation_task(), make_resolved_m42())

    cache_warnings = [
        warning for warning in caught if issubclass(warning.category, CacheMissingWarning)
    ]
    assert cache_warnings == []


def test_m42_beijing_regression_at_three_times() -> None:
    result = starskill.calculate_ephemeris(
        make_observation_task(end="2026-01-11 02:00:00"),
        make_resolved_m42(),
    )
    expected = {
        0: (13.2139368293, 108.7655341013, -9.8954883771, -60.2460237534),
        24: (44.1819336415, 169.3763179574, -54.9752201032, -30.6517897877),
        48: (23.8623638808, 239.7783847619, -62.4705343427, 12.1518434977),
    }

    assert len(result.samples) == 49
    for index, values in expected.items():
        sample = result.samples[index]
        actual = (
            sample.target_altitude_deg,
            sample.target_azimuth_deg,
            sample.sun_altitude_deg,
            sample.moon_altitude_deg,
        )
        assert actual == pytest.approx(values, abs=1e-6)


def test_write_ephemeris_csv_uses_fixed_columns_and_degree_precision(tmp_path) -> None:
    assert hasattr(starskill, "write_ephemeris_csv"), "CSV writer is missing"
    result = starskill.calculate_ephemeris(make_observation_task(), make_resolved_m42())
    output_path = tmp_path / "intermediate" / "ephemeris.csv"

    starskill.write_ephemeris_csv(result, output_path)

    with output_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "timestamp_local",
        "timestamp_utc",
        "target_altitude_deg",
        "target_azimuth_deg",
        "sun_altitude_deg",
        "moon_altitude_deg",
        "moon_separation_deg",
    ]
    assert len(rows) == 3
    assert rows[0]["timestamp_local"] == "2026-01-10T18:00:00+08:00"
    assert rows[0]["timestamp_utc"] == "2026-01-10T10:00:00+00:00"
    assert rows[0]["target_altitude_deg"] == "13.213937"
    assert rows[0]["moon_separation_deg"] == "109.332300"


def test_write_ephemeris_json_preserves_provenance_and_settings(tmp_path) -> None:
    assert hasattr(starskill, "write_ephemeris_json"), "JSON writer is missing"
    result = starskill.calculate_ephemeris(
        make_observation_task(),
        make_resolved_m42(),
        clock=lambda: datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc),
    )
    output_path = tmp_path / "intermediate" / "ephemeris.json"

    starskill.write_ephemeris_json(result, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["target"]["source"]["database"] == "SIMBAD"
    assert payload["observer"]["timezone"] == "Asia/Shanghai"
    assert payload["settings"] == {
        "calculated_at": "2026-07-18T12:30:00Z",
        "astropy_version": "7.2.0",
        "time_scale": "UTC",
        "horizontal_frame": "AltAz",
        "atmospheric_refraction": False,
        "iers_auto_download": False,
    }
    assert len(payload["samples"]) == 3
