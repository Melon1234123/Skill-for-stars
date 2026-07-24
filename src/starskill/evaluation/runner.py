"""Execute an evaluation case and record the real CLI process evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from starskill.evaluation.cases import load_case
from starskill.evaluation.models import EvaluationCase, ExecutionRecord


class ExecutionError(ValueError):
    """Raised when a case cannot be captured in a fresh run directory."""


def execute_case(
    case_path: Path,
    run_dir: Path,
    *,
    python_executable: Path,
    target_cache_dir: Path,
    image_cache_dir: Path,
    source_path: Path | None = None,
) -> ExecutionRecord:
    """Run one case in a new directory and write script-owned evidence."""
    source_case_path = case_path.resolve()
    case = load_case(source_case_path)
    run_dir = run_dir.resolve()
    _prepare_run_directory(run_dir)

    captured_case_path = run_dir / "case.json"
    captured_task_path = run_dir / "task.json"
    shutil.copyfile(source_case_path, captured_case_path)
    shutil.copyfile(case.task_path, captured_task_path)

    project_root = _project_root_from_case_path(source_case_path)
    source_path = (source_path or project_root / "src").resolve()
    if not source_path.is_dir():
        raise ExecutionError(f"source path must be an existing directory: {source_path}")
    environment = os.environ.copy()
    inherited_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(source_path)
        if not inherited_pythonpath
        else os.pathsep.join((str(source_path), inherited_pythonpath))
    )
    command_argv = build_case_command(
        case,
        task_path=captured_task_path,
        run_dir=run_dir,
        python_executable=python_executable.absolute(),
        target_cache_dir=target_cache_dir.resolve(),
        image_cache_dir=image_cache_dir.resolve(),
    )
    started_at = _utc_now()
    completed = subprocess.run(
        command_argv,
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    completed_at = _utc_now()

    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    exit_code_path = run_dir / "exit_code.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    exit_code_path.write_text(f"{completed.returncode}\n", encoding="utf-8")

    record = ExecutionRecord(
        recorder="starskill.evaluation.runner",
        schema_version=1,
        case_id=case.case_id,
        case_kind=case.kind,
        role=case.role,
        workflow=case.workflow,
        task_path=str(captured_task_path),
        run_dir=str(run_dir),
        working_directory=str(project_root),
        source_path=str(source_path),
        environment={"PYTHONPATH": environment["PYTHONPATH"]},
        command_argv=command_argv,
        return_code=completed.returncode,
        started_at=started_at,
        completed_at=completed_at,
        stdout_file=str(stdout_path),
        stderr_file=str(stderr_path),
        exit_code_file=str(exit_code_path),
        artifact_sha256=_artifact_hashes(run_dir),
    )
    (run_dir / "execution.json").write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return record


def build_case_command(
    case: EvaluationCase,
    *,
    task_path: Path,
    run_dir: Path,
    python_executable: Path,
    target_cache_dir: Path,
    image_cache_dir: Path,
) -> list[str]:
    """Build the exact supported CLI argv for a captured evaluation case."""
    command = [str(python_executable), "-m", "starskill", case.workflow, str(task_path)]
    if case.workflow == "validate":
        return command
    if case.workflow == "run":
        return [*command, "--output-dir", str(run_dir), "--cache-dir", str(target_cache_dir)]
    if case.workflow == "relationship":
        return [
            *command,
            "--output",
            str(run_dir / "relationship.csv"),
            "--metadata",
            str(run_dir / "relationship.json"),
            "--cache-dir",
            str(target_cache_dir),
        ]
    if case.workflow == "fetch-image":
        return [*command, "--output-dir", str(run_dir), "--cache-dir", str(image_cache_dir)]
    raise ExecutionError(f"automatic capture does not support the {case.workflow!r} workflow")


def _prepare_run_directory(run_dir: Path) -> None:
    if run_dir.exists():
        if not run_dir.is_dir() or any(run_dir.iterdir()):
            raise ExecutionError(f"run directory must be new and empty: {run_dir}")
    else:
        run_dir.mkdir(parents=True)


def _artifact_hashes(run_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.name != "execution.json"
    }


def _project_root_from_case_path(case_path: Path) -> Path:
    """Resolve the checkout root without relying on the installed package path."""
    try:
        project_root = case_path.parents[3]
    except IndexError as exc:
        raise ExecutionError(
            f"case path must be under <project>/evaluation/cases: {case_path}"
        ) from exc
    if not (project_root / "pyproject.toml").is_file():
        raise ExecutionError(
            f"case path must be under <project>/evaluation/cases: {case_path}"
        )
    return project_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
