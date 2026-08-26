import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from starskill.evaluation.models import AgentResponse, ToolCallRecord
from starskill.evaluation.personas import generate_tasks
from starskill.evaluation.self_play import (
    AgentProvider,
    SelfPlayError,
    export_post_training_datasets,
    load_self_play_trace,
    run_self_play,
)
from starskill.evaluation.persona_cli import main as persona_cli_main


def _catalog_task():
    return next(
        task
        for task in generate_tasks(personas="researcher", task_count=7, seed=42)
        if task.task_family == "catalog_query"
    )


class GoodProvider:
    def respond(self, _prompt):
        return AgentResponse(
            response_markdown="已使用 ADQL 查询并保留 provenance、行数和数据来源。",
            tool_calls=(
                ToolCallRecord(
                    tool="astronomy_catalog_query",
                    arguments={"service": "gaia", "max_rows": 100},
                    result={"resources": ["request.json", "query.adql", "result.ecsv", "provenance.json"]},
                ),
            ),
            artifacts={
                "request.json": "{}\n",
                "query.adql": "SELECT TOP 100 source_id FROM gaiadr3.gaia_source\n",
                "result.ecsv": "# %ECSV 1.0\n",
                "provenance.json": "{}\n",
            },
        )


class PoorProvider:
    def respond(self, _prompt):
        return AgentResponse(response_markdown="查询完成。")


class FailingProvider:
    def respond(self, _prompt):
        raise RuntimeError("provider unavailable")


def test_agent_provider_protocol_is_runtime_checkable() -> None:
    assert isinstance(GoodProvider(), AgentProvider)


def test_self_play_captures_required_evidence_and_scores_all_dimensions(tmp_path) -> None:
    trace = run_self_play(task=_catalog_task(), provider=GoodProvider(), output_dir=tmp_path / "run")
    run_dir = Path(trace.run_dir)

    assert trace.score.status == "completed"
    assert trace.score.task_success.score == 1.0
    assert trace.score.scientific_correctness.score == 1.0
    assert trace.score.tool_selection.score == 1.0
    assert trace.score.evidence_quality.score == 1.0
    assert trace.score.reproducibility.score == 1.0
    assert trace.score.persona_satisfaction.score == 1.0
    assert trace.satisfaction.satisfied is True
    assert {path.name for path in run_dir.iterdir()} == {
        "prompt.json",
        "response.md",
        "tool_calls.jsonl",
        "score.json",
        "satisfaction.json",
        "artifacts",
    }
    assert (run_dir / "artifacts" / "provenance.json").is_file()
    assert load_self_play_trace(run_dir) == trace


def test_self_play_provider_failure_is_recorded_as_failed_not_success(tmp_path) -> None:
    trace = run_self_play(task=_catalog_task(), provider=FailingProvider(), output_dir=tmp_path / "run")

    assert trace.score.status == "failed"
    assert trace.score.overall_score == 0.0
    assert trace.score.failure == {
        "code": "agent_provider_error",
        "message": "AgentProvider raised RuntimeError",
    }
    assert trace.satisfaction.satisfied is False
    assert (Path(trace.run_dir) / "tool_calls.jsonl").is_file()


def test_dataset_export_writes_regression_success_and_real_preference_pairs(tmp_path) -> None:
    task = _catalog_task()
    run_root = tmp_path / "runs"
    good = run_self_play(task=task, provider=GoodProvider(), output_dir=run_root / "good", run_id="good")
    poor = run_self_play(task=task, provider=PoorProvider(), output_dir=run_root / "poor", run_id="poor")
    result = export_post_training_datasets(run_root=run_root, output_dir=tmp_path / "datasets")

    regression = (tmp_path / "datasets" / "regression.jsonl").read_text(encoding="utf-8").splitlines()
    successful = (tmp_path / "datasets" / "successful_traces.jsonl").read_text(encoding="utf-8").splitlines()
    preferences = (tmp_path / "datasets" / "preferences.jsonl").read_text(encoding="utf-8").splitlines()
    preference = json.loads(preferences[0])

    assert good.score.overall_score > poor.score.overall_score
    assert result["counts"] == {"regression": 2, "successful_traces": 1, "preferences": 1}
    assert len(regression) == 2
    assert len(successful) == 1
    assert set(preference) == {"prompt", "persona", "chosen", "rejected", "reasons"}
    assert preference["chosen"] == good.response_markdown
    assert preference["rejected"] == poor.response_markdown


def test_dataset_export_rejects_incomplete_or_overwritten_output(tmp_path) -> None:
    run_root = tmp_path / "runs"
    run_self_play(task=_catalog_task(), provider=GoodProvider(), output_dir=run_root / "run")
    output_dir = tmp_path / "datasets"
    export_post_training_datasets(run_root=run_root, output_dir=output_dir)

    with pytest.raises(SelfPlayError) as exc_info:
        export_post_training_datasets(run_root=run_root, output_dir=output_dir)

    assert exc_info.value.code == "unsafe_output_path"


def test_export_datasets_cli_writes_the_required_dataset_filenames(tmp_path) -> None:
    run_root = tmp_path / "runs"
    run_self_play(task=_catalog_task(), provider=GoodProvider(), output_dir=run_root / "run")
    output_dir = tmp_path / "datasets"
    stdout = StringIO()

    with redirect_stdout(stdout):
        exit_code = persona_cli_main(
            ["export-datasets", "--run-root", str(run_root), "--output-dir", str(output_dir)]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["counts"] == {"regression": 1, "successful_traces": 1, "preferences": 0}
    assert (output_dir / "regression.jsonl").is_file()
    assert (output_dir / "successful_traces.jsonl").is_file()
    assert (output_dir / "preferences.jsonl").is_file()
