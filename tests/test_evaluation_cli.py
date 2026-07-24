import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.evaluate_starskill as evaluation_cli
from scripts.evaluate_starskill import main
from starskill.evaluation.cases import load_case
from starskill.evaluation.models import EvaluationSummary


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_minimal_acceptance_project(root: Path) -> Path:
    fixture_root = root / "acceptance-project"
    fixture_files = (
        "evaluation/cases/generic/generic-coordinate-coordinate.json",
        "evaluation/tasks/generic-coordinate-coordinate.json",
        "evaluation/prompts/workers/outreach.md",
        "pyproject.toml",
    )
    for relative_path in fixture_files:
        destination = fixture_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((PROJECT_ROOT / relative_path).read_bytes())
    return fixture_root


def _write_worker_evidence(
    run_dir: Path, *, exit_code: int, stderr_file: Path | None = None
) -> None:
    (run_dir / "stdout.txt").write_text("", encoding="utf-8")
    (run_dir / "stderr.txt").write_text("", encoding="utf-8")
    (run_dir / "exit_code.txt").write_text(f"{exit_code}\n", encoding="utf-8")
    (run_dir / "response.md").write_text("Captured response.\n", encoding="utf-8")
    stderr_path = stderr_file or run_dir / "stderr.txt"
    evidence_paths = {
        "stdout_file": str((run_dir / "stdout.txt").resolve()),
        "stderr_file": str(stderr_path.resolve()),
        "response_file": str((run_dir / "response.md").resolve()),
    }
    (run_dir / "tool_calls.jsonl").write_text(
        json.dumps(
            {
                "tool": "run-starskill",
                "command": "run-starskill",
                "case_id": "failure-invalid-timezone",
                "case_kind": "failure",
                "worker_role": "teacher",
                "task_path": str((PROJECT_ROOT / "evaluation/tasks/failure-invalid-timezone.json").resolve()),
                "workflow": "validate",
                "run_dir": str(run_dir.resolve()),
                "output_dir": str(run_dir.resolve()),
                "return_code": exit_code,
                **evidence_paths,
                "result": {"return_code": exit_code, "output_dir": str(run_dir.resolve()), **evidence_paths},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_replay_returns_structured_error_for_oversized_top_level_bonus_json(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stderr.json").write_text(
        json.dumps({"valid": False, "error": "validation_error"}), encoding="utf-8"
    )
    _write_worker_evidence(run_dir, exit_code=2, stderr_file=run_dir / "stderr.json")
    bonus_path = tmp_path / "bonus.json"
    bonus_path.write_text('{"awarded":' + "9" * 10_000 + "}", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--stderr-file",
                str(run_dir / "stderr.json"),
                "--bonus-file",
                str(bonus_path),
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "invalid_json"


@pytest.mark.parametrize("input_flag", ["--review-file", "--escalation-file"])
def test_replay_returns_structured_error_for_oversized_review_or_escalation_json(
    tmp_path, input_flag: str
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stderr.json").write_text(
        json.dumps({"valid": False, "error": "validation_error"}), encoding="utf-8"
    )
    _write_worker_evidence(run_dir, exit_code=2, stderr_file=run_dir / "stderr.json")
    input_path = tmp_path / "input.json"
    input_path.write_text('{"value":' + "9" * 10_000 + "}", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--stderr-file",
                str(run_dir / "stderr.json"),
                input_flag,
                str(input_path),
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "invalid_json"


def test_replay_returns_structured_error_for_oversized_case_manifest(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    case_path = tmp_path / "case.json"
    case_path.write_text('{"case_id":' + "9" * 10_000 + "}", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(case_path),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "0",
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "invalid_case_manifest"


def test_aggregate_returns_structured_error_for_oversized_score_json(tmp_path) -> None:
    score_root = tmp_path / "scores"
    score_dir = score_root / "run"
    score_dir.mkdir(parents=True)
    (score_dir / "score.json").write_text('{"score":' + "9" * 10_000 + "}", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "aggregate",
                "--score-root",
                str(score_root),
                "--output-dir",
                str(tmp_path / "aggregate"),
            ]
        )

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "invalid_score_report"


def test_replay_command_writes_machine_and_score_reports(tmp_path) -> None:
    case = Path("evaluation/cases/failures/failure-invalid-timezone.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stderr.json").write_text(
        json.dumps({"valid": False, "error": "validation_error"}), encoding="utf-8"
    )
    _write_worker_evidence(run_dir, exit_code=2, stderr_file=run_dir / "stderr.json")
    (run_dir / "baseline.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_measurement",
                "metric": "runtime_seconds",
                "unit": "seconds",
                "value": 12.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "comparison.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_measurement",
                "metric": "runtime_seconds",
                "unit": "seconds",
                "value": 8.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "verification.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_verification",
                "command": "python -m pytest tests/test_evaluation_cli.py -q",
                "exit_code": 0,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    review = tmp_path / "review.json"
    bonus = tmp_path / "bonus.json"
    review.write_text(
        json.dumps(
            {
                "case_id": "failure-invalid-timezone",
                "reviewer_role": "research",
                "role_usability_points": 5,
                "safety_review_points": 6,
                "critical_issues": [],
                "issues": [],
                "confidence": 0.9,
                "recommendation": "pass",
            }
        ),
        encoding="utf-8",
    )
    bonus.write_text(
        json.dumps(
            {
                category: {
                    "awarded": awarded,
                    "evidence_paths": ["baseline.json", "comparison.json", "verification.json"],
                    "baseline": {"path": "baseline.json", "description": "baseline"},
                    "comparison": {"path": "comparison.json", "description": "comparison"},
                    "verification": {"path": "verification.json", "description": "test"},
                }
                for category, awarded in (("standardization", 3), ("acceleration", 2))
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report"

    assert (
        main(
            [
                "replay",
                "--case",
                str(case),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--stderr-file",
                str(run_dir / "stderr.json"),
                "--review-file",
                str(review),
                "--bonus-file",
                str(bonus),
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "machine_checks.json").is_file()
    assert (output / "score.json").is_file()
    assert (output / "summary.md").is_file()
    payload = json.loads((output / "score.json").read_text(encoding="utf-8"))
    assert payload["bonus"]["acceleration"]["awarded"] == 2
    assert payload["bonus"]["standardization"]["evidence_paths"] == [
        "baseline.json",
        "comparison.json",
        "verification.json",
    ]


def test_replay_command_returns_structured_error_for_missing_case_file(tmp_path) -> None:
    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(tmp_path / "missing-case.json"),
                "--run-dir",
                str(tmp_path / "run"),
                "--return-code",
                "2",
                "--output-dir",
                str(tmp_path / "report"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code != 0
    assert payload["error"] == "input_not_found"


def test_replay_command_returns_structured_error_for_malformed_reviewer_json(tmp_path) -> None:
    case = Path("evaluation/cases/failures/failure-invalid-timezone.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    review = tmp_path / "review.json"
    _write_worker_evidence(run_dir, exit_code=2)
    review.write_text("{not-json", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(case),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--review-file",
                str(review),
                "--output-dir",
                str(tmp_path / "report"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code != 0
    assert payload["error"] == "invalid_json"


def test_replay_command_rejects_output_inside_run_dir(tmp_path) -> None:
    case = Path("evaluation/cases/failures/failure-invalid-timezone.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(case),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--output-dir",
                str(run_dir / "nested-report"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code != 0
    assert payload["error"] == "unsafe_output_path"


def test_aggregate_command_rejects_malformed_score_file(tmp_path) -> None:
    score_root = tmp_path / "scores"
    run_dir = score_root / "run-a"
    run_dir.mkdir(parents=True)
    (run_dir / "score.json").write_text("{bad-json", encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "aggregate",
                "--score-root",
                str(score_root),
                "--output-dir",
                str(tmp_path / "aggregate"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code != 0
    assert payload["error"] == "invalid_score_report"


def test_aggregate_command_rejects_mixed_directory_with_incomplete_run(tmp_path) -> None:
    score_root = tmp_path / "scores"
    complete = score_root / "complete"
    incomplete = score_root / "incomplete"
    complete.mkdir(parents=True)
    incomplete.mkdir(parents=True)
    (complete / "score.json").write_text(
        json.dumps(
            {
                "run_id": "complete",
                "run_dir": str(complete),
                "score": {
                    "case_id": "core-m42",
                    "case_kind": "core",
                    "hard_gate_passed": True,
                    "base_score": 100,
                    "bonus_score": 0,
                    "total_score": 100,
                    "dimensions": {
                        "closed_loop": 40,
                        "scientific_correctness": 25,
                        "reproducibility": 20,
                        "error_and_safety": 10,
                        "role_usability": 5,
                    },
                    "issues": [],
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (incomplete / "machine_checks.json").write_text(
        json.dumps({"case_id": "core-broken"}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "aggregate",
                "--score-root",
                str(score_root),
                "--output-dir",
                str(tmp_path / "aggregate"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code != 0
    assert payload["error"] == "incomplete_score_report"
    assert not (tmp_path / "aggregate" / "summary.json").exists()


def test_replay_command_returns_structured_error_for_non_utf8_stderr_file(tmp_path) -> None:
    case = Path("evaluation/cases/failures/failure-invalid-timezone.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stderr.bin").write_bytes(b"\xff\xfe\x00")
    _write_worker_evidence(run_dir, exit_code=2, stderr_file=run_dir / "stderr.bin")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(case),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--stderr-file",
                str(run_dir / "stderr.bin"),
                "--output-dir",
                str(tmp_path / "report"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code != 0
    assert payload["error"] == "input_read_error"


def test_help_lists_bonus_file_option() -> None:
    stdout = StringIO()
    with redirect_stdout(stdout):
        try:
            main(["replay", "--help"])
        except SystemExit:
            pass

    assert "--bonus-file" in stdout.getvalue()


def test_execute_command_reports_a_script_owned_record(tmp_path, monkeypatch) -> None:
    run_dir = tmp_path / "run"

    def fake_execute(_case_path, captured_run_dir, **_kwargs):
        captured_run_dir.mkdir(parents=True)
        return SimpleNamespace(
            case_id="failure-invalid-timezone",
            return_code=2,
            run_dir=str(captured_run_dir.resolve()),
        )

    monkeypatch.setattr(evaluation_cli, "execute_case", fake_execute)
    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = evaluation_cli.main(
            [
                "execute",
                "--case",
                str(PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"),
                "--run-dir",
                str(run_dir),
            ]
        )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload == {
        "case_id": "failure-invalid-timezone",
        "execution_file": str((run_dir / "execution.json").resolve()),
        "ok": True,
        "return_code": 2,
        "run_dir": str(run_dir.resolve()),
    }


def test_acceptance_repeats_cores_and_runs_each_variant_once(tmp_path, monkeypatch) -> None:
    executed: list[tuple[str, Path]] = []
    replayed_score_dirs: list[Path] = []

    def fake_execute(case_path, run_dir, **_kwargs):
        case = load_case(case_path)
        executed.append((case.case_id, run_dir))
        if case.workflow == "fetch-image":
            cache_dir = _kwargs["image_cache_dir"]
            cache_files = sorted(path.suffix for path in cache_dir.iterdir())
            assert cache_files == [".jpg", ".json"]
        if case.workflow == "run":
            cache_dir = _kwargs["target_cache_dir"]
            assert [path.suffix for path in cache_dir.iterdir()] == [".json"]
        if case.case_id in {"generic-mars-m31", "generic-m31-coordinate"}:
            cache_dir = _kwargs["target_cache_dir"]
            assert [path.suffix for path in cache_dir.iterdir()] == [".json"]
        run_dir.mkdir(parents=True)
        return SimpleNamespace(
            case_id=case.case_id,
            return_code=case.expected_exit_code,
            run_dir=str(run_dir),
            artifact_sha256={"task.json": "0" * 64},
        )

    summary = EvaluationSummary(
        total_runs=19,
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

    def fake_replay(args):
        args.output_dir.mkdir(parents=True)
        replayed_score_dirs.append(args.output_dir.resolve())
        return 0

    monkeypatch.setattr(evaluation_cli, "_replay", fake_replay)
    monkeypatch.setattr(evaluation_cli, "collect_score_reports", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(evaluation_cli, "aggregate_scores", lambda _bundles: summary)
    monkeypatch.setattr(
        evaluation_cli,
        "write_aggregate_reports",
        lambda _summary, _bundles, output_dir: (output_dir / "summary.json").write_text("{}"),
    )

    run_root = tmp_path / "runs"
    score_root = tmp_path / "scores"
    aggregate_root = tmp_path / "aggregate"
    exit_code = evaluation_cli.main(
        [
            "acceptance",
            "--run-root",
            str(run_root),
            "--score-root",
            str(score_root),
            "--output-dir",
            str(aggregate_root),
        ]
    )

    cases = [
        load_case(path)
        for path in sorted((PROJECT_ROOT / "evaluation/cases").rglob("*.json"))
    ]
    expected_counts = {
        case.case_id: 3 if case.kind == "core" else 1
        for case in cases
        if case.kind in {"core", "variant"}
    }
    actual_counts = {case_id: sum(case_id == observed for observed, _run_dir in executed) for case_id in expected_counts}
    assert exit_code == 0
    assert actual_counts == expected_counts
    assert len({run_dir for _case_id, run_dir in executed}) == 19
    assert all(path.is_relative_to(run_root.resolve()) for _case_id, path in executed)
    assert len(replayed_score_dirs) == 19
    assert all(path.is_relative_to(score_root.resolve()) for path in replayed_score_dirs)
    assert (aggregate_root / "summary.json").is_file()
    assert (aggregate_root / "acceptance.json").is_file()
    assert not (aggregate_root / "reports").exists()


def test_acceptance_accepts_output_root_without_explicit_run_or_score_roots(
    tmp_path, monkeypatch
) -> None:
    fixture_root = _write_minimal_acceptance_project(tmp_path)
    monkeypatch.setattr(
        evaluation_cli,
        "__file__",
        str(fixture_root / "scripts" / "evaluate_starskill.py"),
    )
    monkeypatch.setenv("PYTHONPATH", str(PROJECT_ROOT / "src"))

    output_root = tmp_path / "generalized-targets"
    exit_code = evaluation_cli.main(["acceptance", "--output-dir", str(output_root)])

    run_dir = output_root / "runs" / "generic-coordinate-coordinate" / "recorded-01"
    score_dir = output_root / "scores" / "generic-coordinate-coordinate" / "recorded-01"
    reports_dir = output_root / "reports"
    execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    score = json.loads((score_dir / "score.json").read_text(encoding="utf-8"))
    summary = json.loads((reports_dir / "summary.json").read_text(encoding="utf-8"))
    acceptance = json.loads((reports_dir / "acceptance.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert (output_root / "runs").is_dir()
    assert (output_root / "scores").is_dir()
    assert execution["recorder"] == "starskill.evaluation.runner"
    assert execution["return_code"] == 0
    assert execution["command_argv"][1:4] == ["-m", "starskill", "relationship"]
    assert execution["artifact_sha256"]["relationship.csv"]
    assert execution["artifact_sha256"]["relationship.json"]
    assert (run_dir / "stdout.txt").is_file()
    assert (run_dir / "stderr.txt").read_text(encoding="utf-8") == ""
    assert (run_dir / "exit_code.txt").read_text(encoding="utf-8") == "0\n"
    assert score["evidence_mode"] == "script_owned_engineering"
    assert score["score"]["hard_gate_passed"] is True
    assert score["raw_inputs"]["execution_file"] == str((run_dir / "execution.json").resolve())
    assert summary["total_runs"] == 1
    assert summary["passed"] is True
    assert (reports_dir / "summary.md").is_file()
    assert acceptance["run_root"] == str((output_root / "runs").resolve())
    assert acceptance["score_root"] == str((output_root / "scores").resolve())
    assert acceptance["output_dir"] == str(reports_dir.resolve())
    assert acceptance["runs"] == [
        {
            "artifact_sha256": execution["artifact_sha256"],
            "case_id": "generic-coordinate-coordinate",
            "execution_file": str((run_dir / "execution.json").resolve()),
            "replay_exit_code": 0,
            "return_code": 0,
            "run_dir": str(run_dir.resolve()),
            "run_name": "recorded-01",
            "score_dir": str(score_dir.resolve()),
        }
    ]
