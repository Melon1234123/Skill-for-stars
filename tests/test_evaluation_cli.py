import hashlib
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from scripts.evaluate_starskill import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_worker_evidence(
    run_dir: Path, *, exit_code: int, stderr_file: Path | None = None
) -> None:
    (run_dir / "case.json").write_text(
        (PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (run_dir / "task.json").write_text(
        (PROJECT_ROOT / "evaluation/tasks/failure-invalid-timezone.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (run_dir / "stdout.txt").write_text("", encoding="utf-8")
    if stderr_file is None:
        (run_dir / "stderr.txt").write_text("", encoding="utf-8")
    (run_dir / "exit_code.txt").write_text(f"{exit_code}\n", encoding="utf-8")
    stderr_path = stderr_file or run_dir / "stderr.txt"
    artifact_sha256 = {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    (run_dir / "execution.json").write_text(
        json.dumps(
            {
                "recorder": "starskill.evaluation.runner",
                "schema_version": 1,
                "case_id": "failure-invalid-timezone",
                "case_kind": "failure",
                "role": "teacher",
                "task_path": str((run_dir / "task.json").resolve()),
                "workflow": "validate",
                "run_dir": str(run_dir.resolve()),
                "working_directory": str(PROJECT_ROOT),
                "command_argv": [
                    str(Path(sys.executable)),
                    "-m",
                    "starskill",
                    "validate",
                    str((run_dir / "task.json").resolve()),
                ],
                "return_code": exit_code,
                "started_at": "2026-07-23T00:00:00+00:00",
                "completed_at": "2026-07-23T00:00:01+00:00",
                "stdout_file": str((run_dir / "stdout.txt").resolve()),
                "stderr_file": str(stderr_path.resolve()),
                "exit_code_file": str((run_dir / "exit_code.txt").resolve()),
                "artifact_sha256": artifact_sha256,
            },
            sort_keys=True,
        )
        + "\n", encoding="utf-8"
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
