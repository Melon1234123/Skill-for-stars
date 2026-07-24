"""Offline report serialization helpers for StarSkill evaluation replay."""

from __future__ import annotations

import json
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from starskill.evaluation.cases import load_cases
from starskill.evaluation.checks import check_run
from starskill.evaluation.models import EvaluationCase, EvaluationSummary, ExecutionRecord, MachineCheckReport, ReviewReport, ScoreReport
from starskill.evaluation.scoring import BonusEvidence, aggregate_scores, score_case


class ReportError(Exception):
    """Structured reporting error."""

    def __init__(self, code: str, message: str, *, details: object | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class RawRunInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_code: int
    stdout: str = ""
    stderr: str = ""
    stdout_file: str | None = None
    stderr_file: str | None = None
    exit_code_file: str | None = None
    tool_calls_file: str | None = None
    response_file: str | None = None
    execution_file: str | None = None


@dataclass(frozen=True)
class ExecutionEvidence:
    role: str
    return_code: int
    stdout_file: Path
    stderr_file: Path
    execution_file: Path | None


_EXECUTION_RECORD_FIELDS = {
    "tool", "command", "case_id", "case_kind", "worker_role", "task_path", "workflow",
    "run_dir", "output_dir", "return_code", "stdout_file", "stderr_file", "response_file", "result",
}

NORMAL_REVIEWER_BY_WORKER_ROLE = {
    "teacher": "research",
    "outreach": "teacher",
    "research": "outreach",
}


class ScoreBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    run_dir: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    case_kind: Literal["core", "variant", "failure", "open"]
    worker_role: Literal["teacher", "outreach", "research"] = "teacher"
    machine_checks_path: str = Field(min_length=1)
    summary_path: str = Field(min_length=1)
    raw_inputs: RawRunInputs
    review: dict[str, object] | None
    bonus: dict[str, object] = Field(default_factory=dict)
    score: ScoreReport
    evidence_mode: Literal["external_worker", "script_owned_engineering"] = "external_worker"
    review_path: str | None = None
    review_sha256: str | None = None
    escalation: dict[str, object] | None = None
    escalation_path: str | None = None
    escalation_sha256: str | None = None


def write_case_reports(
    *,
    case: EvaluationCase,
    run_dir: Path,
    return_code: int,
    stdout_text: str,
    stderr_text: str,
    review: ReviewReport | None,
    score: ScoreReport,
    machine: MachineCheckReport,
    output_dir: Path,
    stdout_file: Path | None = None,
    stderr_file: Path | None = None,
    execution_file: Path | None = None,
    bonus: dict[str, object] | None = None,
    review_file: Path | None = None,
    worker_role: str | None = None,
    evidence_mode: Literal["external_worker", "script_owned_engineering"] = "external_worker",
    escalation: dict[str, object] | None = None,
    escalation_file: Path | None = None,
) -> ScoreBundle:
    output_dir = output_dir.resolve()
    run_dir = run_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    machine_path = output_dir / "machine_checks.json"
    score_path = output_dir / "score.json"
    summary_path = output_dir / "summary.md"
    raw_inputs = RawRunInputs(
        return_code=return_code,
        stdout=stdout_text,
        stderr=stderr_text,
        stdout_file=str(stdout_file.resolve()) if stdout_file is not None else None,
        stderr_file=str(stderr_file.resolve()) if stderr_file is not None else None,
        exit_code_file=str((run_dir / "exit_code.txt").resolve()),
        tool_calls_file=(
            None if execution_file is not None else str((run_dir / "tool_calls.jsonl").resolve())
        ),
        response_file=(
            None if execution_file is not None else str((run_dir / "response.md").resolve())
        ),
        execution_file=str(execution_file.resolve()) if execution_file is not None else None,
    )

    _write_json(
        machine_path,
        {
            "case": case.model_dump(mode="json"),
            "run": {
                "run_id": run_dir.name,
                "run_dir": str(run_dir),
                **raw_inputs.model_dump(mode="json"),
            },
            "machine_check": machine.model_dump(mode="json"),
        },
    )

    bundle = ScoreBundle(
        run_id=run_dir.name,
        run_dir=str(run_dir),
        case_id=case.case_id,
        case_kind=case.kind,
        worker_role=worker_role or case.role,
        machine_checks_path=str(machine_path),
        summary_path=str(summary_path),
        raw_inputs=raw_inputs,
        review=review.model_dump(mode="json") if review is not None else None,
        bonus=dict(sorted((bonus or {}).items())),
        score=score,
        evidence_mode=evidence_mode,
        review_path=str(review_file.resolve()) if review_file is not None else None,
        review_sha256=_file_sha256(review_file) if review_file is not None else None,
        escalation=escalation,
        escalation_path=str(escalation_file.resolve()) if escalation_file is not None else None,
        escalation_sha256=_file_sha256(escalation_file) if escalation_file is not None else None,
    )
    _write_json(score_path, bundle.model_dump(mode="json"))
    summary_path.write_text(
        _render_case_summary(case, machine, review, score, bundle), encoding="utf-8"
    )
    return bundle


def collect_score_reports(score_root: Path, *, cases_root: Path | None = None) -> list[ScoreBundle]:
    score_root = score_root.resolve()
    if not score_root.exists() or not score_root.is_dir():
        raise ReportError("input_not_found", f"score root does not exist: {score_root}")

    _reject_incomplete_report_dirs(score_root)
    score_paths = sorted(score_root.rglob("score.json"))
    if not score_paths:
        raise ReportError("input_not_found", f"no score.json files found under {score_root}")

    bundles: list[ScoreBundle] = []
    seen_physical_runs: set[tuple[str, str]] = set()
    canonical_cases = (
        {case.case_id: case for case in load_cases(cases_root)} if cases_root is not None else {}
    )
    for path in score_paths:
        bundle = _load_score_bundle(path)
        _validate_bundle_consistency(bundle, path)
        _validate_bundle_references(bundle, path)
        physical_run = (bundle.case_id, str(Path(bundle.run_dir).resolve()))
        if physical_run in seen_physical_runs:
            raise ReportError(
                "duplicate_score_report",
                "duplicate physical case run detected during aggregation",
                details={"case_id": bundle.case_id, "run_dir": physical_run[1], "path": str(path)},
            )
        seen_physical_runs.add(physical_run)
        if canonical_cases:
            _validate_bundle_against_evidence(bundle, path, canonical_cases)
        bundles.append(bundle)
    if canonical_cases:
        _validate_case_matrix(bundles, canonical_cases)
    return bundles


def write_aggregate_reports(
    summary: EvaluationSummary,
    bundles: list[ScoreBundle],
    output_dir: Path,
) -> None:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "summary.json", summary.model_dump(mode="json"))
    (output_dir / "summary.md").write_text(
        _render_aggregate_summary(summary, bundles),
        encoding="utf-8",
    )


def _validate_bundle_against_evidence(
    bundle: ScoreBundle, score_path: Path, canonical_cases: dict[str, EvaluationCase]
) -> None:
    case = canonical_cases.get(bundle.case_id)
    if case is None or case.kind != bundle.case_kind:
        raise ReportError("invalid_score_report", f"unknown or mismatched canonical case: {bundle.case_id}")
    if bundle.worker_role != case.role:
        raise ReportError("invalid_worker_role", "score bundle worker role does not match the canonical case role")
    run_dir = Path(bundle.run_dir).resolve()
    machine_path = _resolve_reference_path(score_path, bundle.machine_checks_path, "machine_checks_path")
    machine_payload = _load_json_object(machine_path, "machine_checks_path")
    if machine_payload.get("case") != case.model_dump(mode="json"):
        raise ReportError("evidence_mismatch", "captured case manifest differs from canonical manifest")
    machine_run = machine_payload.get("run")
    machine_report = machine_payload.get("machine_check")
    if not isinstance(machine_run, dict) or not isinstance(machine_report, dict):
        raise ReportError("invalid_score_report", "machine_checks.json is missing run or machine_check data")
    if machine_run.get("run_id") != bundle.run_id or machine_run.get("run_dir") != str(run_dir):
        raise ReportError("evidence_mismatch", "machine check run identity differs from score bundle")
    expected_machine_run = {
        "run_id": bundle.run_id,
        "run_dir": str(run_dir),
        **bundle.raw_inputs.model_dump(mode="json"),
    }
    if machine_run != expected_machine_run:
        raise ReportError("evidence_mismatch", "machine check run data differs from score bundle raw inputs")
    _validate_evidence_mode(bundle)
    _validate_raw_evidence(bundle, case, run_dir)
    try:
        recorded_machine = MachineCheckReport.model_validate(machine_report)
    except ValidationError as exc:
        raise ReportError("invalid_score_report", "machine check did not match required schema", details=exc.errors()) from exc
    rederived_machine = check_run(
        case,
        run_dir,
        bundle.raw_inputs.return_code,
        bundle.raw_inputs.stdout,
        bundle.raw_inputs.stderr,
    )
    if recorded_machine != rederived_machine:
        raise ReportError("evidence_mismatch", "machine_checks.json does not match replayed evidence")
    review = _validate_review(bundle, case, rederived_machine)
    _validate_bonus_evidence(bundle.bonus, run_dir, case)
    try:
        rederived_score = score_case(
            rederived_machine,
            review,
            bundle.bonus,
            script_owned_engineering=bundle.evidence_mode == "script_owned_engineering",
        )
    except (ValidationError, ValueError) as exc:
        raise ReportError("invalid_score_report", "bonus evidence did not match required schema", details=str(exc)) from exc
    if bundle.score != rederived_score:
        raise ReportError("evidence_mismatch", "score.json does not match machine, review, and bonus evidence")


def _validate_evidence_mode(bundle: ScoreBundle) -> None:
    script_owned = bundle.evidence_mode == "script_owned_engineering"
    if script_owned:
        if bundle.raw_inputs.execution_file is None:
            raise ReportError(
                "evidence_mismatch",
                "script-owned engineering score bundles require execution.json evidence",
            )
        if any(
            (
                bundle.review is not None,
                bundle.review_path is not None,
                bundle.review_sha256 is not None,
                bundle.escalation is not None,
                bundle.escalation_path is not None,
                bundle.escalation_sha256 is not None,
            )
        ):
            raise ReportError(
                "evidence_mismatch",
                "script-owned engineering score bundles cannot include reviewer evidence",
            )
        if bundle.bonus:
            raise ReportError(
                "evidence_mismatch",
                "script-owned engineering score bundles cannot include bonus evidence",
            )
        return
    if bundle.raw_inputs.execution_file is not None:
        raise ReportError(
            "evidence_mismatch",
            "external Worker score bundles cannot use script-owned execution evidence",
        )


def _validate_raw_evidence(bundle: ScoreBundle, case: EvaluationCase, run_dir: Path) -> None:
    raw = bundle.raw_inputs
    if raw.execution_file is not None:
        evidence = validate_execution_evidence(case, run_dir)
        if evidence.execution_file is None:
            raise ReportError("evidence_mismatch", "script-owned execution evidence was not recovered")
        if (
            evidence.return_code != raw.return_code
            or evidence.stdout_file != _resolve_run_evidence_path(run_dir, raw.stdout_file, "stdout_file")
            or evidence.stderr_file != _resolve_run_evidence_path(run_dir, raw.stderr_file, "stderr_file")
            or evidence.execution_file != _resolve_run_evidence_path(run_dir, raw.execution_file, "execution_file")
        ):
            raise ReportError("evidence_mismatch", "score bundle differs from script-owned execution evidence")
        return
    paths = {
        "stdout_file": raw.stdout_file,
        "stderr_file": raw.stderr_file,
        "exit_code_file": raw.exit_code_file,
        "tool_calls_file": raw.tool_calls_file,
        "response_file": raw.response_file,
    }
    resolved = {name: _resolve_run_evidence_path(run_dir, path, name) for name, path in paths.items()}
    try:
        if resolved["stdout_file"].read_text(encoding="utf-8") != raw.stdout:
            raise ReportError("evidence_mismatch", "captured stdout differs from score bundle")
        if resolved["stderr_file"].read_text(encoding="utf-8") != raw.stderr:
            raise ReportError("evidence_mismatch", "captured stderr differs from score bundle")
        if int(resolved["exit_code_file"].read_text(encoding="utf-8").strip()) != raw.return_code:
            raise ReportError("evidence_mismatch", "captured exit code differs from score bundle")
        _validate_tool_call_records(
            resolved["tool_calls_file"],
            case,
            run_dir,
            raw.return_code,
            bundle.worker_role,
            resolved,
            canonical_worker_role=case.role,
        )
        if not resolved["response_file"].read_text(encoding="utf-8").strip():
            raise ValueError("response.md must not be empty")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ReportError):
            raise
        raise ReportError("invalid_execution_evidence", "captured worker evidence is invalid", details=str(exc)) from exc


def validate_execution_evidence(
    case: EvaluationCase,
    run_dir: Path,
    return_code: int | None = None,
    stdout_file: Path | None = None,
    stderr_file: Path | None = None,
) -> ExecutionEvidence:
    execution_file = run_dir / "execution.json"
    if execution_file.is_file():
        return _validate_script_execution_record(case, run_dir, execution_file)
    if return_code is None or stdout_file is None or stderr_file is None:
        raise ReportError(
            "invalid_execution_evidence",
            "external Worker evidence requires --return-code, stdout, and stderr paths",
        )
    raw = RawRunInputs(
        return_code=return_code,
        stdout_file=str(stdout_file.resolve()),
        stderr_file=str(stderr_file.resolve()),
        exit_code_file=str((run_dir / "exit_code.txt").resolve()),
        tool_calls_file=str((run_dir / "tool_calls.jsonl").resolve()),
        response_file=str((run_dir / "response.md").resolve()),
    )
    paths = {
        "stdout_file": raw.stdout_file,
        "stderr_file": raw.stderr_file,
        "exit_code_file": raw.exit_code_file,
        "tool_calls_file": raw.tool_calls_file,
        "response_file": raw.response_file,
    }
    resolved = {name: _resolve_run_evidence_path(run_dir, path, name) for name, path in paths.items()}
    try:
        if int(resolved["exit_code_file"].read_text(encoding="utf-8").strip()) != return_code:
            raise ReportError("invalid_execution_evidence", "--return-code does not match captured exit_code.txt")
        if not resolved["response_file"].read_text(encoding="utf-8").strip():
            raise ReportError("invalid_execution_evidence", "response.md must not be empty")
        role = _validate_tool_call_records(
            resolved["tool_calls_file"], case, run_dir, return_code, None, resolved
        )
        return ExecutionEvidence(
            role=role,
            return_code=return_code,
            stdout_file=resolved["stdout_file"],
            stderr_file=resolved["stderr_file"],
            execution_file=None,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ReportError("invalid_execution_evidence", "captured worker evidence is invalid", details=str(exc)) from exc


def _validate_script_execution_record(
    case: EvaluationCase, run_dir: Path, execution_file: Path
) -> ExecutionEvidence:
    try:
        payload = _load_json_object(execution_file, "execution_file")
        record = ExecutionRecord.model_validate(payload)
        resolved_execution = _resolve_run_evidence_path(run_dir, str(execution_file.resolve()), "execution_file")
        expected_task = (run_dir / "task.json").resolve()
        expected_case = (run_dir / "case.json").resolve()
        expected_working_directory = _project_root_for_task_path(Path(case.task_path))
        stdout_file = _resolve_run_evidence_path(run_dir, record.stdout_file, "stdout_file")
        stderr_file = _resolve_run_evidence_path(run_dir, record.stderr_file, "stderr_file")
        exit_code_file = _resolve_run_evidence_path(run_dir, record.exit_code_file, "exit_code_file")
        if (
            record.case_id != case.case_id
            or record.case_kind != case.kind
            or record.role != case.role
            or record.workflow != case.workflow
            or Path(record.run_dir).resolve() != run_dir.resolve()
            or Path(record.task_path).resolve() != expected_task
            or Path(record.working_directory).resolve() != expected_working_directory
        ):
            raise ValueError("execution.json identity does not match the declared case")
        captured_case = _load_json_object(expected_case, "case.json")
        if any(
            captured_case.get(field) != getattr(case, field)
            for field in ("case_id", "kind", "role", "workflow", "expected_exit_code", "expected_status")
        ):
            raise ValueError("captured case.json identity does not match the canonical case")
        if not expected_task.is_file() or expected_task.read_bytes() != Path(case.task_path).read_bytes():
            raise ValueError("captured task.json does not match the canonical task")
        _validate_script_command(record, case, expected_task, run_dir)
        if int(exit_code_file.read_text(encoding="utf-8").strip()) != record.return_code:
            raise ValueError("execution.json return_code does not match exit_code.txt")
        actual_hashes = _artifact_hashes(run_dir)
        if record.artifact_sha256 != actual_hashes:
            raise ValueError("execution.json artifact hashes do not match captured files")
        return ExecutionEvidence(
            role=record.role,
            return_code=record.return_code,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            execution_file=resolved_execution,
        )
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise ReportError("invalid_execution_evidence", "script-owned execution evidence is invalid", details=str(exc)) from exc


def _project_root_for_task_path(task_path: Path) -> Path:
    for candidate in task_path.resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ValueError(f"canonical task path is outside a project checkout: {task_path}")


def _validate_script_command(
    record: ExecutionRecord, case: EvaluationCase, task_path: Path, run_dir: Path
) -> None:
    command = record.command_argv
    if command[:4] != [command[0], "-m", "starskill", case.workflow] or command[4] != str(task_path):
        raise ValueError("execution.json command does not invoke the captured case task")
    if case.workflow == "validate" and len(command) == 5:
        return
    if case.workflow == "run" and len(command) == 9 and command[5:7] == ["--output-dir", str(run_dir)] and command[7] == "--cache-dir":
        return
    if case.workflow == "relationship" and command[5:] == [
        "--output", str(run_dir / "relationship.csv"), "--metadata", str(run_dir / "relationship.json")
    ]:
        return
    if case.workflow == "fetch-image" and len(command) == 9 and command[5:7] == ["--output-dir", str(run_dir)] and command[7] == "--cache-dir":
        return
    raise ValueError("execution.json command does not match the supported workflow contract")


def _artifact_hashes(run_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.name != "execution.json"
    }


def _validate_tool_call_records(
    path: Path,
    case: EvaluationCase,
    run_dir: Path,
    return_code: int,
    worker_role: str | None,
    evidence_paths: dict[str, Path],
    *,
    canonical_worker_role: str | None = None,
) -> str:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError("tool_calls.jsonl must contain one declared run-starskill invocation")
    roles: set[str] = set()
    expected_paths = {
        "stdout_file": str(evidence_paths["stdout_file"]),
        "stderr_file": str(evidence_paths["stderr_file"]),
        "response_file": str(evidence_paths["response_file"]),
    }
    for line in lines:
        record = json.loads(line)
        if not isinstance(record, dict) or set(record) != _EXECUTION_RECORD_FIELDS:
            raise ValueError("tool_calls.jsonl record does not match the execution-evidence schema")
        if record.get("tool") != "run-starskill" or record.get("command") != "run-starskill":
            raise ValueError("tool_calls.jsonl record must declare run-starskill")
        if record.get("case_id") != case.case_id or record.get("case_kind") != case.kind:
            raise ValueError("tool_calls.jsonl case identity does not match the declared case")
        if record.get("workflow") != case.workflow or record.get("task_path") != case.task_path:
            raise ValueError("tool_calls.jsonl task/workflow does not match the declared case")
        if record.get("worker_role") not in {"teacher", "outreach", "research"}:
            raise ValueError("tool_calls.jsonl worker_role is invalid")
        if canonical_worker_role is not None and record["worker_role"] != canonical_worker_role:
            raise ValueError("tool_calls.jsonl worker_role does not match the canonical case role")
        if worker_role is not None and record["worker_role"] != worker_role:
            raise ValueError("tool_calls.jsonl worker_role differs from score bundle")
        if record.get("run_dir") != str(run_dir) or record.get("output_dir") != str(run_dir):
            raise ValueError("tool_calls.jsonl run/output directory does not match the captured run")
        if record.get("return_code") != return_code or any(record.get(key) != value for key, value in expected_paths.items()):
            raise ValueError("tool_calls.jsonl captured result links do not match the evidence files")
        result = record.get("result")
        if result != {"return_code": return_code, "output_dir": str(run_dir), **expected_paths}:
            raise ValueError("tool_calls.jsonl result does not link to the captured execution evidence")
        roles.add(record["worker_role"])
    if len(roles) != 1:
        raise ValueError("tool_calls.jsonl must declare exactly one worker role")
    return roles.pop()


def _resolve_run_evidence_path(run_dir: Path, raw_path: str | None, field: str) -> Path:
    if not raw_path:
        raise ReportError("invalid_execution_evidence", f"score bundle is missing {field}")
    path = Path(raw_path).resolve()
    try:
        path.relative_to(run_dir)
    except ValueError as exc:
        raise ReportError("invalid_execution_evidence", f"{field} must remain inside run_dir") from exc
    if not path.is_file():
        raise ReportError("invalid_execution_evidence", f"captured {field} is missing: {path}")
    return path


def _validate_review(
    bundle: ScoreBundle, case: EvaluationCase, machine: MachineCheckReport
) -> ReviewReport | None:
    if bundle.review is None:
        return None
    try:
        review = ReviewReport.model_validate(bundle.review)
    except ValidationError as exc:
        raise ReportError("invalid_score_report", "review data did not match required schema", details=exc.errors()) from exc
    if review.case_id != case.case_id:
        raise ReportError("evidence_mismatch", "review case_id does not match canonical case")
    expected_reviewer = NORMAL_REVIEWER_BY_WORKER_ROLE[case.role]
    if review.reviewer_role == "adjudicator":
        _validate_adjudication_evidence(bundle, case, machine, expected_reviewer)
    elif review.reviewer_role != expected_reviewer:
        raise ReportError(
            "invalid_reviewer_rotation",
            f"invalid reviewer rotation: {case.role} cases must be reviewed by {expected_reviewer}",
        )
    if not bundle.review_path or not bundle.review_sha256:
        raise ReportError("invalid_score_report", "review evidence path and hash are required")
    review_path = Path(bundle.review_path).resolve()
    if not review_path.is_file() or _file_sha256(review_path) != bundle.review_sha256:
        raise ReportError("evidence_mismatch", "review file differs from captured review evidence")
    if _load_json_object(review_path, "review_path") != bundle.review:
        raise ReportError("evidence_mismatch", "review data differs from captured review evidence")
    return review


def _validate_adjudication_evidence(
    bundle: ScoreBundle, case: EvaluationCase, machine: MachineCheckReport, expected_reviewer: str
) -> None:
    if not bundle.escalation or not bundle.escalation_path or not bundle.escalation_sha256:
        raise ReportError("invalid_reviewer_rotation", "adjudicator requires documented normal-review escalation")
    path = Path(bundle.escalation_path).resolve()
    if not path.is_file() or _file_sha256(path) != bundle.escalation_sha256:
        raise ReportError("evidence_mismatch", "adjudication escalation file differs from captured evidence")
    if _load_json_object(path, "escalation_path") != bundle.escalation:
        raise ReportError("evidence_mismatch", "adjudication escalation differs from captured evidence")
    if set(bundle.escalation) != {"normal_review", "reason", "machine_check_codes"}:
        raise ReportError("invalid_reviewer_rotation", "adjudication escalation has an invalid schema")
    try:
        normal = ReviewReport.model_validate(bundle.escalation["normal_review"])
    except ValidationError as exc:
        raise ReportError("invalid_reviewer_rotation", "adjudication normal review is invalid", details=exc.errors()) from exc
    if normal.case_id != case.case_id or normal.reviewer_role != expected_reviewer:
        raise ReportError("invalid_reviewer_rotation", "adjudication must retain normal rotating reviewer evidence")
    reason = bundle.escalation["reason"]
    codes = bundle.escalation["machine_check_codes"]
    if reason == "normal_review_critical" and normal.critical_issues:
        return
    if reason == "machine_conflict" and isinstance(codes, list) and codes and all(
        isinstance(code, str) and any(issue.code == code for issue in machine.issues) for code in codes
    ):
        return
    raise ReportError("invalid_reviewer_rotation", "adjudication escalation does not prove a critical review or machine conflict")


def validate_bonus_evidence(bonus: dict[str, object], run_dir: Path, case: EvaluationCase) -> None:
    _validate_bonus_evidence(bonus, run_dir, case)


def _validate_bonus_evidence(bonus: dict[str, object], run_dir: Path, case: EvaluationCase) -> None:
    try:
        evidence = BonusEvidence.model_validate(bonus)
    except ValidationError as exc:
        raise ReportError("validation_error", "bonus evidence did not match the required schema", details=exc.errors()) from exc
    project_root = Path(__file__).resolve().parents[3]
    for category in ("standardization", "acceleration", "reproducible_refactor"):
        claim = getattr(evidence, category)
        if claim is None:
            continue
        reference_paths = {
            claim.baseline.path,
            claim.comparison.path,
            claim.verification.path,
        }
        if not reference_paths.issubset(set(claim.evidence_paths)):
            raise ReportError(
                "invalid_bonus_evidence",
                f"bonus {category} baseline, comparison, and verification paths must be listed in evidence_paths",
            )
        resolved = {
            reference: _read_bonus_evidence_file(
                category, reference, run_dir, project_root
            )
            for reference in [
                *claim.evidence_paths,
                claim.baseline.path,
                claim.comparison.path,
                claim.verification.path,
            ]
        }
        baseline = _parse_bonus_measurement(category, "baseline", resolved[claim.baseline.path])
        comparison = _parse_bonus_measurement(category, "comparison", resolved[claim.comparison.path])
        if baseline["metric"] != comparison["metric"] or baseline["unit"] != comparison["unit"]:
            raise ReportError(
                "invalid_bonus_evidence",
                f"bonus {category} baseline and comparison must measure the same metric and unit",
            )
        if baseline["value"] == comparison["value"]:
            raise ReportError(
                "invalid_bonus_evidence",
                f"bonus {category} baseline and comparison must contain different recorded values",
            )
        _parse_bonus_verification(category, resolved[claim.verification.path])


def _read_bonus_evidence_file(
    category: str, reference: str, run_dir: Path, project_root: Path
) -> bytes:
    path = _resolve_bonus_path(reference, run_dir, project_root)
    if not path.is_file():
        raise ReportError(
            "invalid_bonus_evidence",
            f"bonus {category} references a missing evidence file: {reference}",
        )
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ReportError(
            "invalid_bonus_evidence", f"bonus {category} evidence is unreadable: {reference}"
        ) from exc
    if not content:
        raise ReportError(
            "invalid_bonus_evidence", f"bonus {category} evidence must be non-empty: {reference}"
        )
    return content


def _parse_bonus_json(category: str, label: str, content: bytes) -> dict[str, object]:
    try:
        record = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReportError(
            "invalid_bonus_evidence", f"bonus {category} {label} must be a JSON evidence record"
        ) from exc
    if not isinstance(record, dict):
        raise ReportError(
            "invalid_bonus_evidence", f"bonus {category} {label} must be a JSON object"
        )
    return record


def _parse_bonus_measurement(category: str, label: str, content: bytes) -> dict[str, object]:
    record = _parse_bonus_json(category, label, content)
    if set(record) != {"record_type", "metric", "unit", "value"}:
        raise ReportError(
            "invalid_bonus_evidence",
            f"bonus {category} {label} must use the starskill_bonus_measurement schema",
        )
    value = record["value"]
    if (
        record["record_type"] != "starskill_bonus_measurement"
        or not isinstance(record["metric"], str)
        or not record["metric"].strip()
        or not isinstance(record["unit"], str)
        or not record["unit"].strip()
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ReportError(
            "invalid_bonus_evidence",
            f"bonus {category} {label} must contain a concrete finite measurement",
        )
    return record


def _parse_bonus_verification(category: str, content: bytes) -> None:
    record = _parse_bonus_json(category, "verification", content)
    if set(record) != {"record_type", "command", "exit_code", "passed"}:
        raise ReportError(
            "invalid_bonus_evidence",
            f"bonus {category} verification must use the starskill_bonus_verification schema",
        )
    exit_code = record["exit_code"]
    if (
        record["record_type"] != "starskill_bonus_verification"
        or not isinstance(record["command"], str)
        or not record["command"].strip()
        or isinstance(exit_code, bool)
        or not isinstance(exit_code, int)
        or exit_code != 0
        or record["passed"] is not True
    ):
        raise ReportError(
            "invalid_bonus_evidence",
            f"bonus {category} verification must record a passing command with exit_code 0",
        )


def _resolve_bonus_path(reference: str, run_dir: Path, project_root: Path) -> Path:
    if reference.startswith("repo:"):
        candidate = (project_root / reference.removeprefix("repo:")).resolve()
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise ReportError("invalid_bonus_evidence", "repository bonus evidence escapes the project root") from exc
        return candidate
    candidate = (run_dir / reference).resolve()
    try:
        candidate.relative_to(run_dir)
    except ValueError as exc:
        raise ReportError("invalid_bonus_evidence", "bonus evidence must remain inside run_dir or use repo: boundary") from exc
    return candidate


def _validate_case_matrix(bundles: list[ScoreBundle], canonical_cases: dict[str, EvaluationCase]) -> None:
    counts: dict[str, int] = {}
    for bundle in bundles:
        counts[bundle.case_id] = counts.get(bundle.case_id, 0) + 1
    missing_core = sorted(case_id for case_id, case in canonical_cases.items() if case.kind == "core" and counts.get(case_id, 0) != 3)
    missing_variants = sorted(case_id for case_id, case in canonical_cases.items() if case.kind == "variant" and counts.get(case_id, 0) == 0)
    if missing_core or missing_variants:
        raise ReportError(
            "incomplete_case_matrix",
            "aggregate requires three runs for every core case and every canonical variant case",
            details={"core": missing_core, "variants": missing_variants},
        )


def _load_json_object(path: Path, field_name: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReportError("invalid_score_report", f"failed to parse {field_name}: {path}", details=str(exc)) from exc
    if not isinstance(payload, dict):
        raise ReportError("invalid_score_report", f"{field_name} must contain a JSON object: {path}")
    return payload


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_score_bundle(path: Path) -> ScoreBundle:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReportError("invalid_score_report", f"failed to read score report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReportError("invalid_score_report", f"score report must be a JSON object: {path}")
    try:
        return ScoreBundle.model_validate(payload)
    except ValidationError as exc:
        fields = [
            ".".join(str(part) for part in error["loc"])
            for error in exc.errors(include_url=False, include_context=False)
        ]
        raise ReportError(
            "invalid_score_report",
            f"score report did not match the required schema ({', '.join(fields)}): {path}",
            details=exc.errors(include_url=False, include_context=False),
        ) from exc


def _validate_bundle_consistency(bundle: ScoreBundle, path: Path) -> None:
    if bundle.case_id != bundle.score.case_id:
        raise ReportError(
            "invalid_score_report",
            f"score bundle case_id mismatch in {path}",
            details={
                "field": "case_id",
                "wrapper_case_id": bundle.case_id,
                "nested_case_id": bundle.score.case_id,
            },
        )
    if bundle.case_kind != bundle.score.case_kind:
        raise ReportError(
            "invalid_score_report",
            f"score bundle case_kind mismatch in {path}",
            details={
                "field": "case_kind",
                "wrapper_case_kind": bundle.case_kind,
                "nested_case_kind": bundle.score.case_kind,
            },
        )


def _validate_bundle_references(bundle: ScoreBundle, path: Path) -> None:
    run_dir = Path(bundle.run_dir).resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        raise ReportError(
            "invalid_score_report",
            f"score bundle run_dir is missing or not a directory: {path}",
            details={"field": "run_dir", "run_dir": bundle.run_dir},
        )
    if bundle.run_id != run_dir.name:
        raise ReportError(
            "invalid_score_report",
            "score bundle run_id must match the physical run directory name",
            details={"run_id": bundle.run_id, "run_dir": str(run_dir)},
        )
    machine_checks_path = _resolve_reference_path(path, bundle.machine_checks_path, "machine_checks_path")
    summary_path = _resolve_reference_path(path, bundle.summary_path, "summary_path")
    _require_readable_file(machine_checks_path, "machine_checks_path")
    _require_readable_file(summary_path, "summary_path")


def _resolve_reference_path(score_json_path: Path, raw_path: str, field_name: str) -> Path:
    candidate = Path(raw_path)
    resolved = candidate if candidate.is_absolute() else (score_json_path.parent / candidate)
    try:
        return resolved.resolve()
    except OSError as exc:
        raise ReportError(
            "invalid_score_report",
            f"score bundle {field_name} could not be resolved: {score_json_path}",
            details={"field": field_name, "path": raw_path, "error": str(exc)},
        ) from exc


def _require_readable_file(path: Path, field_name: str) -> None:
    if not path.exists() or not path.is_file():
        raise ReportError(
            "invalid_score_report",
            f"score bundle {field_name} is missing or not a file: {path}",
            details={"field": field_name, "path": str(path)},
        )
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportError(
            "invalid_score_report",
            f"score bundle {field_name} is not readable as UTF-8 text: {path}",
            details={"field": field_name, "path": str(path), "error": str(exc)},
        ) from exc


def _reject_incomplete_report_dirs(score_root: Path) -> None:
    for directory in sorted(path for path in score_root.rglob("*") if path.is_dir()):
        has_report_artifact = any((directory / name).exists() for name in ("machine_checks.json", "summary.md"))
        has_score = (directory / "score.json").exists()
        if has_report_artifact and not has_score:
            raise ReportError(
                "incomplete_score_report",
                f"incomplete replay report directory missing score.json: {directory}",
                details={"directory": str(directory)},
            )


def _render_case_summary(
    case: EvaluationCase,
    machine: MachineCheckReport,
    review: ReviewReport | None,
    score: ScoreReport,
    bundle: ScoreBundle,
) -> str:
    critical_issues = [issue for issue in machine.issues if issue.severity == "critical"]
    reviewer_critical_issues = review.critical_issues if review is not None else []
    reviewer_issues = review.issues if review is not None else []
    reviewer_recommendation = (
        review.recommendation
        if review is not None
        else "not_applicable"
        if bundle.evidence_mode == "script_owned_engineering"
        else "missing"
    )
    checked = "\n".join(f"- `{path}`" for path in machine.checked_files) or "- None"
    machine_critical = (
        "\n".join(
            f"- `{issue.code}`: {issue.message}"
            + (f" (`{issue.evidence_path}`)" if issue.evidence_path else "")
            for issue in critical_issues
        )
        if critical_issues
        else ""
    )
    reviewer_critical = (
        "\n".join(f"- reviewer: {item}" for item in reviewer_critical_issues)
        if reviewer_critical_issues
        else ""
    )
    critical = "\n".join(part for part in (machine_critical, reviewer_critical) if part) or "- None"
    review_lines = "\n".join(f"- {item}" for item in reviewer_issues) or "- None"
    bonus_lines = (
        "\n".join(
            f"- {name}: `{value.get('awarded', 0) if isinstance(value, dict) else value}` "
            f"evidence `{', '.join(value.get('evidence_paths', [])) if isinstance(value, dict) else ''}`"
            for name, value in sorted(bundle.bonus.items())
        )
        if bundle.bonus
        else "- None"
    )
    return (
        f"# Evaluation Replay Summary: {case.case_id}\n\n"
        f"- Case ID: `{case.case_id}`\n"
        f"- Case kind: `{case.kind}`\n"
        f"- Evidence mode: `{bundle.evidence_mode}`\n"
        f"- Hard-gate passed: `{score.hard_gate_passed}`\n"
        f"- Reviewer recommendation: `{reviewer_recommendation}`\n\n"
        "## Calculated facts\n\n"
        f"- Closed loop: `{score.dimensions.get('closed_loop', 0)}`\n"
        f"- Scientific correctness: `{score.dimensions.get('scientific_correctness', 0)}`\n"
        f"- Reproducibility: `{score.dimensions.get('reproducibility', 0)}`\n"
        f"- Error and safety: `{score.dimensions.get('error_and_safety', 0)}`\n"
        f"- Role usability: `{score.dimensions.get('role_usability', 0)}`\n"
        f"- Bonus score: `{score.bonus_score}`\n"
        f"- Bonus evidence categories:\n{bonus_lines}\n\n"
        "## Rule-based conclusions\n\n"
        f"- Expected workflow: `{case.workflow}`\n"
        f"- Expected status: `{case.expected_status}`\n"
        f"- Observed exit code: `{machine.exit_code}`\n"
        f"- Checked artifact paths:\n{checked}\n\n"
        "## Captured execution evidence\n\n"
        f"- Return code: `{bundle.raw_inputs.return_code}`\n"
        f"- stdout: `{bundle.raw_inputs.stdout_file}`\n"
        f"- stderr: `{bundle.raw_inputs.stderr_file}`\n"
        f"- tool calls: `{bundle.raw_inputs.tool_calls_file}`\n"
        f"- response: `{bundle.raw_inputs.response_file}`\n"
        f"- review evidence: `{bundle.review_path}`\n\n"
        f"- Critical issues:\n{critical}\n\n"
        "## Human review\n\n"
        f"- Recommendation: `{reviewer_recommendation}`\n"
        f"- Reviewer issues:\n{review_lines}\n"
    )


def _render_aggregate_summary(summary: EvaluationSummary, bundles: list[ScoreBundle]) -> str:
    case_counts: dict[str, int] = {}
    for bundle in bundles:
        case_counts[bundle.case_id] = case_counts.get(bundle.case_id, 0) + 1
    failed_bundles = [bundle for bundle in bundles if not bundle.score.hard_gate_passed]
    lines = [
        "# Evaluation Aggregate Summary",
        "",
        f"- Total runs: `{summary.total_runs}`",
        f"- Hard-gate pass rate: `{summary.hard_gate_pass_rate}`",
        f"- Core average base score: `{summary.core_average_base_score}`",
        f"- Passed: `{summary.passed}`",
        "",
        "## Acceptance thresholds",
        "",
        *[f"- {name}: `{value}`" for name, value in sorted(summary.thresholds.items())],
        "",
        "## Completeness and stability",
        "",
        *[
            f"- {case_id}: `{case_counts[case_id]}` runs, stddev `{stddev}`"
            for case_id, stddev in sorted(summary.per_case_standard_deviation.items())
        ],
        *[
            f"- {case_id}: `{count}` runs"
            for case_id, count in sorted(case_counts.items())
            if case_id not in summary.per_case_standard_deviation
        ],
        "",
        "## Open-task scores (independent 20-point scale)",
        "",
        *(
            [
            f"- {case_id}: `{score}` / 20"
            for case_id, score in sorted(summary.open_task_scores.items())
            ]
            or ["- None"]
        ),
        "",
        "## Final decision",
        "",
        *[f"- {name}: `{value}`" for name, value in sorted(summary.decisions.items())],
        "",
    ]
    if not failed_bundles:
        lines.extend(["## Critical failure evidence", "", "- None"])
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "## Critical failure evidence",
            "",
            "| case_id | run_id | case_kind | hard_gate | base | bonus | total |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for bundle in failed_bundles:
        lines.append(
            f"| {bundle.score.case_id} | {bundle.run_id} | {bundle.score.case_kind} | "
            f"{bundle.score.hard_gate_passed} | {bundle.score.base_score} | "
            f"{bundle.score.bonus_score} | {bundle.score.total_score} |"
        )
    critical_paths = []
    for bundle in failed_bundles:
        critical_paths.extend(
            f"- `{bundle.case_id}` / `{bundle.run_id}`: `{issue.evidence_path}`"
            for issue in bundle.score.issues
            if issue.severity == "critical" and issue.evidence_path
        )
        if bundle.review and bundle.review.get("critical_issues") and bundle.review_path:
            critical_paths.append(f"- `{bundle.case_id}` / `{bundle.run_id}` reviewer evidence: `{bundle.review_path}`")
    lines.extend(critical_paths or ["- None"])
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
