import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def write_core_m42_bundle(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "input.json": json.dumps(
            {"task_type": "observation_plan", "target": "M42"}, indent=2
        )
        + "\n",
        "result.json": json.dumps({"target": {"canonical_name": "M 42"}}) + "\n",
        "report.md": "# M42 Observation Plan\n",
        "review_checklist.md": "# Human Review\n",
        "intermediate/target_resolved.json": json.dumps(
            {"canonical_name": "M 42"}
        )
        + "\n",
        "intermediate/ephemeris.json": json.dumps({"samples": []}) + "\n",
        "intermediate/ephemeris.csv": (
            "timestamp_utc,target_altitude_deg\n2026-01-10T10:00:00+00:00,35\n"
        ),
        "intermediate/visibility.csv": (
            "timestamp_utc,is_observable\n2026-01-10T10:00:00+00:00,true\n"
        ),
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
    _write_worker_evidence(
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
    _write_worker_evidence(
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


def _write_worker_evidence(
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
    _write_text(run_dir / "response.md", "Captured worker response.\n")
    evidence_paths = {
        "stdout_file": str((run_dir / "stdout.txt").resolve()),
        "stderr_file": str((run_dir / "stderr.txt").resolve()),
        "response_file": str((run_dir / "response.md").resolve()),
    }
    _write_text(
        run_dir / "tool_calls.jsonl",
        json.dumps(
            {
                "tool": "run-starskill",
                "command": "run-starskill",
                "case_id": case_id,
                "case_kind": case_kind,
                "worker_role": worker_role,
                "task_path": str(task_path.resolve()),
                "workflow": workflow,
                "run_dir": str(run_dir.resolve()),
                "output_dir": str(run_dir.resolve()),
                "return_code": exit_code,
                **evidence_paths,
                "result": {"return_code": exit_code, "output_dir": str(run_dir.resolve()), **evidence_paths},
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
