import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def write_core_m42_bundle(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "input.json": (PROJECT_ROOT / "examples" / "observation_m42_beijing.json").read_text(
            encoding="utf-8"
        ),
        "result.json": json.dumps({"target": {"canonical_name": "M 42"}}) + "\n",
        "report.md": "# M42 observation plan\n",
        "review_checklist.md": "# Human review\n",
        "intermediate/target_resolved.json": json.dumps(
            {"canonical_name": "M 42"}
        )
        + "\n",
        "intermediate/ephemeris.json": json.dumps({"samples": []}) + "\n",
        "intermediate/ephemeris.csv": "time_utc,target_altitude_deg\n2026-01-10T10:00:00+00:00,35\n",
        "intermediate/visibility.csv": "time_utc,visible\n2026-01-10T10:00:00+00:00,true\n",
        "stdout.json": json.dumps(
            {"status": "success", "output_dir": str(run_dir)}, ensure_ascii=False, indent=2
        )
        + "\n",
        "stderr.txt": "",
    }
    for relative_path, content in artifacts.items():
        _write_text(run_dir / relative_path, content)

    _write_fixed_png(run_dir / "figures" / "visibility_curve.png")
    _write_run_json(
        run_dir,
        status="success",
        issues=[],
        started_at="2026-07-19T10:18:36+00:00",
        completed_at="2026-07-19T10:18:37+00:00",
    )
    _write_execution_record(
        run_dir,
        exit_code=0,
        case_id="core-m42-beijing",
        case_kind="core",
        worker_role="teacher",
        task_path=PROJECT_ROOT / "examples/observation_m42_beijing.json",
        workflow="run",
    )


def write_variant_m42_no_window_bundle(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_text(
        run_dir / "result.json",
        json.dumps(
            {
                "target": {"canonical_name": "M 42"},
                "windows": [],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write_text(
        run_dir / "stdout.json",
        json.dumps(
            {
                "status": "success",
                "output_dir": str(run_dir),
                "message": "No valid observation window found.",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    _write_text(run_dir / "stderr.txt", "")
    _write_run_json(
        run_dir,
        status="success",
        issues=[],
        started_at="2026-07-19T10:18:36+00:00",
        completed_at="2026-07-19T10:18:37+00:00",
    )
    _write_execution_record(
        run_dir,
        exit_code=0,
        case_id="variant-m42-no-window",
        case_kind="variant",
        worker_role="teacher",
        task_path=PROJECT_ROOT / "evaluation/tasks/variant-m42-no-window.json",
        workflow="run",
    )


def write_review_report(
    path: Path,
    *,
    case_id: str,
    reviewer_role: str,
    role_usability_points: float,
    safety_review_points: float,
    issues: list[str] | None = None,
    critical_issues: list[str] | None = None,
) -> None:
    _write_text(
        path,
        json.dumps(
            {
                "case_id": case_id,
                "reviewer_role": reviewer_role,
                "role_usability_points": role_usability_points,
                "safety_review_points": safety_review_points,
                "critical_issues": critical_issues or [],
                "issues": issues or [],
                "confidence": 0.95,
                "recommendation": "pass",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _write_run_json(
    run_dir: Path,
    *,
    status: str,
    issues: list[dict[str, object]],
    started_at: str,
    completed_at: str,
) -> None:
    artifact_paths = sorted(
        path.relative_to(run_dir).as_posix()
        for path in run_dir.rglob("*")
        if path.is_file() and path.name != "run.json"
    )
    payload = {
        "run_id": run_dir.name,
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "artifacts": [_artifact_record(run_dir, relative_path) for relative_path in artifact_paths],
        "issues": issues,
    }
    _write_text(
        run_dir / "run.json",
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _artifact_record(run_dir: Path, relative_path: str) -> dict[str, object]:
    content = (run_dir / relative_path).read_bytes()
    return {
        "path": relative_path,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_execution_record(
    run_dir: Path,
    *,
    exit_code: int,
    case_id: str,
    case_kind: str,
    worker_role: str,
    task_path: Path,
    workflow: str,
) -> None:
    _write_text(run_dir / "stdout.txt", (run_dir / "stdout.json").read_text(encoding="utf-8"))
    _write_text(run_dir / "stderr.txt", "")
    _write_text(run_dir / "exit_code.txt", f"{exit_code}\n")
    case_path = next(
        (PROJECT_ROOT / "evaluation" / "cases" / kind / f"{case_id}.json")
        for kind in ("core", "variants", "failures", "open")
        if (PROJECT_ROOT / "evaluation" / "cases" / kind / f"{case_id}.json").is_file()
    )
    _write_text(run_dir / "case.json", case_path.read_text(encoding="utf-8"))
    _write_text(run_dir / "task.json", task_path.read_text(encoding="utf-8"))
    task_copy = (run_dir / "task.json").resolve()
    if workflow == "validate":
        command_argv = [str(PROJECT_ROOT / ".venv/bin/python"), "-m", "starskill", workflow, str(task_copy)]
    elif workflow == "run":
        command_argv = [
            str(PROJECT_ROOT / ".venv/bin/python"), "-m", "starskill", workflow, str(task_copy),
            "--output-dir", str(run_dir.resolve()), "--cache-dir", str((PROJECT_ROOT / "cache/targets").resolve()),
        ]
    else:
        raise AssertionError(f"fixture does not support workflow {workflow}")
    artifact_sha256 = {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file()
    }
    _write_text(
        run_dir / "execution.json",
        json.dumps(
            {
                "recorder": "starskill.evaluation.runner",
                "schema_version": 1,
                "case_id": case_id,
                "case_kind": case_kind,
                "role": worker_role,
                "task_path": str(task_copy),
                "workflow": workflow,
                "run_dir": str(run_dir.resolve()),
                "working_directory": str(PROJECT_ROOT),
                "command_argv": command_argv,
                "return_code": exit_code,
                "started_at": "2026-07-23T00:00:00+00:00",
                "completed_at": "2026-07-23T00:00:01+00:00",
                "stdout_file": str((run_dir / "stdout.txt").resolve()),
                "stderr_file": str((run_dir / "stderr.txt").resolve()),
                "exit_code_file": str((run_dir / "exit_code.txt").resolve()),
                "artifact_sha256": artifact_sha256,
            },
            sort_keys=True,
        )
        + "\n",
    )


def _write_fixed_png(path: Path) -> None:
    image = Image.new("RGB", (256, 192))
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), ((x * 5) % 256, (y * 7) % 256, ((x + y) * 11) % 256))
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
