"""Deterministic M42 inputs shared by CLI and planning tests."""

from datetime import datetime, timezone
from pathlib import Path

from starskill.ephemeris_calculator import calculate_ephemeris, write_ephemeris_json
from starskill.schemas import ObservationTask, ResolvedTarget


def make_m42_task() -> ObservationTask:
    return ObservationTask.model_validate(
        {
            "task_type": "observation_plan",
            "target": "M42",
            "observer": {
                "location_name": "Beijing",
                "longitude": 116.4074,
                "latitude": 39.9042,
                "timezone": "Asia/Shanghai",
            },
            "time_range": {
                "start": "2026-01-10 18:00:00",
                "end": "2026-01-11 02:00:00",
            },
            "interval_minutes": 10,
        }
    )


def make_resolved_m42() -> ResolvedTarget:
    return ResolvedTarget.model_validate(
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


def make_m42_ephemeris():
    return calculate_ephemeris(
        make_m42_task(),
        make_resolved_m42(),
        clock=lambda: datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc),
    )


def write_m42_target(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(make_resolved_m42().model_dump_json(indent=2), encoding="utf-8")


def write_m42_ephemeris(path: Path) -> None:
    write_ephemeris_json(make_m42_ephemeris(), path)
