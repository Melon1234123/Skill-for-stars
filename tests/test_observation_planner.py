import csv
from datetime import timedelta
import json
from pathlib import Path

import pytest
from PIL import Image, ImageStat

import starskill
import starskill.schemas as schemas


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_m42_ephemeris() -> schemas.EphemerisResult:
    return schemas.EphemerisResult.model_validate_json(
        (PROJECT_ROOT / "runs/day3_m42/intermediate/ephemeris.json").read_text(
            encoding="utf-8"
        )
    )


def make_ephemeris(
    target_altitudes: list[float],
    sun_altitudes: list[float],
) -> schemas.EphemerisResult:
    source = load_m42_ephemeris()
    first = source.samples[0]
    samples = [
        first.model_copy(
            update={
                "timestamp_local": first.timestamp_local + timedelta(minutes=10 * index),
                "timestamp_utc": first.timestamp_utc + timedelta(minutes=10 * index),
                "target_altitude_deg": target_altitude,
                "sun_altitude_deg": sun_altitudes[index],
            }
        )
        for index, target_altitude in enumerate(target_altitudes)
    ]
    return source.model_copy(update={"samples": samples})


def test_plan_observation_applies_inclusive_thresholds_and_reasons() -> None:
    assert hasattr(schemas, "VisibilityCriteria"), "visibility criteria are missing"
    assert hasattr(starskill, "plan_observation"), "observation planner is missing"
    ephemeris = make_ephemeris(
        target_altitudes=[29.9, 30.0, 35.0, 29.0],
        sun_altitudes=[-15.0, -12.0, -11.9, -10.0],
    )

    plan = starskill.plan_observation(ephemeris, schemas.VisibilityCriteria())

    assert [sample.is_observable for sample in plan.samples] == [False, True, False, False]
    assert plan.samples[0].rejection_reasons == ["target_below_minimum_altitude"]
    assert plan.samples[1].rejection_reasons == []
    assert plan.samples[2].rejection_reasons == ["sun_above_maximum_altitude"]
    assert plan.samples[3].rejection_reasons == [
        "target_below_minimum_altitude",
        "sun_above_maximum_altitude",
    ]
    assert len(plan.windows) == 1
    assert plan.windows[0].start_local == plan.samples[1].timestamp_local
    assert plan.windows[0].end_local == plan.samples[1].timestamp_local
    assert plan.windows[0].sample_count == 1


def test_plan_observation_returns_no_windows_when_all_samples_fail() -> None:
    ephemeris = make_ephemeris(
        target_altitudes=[10.0, 20.0, 29.0],
        sun_altitudes=[-20.0, -20.0, -20.0],
    )

    plan = starskill.plan_observation(ephemeris, schemas.VisibilityCriteria())

    assert not any(sample.is_observable for sample in plan.samples)
    assert plan.windows == []


def test_plan_observation_merges_multiple_contiguous_windows() -> None:
    ephemeris = make_ephemeris(
        target_altitudes=[35.0, 36.0, 29.0, 40.0, 41.0],
        sun_altitudes=[-20.0] * 5,
    )

    plan = starskill.plan_observation(ephemeris, schemas.VisibilityCriteria())

    assert len(plan.windows) == 2
    assert [(window.sample_count, window.peak_target_altitude_deg) for window in plan.windows] == [
        (2, 36.0),
        (2, 41.0),
    ]
    assert plan.windows[0].start_utc == plan.samples[0].timestamp_utc
    assert plan.windows[0].end_utc == plan.samples[1].timestamp_utc
    assert plan.windows[1].start_utc == plan.samples[3].timestamp_utc
    assert plan.windows[1].end_utc == plan.samples[4].timestamp_utc


def test_moon_illumination_matches_independent_reference_without_becoming_a_rule() -> None:
    assert hasattr(
        starskill, "calculate_moon_illumination"
    ), "moon illumination calculator is missing"
    ephemeris = load_m42_ephemeris()
    selected = [ephemeris.samples[index] for index in (0, 24, 48)]

    illumination = starskill.calculate_moon_illumination(
        [sample.timestamp_utc for sample in selected]
    )
    plan = starskill.plan_observation(ephemeris, schemas.VisibilityCriteria())

    assert illumination == pytest.approx(
        [0.524849460043, 0.508690266580, 0.492578603587], abs=5e-4
    )
    assert [plan.samples[index].moon_illumination_fraction for index in (0, 24, 48)] == pytest.approx(
        illumination,
        abs=1e-12,
    )
    assert all(
        set(sample.rejection_reasons)
        <= {"target_below_minimum_altitude", "sun_above_maximum_altitude"}
        for sample in plan.samples
    )


def test_visibility_writers_preserve_samples_rules_and_provenance(tmp_path) -> None:
    assert hasattr(starskill, "write_visibility_csv"), "visibility CSV writer is missing"
    assert hasattr(
        starskill, "write_observation_plan_json"
    ), "observation plan JSON writer is missing"
    plan = starskill.plan_observation(load_m42_ephemeris(), schemas.VisibilityCriteria())
    csv_path = tmp_path / "intermediate" / "visibility.csv"
    json_path = tmp_path / "result.json"

    starskill.write_visibility_csv(plan, csv_path)
    starskill.write_observation_plan_json(plan, json_path)

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "timestamp_local",
        "timestamp_utc",
        "target_altitude_deg",
        "target_azimuth_deg",
        "sun_altitude_deg",
        "moon_altitude_deg",
        "moon_separation_deg",
        "moon_illumination_fraction",
        "is_observable",
        "rejection_reasons",
    ]
    assert len(rows) == 49
    assert rows[0]["moon_illumination_fraction"] == "0.524799"
    assert rows[0]["is_observable"] == "false"
    assert rows[0]["rejection_reasons"] == (
        "target_below_minimum_altitude;sun_above_maximum_altitude"
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["criteria"] == {
        "min_target_altitude_deg": 30.0,
        "max_sun_altitude_deg": -12.0,
    }
    assert payload["source_ephemeris_settings"]["time_scale"] == "UTC"
    assert payload["source_ephemeris_settings"]["astropy_version"] == "7.2.0"
    assert len(payload["samples"]) == 49
    assert len(payload["windows"]) == 1


def test_plot_visibility_exports_stable_nonblank_png_and_closes_figure(tmp_path) -> None:
    assert hasattr(starskill, "plot_visibility"), "visibility plotter is missing"
    plan = starskill.plan_observation(load_m42_ephemeris(), schemas.VisibilityCriteria())
    output_path = tmp_path / "figures" / "visibility_curve.png"

    starskill.plot_visibility(plan, output_path)

    from matplotlib import pyplot as plt

    assert output_path.stat().st_size > 30_000
    with Image.open(output_path) as image:
        assert image.size == (1800, 900)
        assert max(ImageStat.Stat(image.convert("RGB")).stddev) > 20
    assert plt.get_fignums() == []
