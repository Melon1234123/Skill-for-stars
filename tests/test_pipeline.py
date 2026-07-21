import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import starskill
from starskill.schemas import ObservationTask
from starskill.target_resolver import TargetServiceError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StaticPipelineBackend:
    service_url = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

    def __init__(self) -> None:
        self.call_count = 0

    def query_object(self, query_name: str) -> dict:
        self.call_count += 1
        return {
            "canonical_name": "M 42",
            "ra_deg": 83.8201,
            "dec_deg": -5.3876,
            "object_type": "HII",
            "aliases": ["M 42", "NGC 1976", "Orion Nebula"],
        }


class FailingPipelineBackend(StaticPipelineBackend):
    def query_object(self, query_name: str) -> dict:
        raise TimeoutError("SIMBAD timed out")


def load_task() -> ObservationTask:
    return ObservationTask.model_validate_json(
        (PROJECT_ROOT / "examples/observation_m42_beijing.json").read_text(
            encoding="utf-8"
        )
    )


def fixed_clock() -> datetime:
    return datetime(2026, 7, 19, 1, 0, tzinfo=timezone.utc)


def test_run_pipeline_generates_auditable_complete_artifacts(tmp_path) -> None:
    assert hasattr(starskill, "run_pipeline"), "pipeline runner is missing"
    output_dir = tmp_path / "run"

    outcome = starskill.run_pipeline(
        load_task(),
        output_dir=output_dir,
        cache_dir=tmp_path / "cache",
        backend=StaticPipelineBackend(),
        clock=fixed_clock,
    )

    expected = {
        "input.json",
        "run.json",
        "result.json",
        "report.md",
        "review_checklist.md",
        "intermediate/target_resolved.json",
        "intermediate/ephemeris.csv",
        "intermediate/ephemeris.json",
        "intermediate/visibility.csv",
        "figures/visibility_curve.png",
    }
    assert outcome.status == "success"
    assert {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_file()} == expected

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "success"
    assert manifest["cache_hit"] is False
    assert manifest["target_source"]["database"] == "SIMBAD"
    assert manifest["dependencies"]["astropy"] == "7.2.0"
    assert manifest["issues"] == []
    for artifact in manifest["artifacts"]:
        path = output_dir / artifact["path"]
        assert path.stat().st_size == artifact["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]

    report = (output_dir / "report.md").read_text(encoding="utf-8")
    checklist = (output_dir / "review_checklist.md").read_text(encoding="utf-8")
    assert "## Calculated Facts" in report
    assert "## Rule-based Assessment" in report
    assert "## Human Review Required" in report
    assert "- [ ]" in checklist


def test_run_pipeline_reports_cache_hit_on_second_run(tmp_path) -> None:
    backend = StaticPipelineBackend()
    cache_dir = tmp_path / "cache"

    first = starskill.run_pipeline(
        load_task(),
        output_dir=tmp_path / "run-1",
        cache_dir=cache_dir,
        backend=backend,
        clock=fixed_clock,
    )
    second = starskill.run_pipeline(
        load_task(),
        output_dir=tmp_path / "run-2",
        cache_dir=cache_dir,
        backend=backend,
        clock=fixed_clock,
    )

    assert first.manifest.cache_hit is False
    assert second.manifest.cache_hit is True
    assert backend.call_count == 1


def test_run_pipeline_keeps_data_when_figure_generation_fails(tmp_path) -> None:
    def fail_plot(*args, **kwargs) -> None:
        raise RuntimeError("renderer unavailable")

    output_dir = tmp_path / "degraded-run"
    outcome = starskill.run_pipeline(
        load_task(),
        output_dir=output_dir,
        cache_dir=tmp_path / "cache",
        backend=StaticPipelineBackend(),
        plotter=fail_plot,
        clock=fixed_clock,
    )

    assert outcome.status == "degraded"
    assert (output_dir / "result.json").is_file()
    assert (output_dir / "intermediate/ephemeris.csv").is_file()
    assert (output_dir / "intermediate/visibility.csv").is_file()
    assert (output_dir / "report.md").is_file()
    assert not (output_dir / "figures/visibility_curve.png").exists()
    assert outcome.manifest.issues[0].code == "figure_generation_failed"
    assert outcome.manifest.issues[0].stage == "visualization"


def test_run_pipeline_records_failed_resolution_without_fake_outputs(tmp_path) -> None:
    output_dir = tmp_path / "failed-run"

    with pytest.raises(TargetServiceError):
        starskill.run_pipeline(
            load_task(),
            output_dir=output_dir,
            cache_dir=tmp_path / "cache",
            backend=FailingPipelineBackend(),
            clock=fixed_clock,
        )

    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["target_source"] is None
    assert manifest["issues"][0]["stage"] == "target_resolution"
    assert manifest["issues"][0]["code"] == "target_service_error"
    assert (output_dir / "input.json").is_file()
    assert not (output_dir / "result.json").exists()
    assert not (output_dir / "report.md").exists()
    assert not (output_dir / "figures/visibility_curve.png").exists()
