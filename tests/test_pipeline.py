import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import starskill
from starskill.recommendations import HUMAN_REVIEW_ITEMS
from starskill.schemas import ObservationTask, SimbadTargetRef
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


class FailIfCalledBackend(StaticPipelineBackend):
    def query_object(self, query_name: str) -> dict:
        raise AssertionError("coordinate targets must not query SIMBAD")


def load_task() -> ObservationTask:
    return ObservationTask.model_validate_json(
        (PROJECT_ROOT / "examples/observation_m42_beijing.json").read_text(
            encoding="utf-8"
        )
    )


def fixed_clock() -> datetime:
    return datetime(2026, 7, 19, 1, 0, tzinfo=timezone.utc)


def test_observation_task_normalizes_legacy_target_to_simbad_ref() -> None:
    task = load_task()

    assert isinstance(task.target, SimbadTargetRef)
    assert task.target == SimbadTargetRef(kind="simbad", name="M42")


def test_run_pipeline_preserves_user_coordinate_provenance(tmp_path) -> None:
    task_payload = load_task().model_dump(mode="json")
    task_payload["target"] = {
        "kind": "coordinates",
        "label": "A",
        "ra_deg": 10,
        "dec_deg": 20,
    }
    task = ObservationTask.model_validate(task_payload)
    output_dir = tmp_path / "run"

    outcome = starskill.run_pipeline(
        task,
        output_dir=output_dir,
        cache_dir=tmp_path / "cache",
        backend=FailIfCalledBackend(),
        clock=fixed_clock,
    )

    result = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
    resolved = json.loads(
        (output_dir / "intermediate/target_resolved.json").read_text(
            encoding="utf-8"
        )
    )
    assert outcome.status in {"success", "degraded"}
    assert result["target"]["source"]["provider"] == "user_coordinates"
    assert resolved["source"]["provider"] == "user_coordinates"
    assert resolved["catalog_target"] is None


def test_run_pipeline_generates_chinese_report_for_zh_cn_task(tmp_path) -> None:
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
    resolved_target = json.loads(
        (output_dir / "intermediate/target_resolved.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["status"] == "success"
    assert manifest["cache_hit"] is False
    assert manifest["target_source"]["database"] == "SIMBAD"
    assert resolved_target["kind"] == "simbad"
    assert resolved_target["catalog_target"]["canonical_name"] == "M 42"
    assert resolved_target["catalog_target"]["source"]["database"] == "SIMBAD"
    assert manifest["dependencies"]["astropy"] == "7.2.0"
    assert manifest["issues"] == []
    for artifact in manifest["artifacts"]:
        path = output_dir / artifact["path"]
        assert path.stat().st_size == artifact["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]

    report = (output_dir / "report.md").read_text(encoding="utf-8")
    checklist = (output_dir / "review_checklist.md").read_text(encoding="utf-8")
    assert "# 观测报告" in report
    assert "## 计算事实" in report
    assert "- 目标：M 42" in report
    assert "## 规则判定" in report
    assert "## 需要人工复核" in report
    assert "Observation Report" not in report
    assert [
        line.removeprefix("- [ ] ")
        for line in checklist.splitlines()
        if line.startswith("- [ ]")
    ] == list(HUMAN_REVIEW_ITEMS)


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


def test_run_pipeline_assigns_unique_ids_for_same_second_runs(tmp_path) -> None:
    first = starskill.run_pipeline(
        load_task(),
        output_dir=tmp_path / "run-1",
        cache_dir=tmp_path / "cache",
        backend=StaticPipelineBackend(),
        clock=fixed_clock,
    )
    second = starskill.run_pipeline(
        load_task(),
        output_dir=tmp_path / "run-2",
        cache_dir=tmp_path / "cache",
        backend=StaticPipelineBackend(),
        clock=fixed_clock,
    )

    assert first.manifest.run_id != second.manifest.run_id
    assert first.manifest.status == second.manifest.status == "success"


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
