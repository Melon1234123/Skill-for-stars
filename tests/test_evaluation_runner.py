import json
import sys
from pathlib import Path

from scripts.evaluate_starskill import main
from starskill.evaluation.runner import execute_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_execute_case_records_the_real_validate_process(tmp_path: Path) -> None:
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
    assert record.working_directory == str(PROJECT_ROOT)
    assert execution["recorder"] == "starskill.evaluation.runner"
    assert execution["return_code"] == 2
    assert execution["artifact_sha256"]["case.json"]
    assert execution["artifact_sha256"]["task.json"]
    assert (run_dir / "case.json").is_file()
    assert (run_dir / "task.json").is_file()
    assert (run_dir / "stdout.txt").read_text(encoding="utf-8") == ""
    assert "validation_error" in (run_dir / "stderr.txt").read_text(encoding="utf-8")
    assert (run_dir / "exit_code.txt").read_text(encoding="utf-8") == "2\n"
    assert not (run_dir / "tool_calls.jsonl").exists()


def test_replay_uses_a_script_owned_execution_record(tmp_path: Path) -> None:
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
    assert score["evidence_mode"] == "script_owned_engineering"
    assert score["score"]["hard_gate_passed"] is True
    assert score["score"]["base_score"] == 4


def test_replay_rejects_a_script_record_with_the_wrong_working_directory(tmp_path: Path) -> None:
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
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    execution["working_directory"] = str(tmp_path / "wrong-checkout")
    execution_path.write_text(json.dumps(execution), encoding="utf-8")

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
