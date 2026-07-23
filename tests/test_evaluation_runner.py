import json
import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

import scripts.evaluate_starskill as evaluation_cli
from scripts.evaluate_starskill import main
from starskill.evaluation.cases import load_case
from starskill.evaluation.models import EvaluationSummary
from starskill.evaluation.runner import execute_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_execute_records_the_real_validate_process(tmp_path: Path) -> None:
    run_dir = tmp_path / "invalid-timezone"
    record = execute_case(
        PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json",
        run_dir,
        python_executable=Path(sys.executable),
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
    )

    execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))

    assert record.return_code == 2
    assert record.command_argv[:4] == [
        str(Path(sys.executable)),
        "-m",
        "starskill",
        "validate",
    ]
    assert record.command_argv[4] == str((run_dir / "task.json").resolve())
    assert execution["recorder"] == "starskill.evaluation.runner"
    assert execution["return_code"] == 2
    assert execution["command_argv"] == record.command_argv
    assert (run_dir / "case.json").is_file()
    assert (run_dir / "task.json").is_file()
    assert (run_dir / "stdout.txt").read_text(encoding="utf-8") == ""
    assert "validation_error" in (run_dir / "stderr.txt").read_text(encoding="utf-8")
    assert (run_dir / "exit_code.txt").read_text(encoding="utf-8") == "2\n"
    assert not (run_dir / "tool_calls.jsonl").exists()


def test_replay_uses_the_script_generated_execution_record(tmp_path: Path) -> None:
    case_path = PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"
    run_dir = tmp_path / "invalid-timezone"
    execute_case(
        case_path,
        run_dir,
        python_executable=Path(sys.executable),
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
    )

    exit_code = main(
        [
            "replay",
            "--case",
            str(case_path),
            "--run-dir",
            str(run_dir),
            "--output-dir",
            str(tmp_path / "score"),
        ]
    )

    score = json.loads((tmp_path / "score" / "score.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert score["raw_inputs"]["return_code"] == 2
    assert score["raw_inputs"]["execution_file"].endswith("execution.json")


def test_replay_rejects_a_tampered_recorded_command(tmp_path: Path) -> None:
    case_path = PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"
    run_dir = tmp_path / "invalid-timezone"
    execute_case(
        case_path,
        run_dir,
        python_executable=Path(sys.executable),
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
    )
    execution_path = run_dir / "execution.json"
    payload = json.loads(execution_path.read_text(encoding="utf-8"))
    payload["command_argv"][3] = "run"
    execution_path.write_text(json.dumps(payload), encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(case_path),
                "--run-dir",
                str(run_dir),
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "invalid_execution_evidence"


def test_replay_rejects_a_tampered_task_copy(tmp_path: Path) -> None:
    case_path = PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"
    run_dir = tmp_path / "invalid-timezone"
    execute_case(
        case_path,
        run_dir,
        python_executable=Path(sys.executable),
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
    )
    (run_dir / "task.json").write_text("{}\n", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(case_path),
                "--run-dir",
                str(run_dir),
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "invalid_execution_evidence"


def test_acceptance_runs_each_core_and_variant_once(tmp_path: Path, monkeypatch) -> None:
    executed_case_ids: list[str] = []

    def fake_execute(case_path: Path, run_dir: Path, **_kwargs):
        case = load_case(case_path)
        executed_case_ids.append(case.case_id)
        run_dir.mkdir(parents=True)
        return type("Record", (), {"return_code": case.expected_exit_code})()

    summary = EvaluationSummary(
        total_runs=9,
        hard_gate_pass_rate=1.0,
        core_hard_gate_pass_rate=1.0,
        variant_hard_gate_pass_rate=1.0,
        average_base_score=89.0,
        core_average_base_score=89.0,
        per_case_standard_deviation={},
        open_task_scores={},
        critical_failures=0,
        passed=True,
        thresholds={},
        decisions={},
        reports=[],
    )

    monkeypatch.setattr(evaluation_cli, "execute_case", fake_execute)
    monkeypatch.setattr(evaluation_cli, "_replay", lambda _args: 0)
    monkeypatch.setattr(evaluation_cli, "collect_score_reports", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(evaluation_cli, "aggregate_scores", lambda _bundles: summary)
    monkeypatch.setattr(
        evaluation_cli,
        "write_aggregate_reports",
        lambda _summary, _bundles, output_dir: (output_dir / "summary.json").write_text("{}"),
    )

    exit_code = evaluation_cli.main(
        [
            "acceptance",
            "--run-root",
            str(tmp_path / "runs"),
            "--score-root",
            str(tmp_path / "scores"),
            "--output-dir",
            str(tmp_path / "aggregate"),
        ]
    )

    expected_case_ids = [
        case.case_id
        for case in sorted(
            (
                load_case(path)
                for path in (PROJECT_ROOT / "evaluation/cases").rglob("*.json")
            ),
            key=lambda case: case.case_id,
        )
        if case.kind in {"core", "variant"}
    ]
    assert exit_code == 0
    assert executed_case_ids == expected_case_ids
    assert len(executed_case_ids) == 9
