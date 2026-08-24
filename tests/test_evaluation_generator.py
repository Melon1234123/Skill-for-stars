import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.evaluate_starskill import main
from starskill.evaluation.models import GeneratedEvaluationTask
from starskill.evaluation.persona_cli import main as persona_cli_main


def test_generate_command_writes_replayable_jsonl_and_manifest(tmp_path) -> None:
    output_dir = tmp_path / "generated"
    stdout = StringIO()

    with redirect_stdout(stdout):
        exit_code = main(
            [
                "generate",
                "--personas",
                "all",
                "--tasks",
                "14",
                "--seed",
                "42",
                "--output-dir",
                str(output_dir),
            ]
        )

    payload = json.loads(stdout.getvalue())
    task_lines = (output_dir / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["task_count"] == 14
    assert Path(payload["resources"]["tasks"]) == output_dir / "tasks.jsonl"
    assert len(task_lines) == 14
    assert all(GeneratedEvaluationTask.model_validate_json(line) for line in task_lines)
    assert manifest["seed"] == 42
    assert manifest["task_count"] == 14
    assert manifest["tasks_sha256"] == payload["tasks_sha256"]


def test_generate_command_refuses_to_overwrite_existing_dataset(tmp_path) -> None:
    output_dir = tmp_path / "generated"
    assert (
        main(
            [
                "generate",
                "--personas",
                "student",
                "--tasks",
                "1",
                "--seed",
                "1",
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "generate",
                "--personas",
                "student",
                "--tasks",
                "1",
                "--seed",
                "1",
                "--output-dir",
                str(output_dir),
            ]
        )

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "unsafe_output_path"


def test_starskill_eval_cli_supports_the_documented_command_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    stdout = StringIO()

    with redirect_stdout(stdout):
        exit_code = persona_cli_main(["generate", "--personas", "all", "--tasks", "7", "--seed", "42"])

    payload = json.loads(stdout.getvalue())
    expected_dir = tmp_path / "evaluation-runs" / "persona-tasks-seed-42"
    assert exit_code == 0
    assert Path(payload["output_dir"]) == expected_dir
    assert (expected_dir / "tasks.jsonl").is_file()
    assert (expected_dir / "manifest.json").is_file()
