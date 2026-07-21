"""Offline replay and aggregation CLI for StarSkill evaluation reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from starskill.evaluation.cases import CaseManifestError, load_case
from starskill.evaluation.checks import check_run
from starskill.evaluation.models import ReviewReport
from starskill.evaluation.reporting import (
    ReportError,
    NORMAL_REVIEWER_BY_WORKER_ROLE,
    collect_score_reports,
    validate_bonus_evidence,
    validate_execution_evidence,
    write_aggregate_reports,
    write_case_reports,
)
from starskill.evaluation.scoring import aggregate_scores, score_case


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evaluate_starskill")
    commands = parser.add_subparsers(dest="command", required=True)

    replay_parser = commands.add_parser("replay", help="replay a saved local evaluation run")
    replay_parser.add_argument("--case", type=Path, required=True)
    replay_parser.add_argument("--run-dir", type=Path, required=True)
    replay_parser.add_argument("--return-code", type=int, required=True)
    replay_parser.add_argument("--stdout-file", type=Path)
    replay_parser.add_argument("--stderr-file", type=Path)
    replay_parser.add_argument("--review-file", type=Path)
    replay_parser.add_argument("--bonus-file", type=Path)
    replay_parser.add_argument("--escalation-file", type=Path)
    replay_parser.add_argument("--output-dir", type=Path, required=True)

    aggregate_parser = commands.add_parser("aggregate", help="aggregate replay score reports")
    aggregate_parser.add_argument("--score-root", type=Path, required=True)
    aggregate_parser.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args(argv)

    try:
        if args.command == "replay":
            return _replay(args)
        return _aggregate(args)
    except CaseManifestError as exc:
        _print_error("invalid_case_manifest", str(exc), exc.details)
        return 1
    except ReportError as exc:
        _print_error(exc.code, str(exc), exc.details)
        return 1


def _replay(args: argparse.Namespace) -> int:
    case_path = _require_file(args.case)
    run_dir = _require_directory(args.run_dir)
    output_dir = args.output_dir.resolve()
    _reject_output_inside_run_dir(run_dir, output_dir)

    case = load_case(case_path)
    stdout_file = _optional_file(args.stdout_file) or run_dir / "stdout.txt"
    stderr_file = _optional_file(args.stderr_file) or run_dir / "stderr.txt"
    review_file = _optional_file(args.review_file)
    bonus_file = _optional_file(args.bonus_file)
    escalation_file = _optional_file(args.escalation_file)

    worker_role = validate_execution_evidence(
        case, run_dir, args.return_code, stdout_file, stderr_file
    )
    stdout_text = _read_optional_text(stdout_file)
    stderr_text = _read_optional_text(stderr_file)
    review = _read_review(review_file)
    bonus = _read_bonus(bonus_file)
    escalation = _read_escalation(escalation_file)
    validate_bonus_evidence(bonus, run_dir, case)
    machine = check_run(case, run_dir, args.return_code, stdout_text, stderr_text)
    _validate_replay_identity(case, review, worker_role, machine, escalation)
    try:
        score = score_case(machine, review, bonus)
    except (ValidationError, ValueError) as exc:
        details = (
            exc.errors(include_url=False, include_context=False)
            if isinstance(exc, ValidationError)
            else {"message": str(exc)}
        )
        raise ReportError(
            "validation_error",
            f"bonus evidence did not match the required schema: {bonus_file}",
            details=details,
        ) from exc
    bundle = write_case_reports(
        case=case,
        run_dir=run_dir,
        return_code=args.return_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        review=review,
        score=score,
        machine=machine,
        output_dir=output_dir,
        stdout_file=stdout_file,
        stderr_file=stderr_file,
        bonus=bonus,
        review_file=review_file,
        worker_role=worker_role,
        escalation=escalation,
        escalation_file=escalation_file,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "case_id": bundle.score.case_id,
                "run_id": bundle.run_id,
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _aggregate(args: argparse.Namespace) -> int:
    score_root = _require_directory(args.score_root)
    cases_root = Path(__file__).resolve().parents[1] / "evaluation" / "cases"
    bundles = collect_score_reports(score_root, cases_root=cases_root)
    summary = aggregate_scores([bundle.score for bundle in bundles])
    write_aggregate_reports(summary, bundles, args.output_dir)
    print(
        json.dumps(
            {
                "ok": True,
                "total_runs": summary.total_runs,
                "passed": summary.passed,
                "output_dir": str(args.output_dir.resolve()),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _require_file(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ReportError("input_not_found", f"required file does not exist: {resolved}")
    return resolved


def _require_directory(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ReportError("input_not_found", f"required directory does not exist: {resolved}")
    return resolved


def _optional_file(path: Path | None) -> Path | None:
    if path is None:
        return None
    return _require_file(path)


def _read_optional_text(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportError("input_read_error", f"failed to read {path}: {exc}") from exc


def _read_review(path: Path | None) -> ReviewReport | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReportError("invalid_json", f"failed to parse reviewer JSON: {path}", details=str(exc)) from exc
    try:
        return ReviewReport.model_validate(payload)
    except ValidationError as exc:
        raise ReportError(
            "validation_error",
            f"reviewer JSON did not match ReviewReport: {path}",
            details=exc.errors(include_url=False, include_context=False),
        ) from exc


def _read_bonus(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReportError("invalid_json", f"failed to parse bonus JSON: {path}", details=str(exc)) from exc
    if not isinstance(payload, dict):
        raise ReportError(
            "invalid_json",
            f"bonus JSON must be an object: {path}",
            details={"path": str(path)},
        )
    return payload


def _read_escalation(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReportError("invalid_json", f"failed to parse escalation JSON: {path}", details=str(exc)) from exc
    if not isinstance(payload, dict):
        raise ReportError("invalid_json", f"escalation JSON must be an object: {path}")
    return payload


def _validate_replay_identity(case, review: ReviewReport | None, worker_role: str, machine, escalation: dict[str, object] | None) -> None:
    if worker_role != case.role:
        raise ReportError("invalid_worker_role", "declared worker role does not match the case role")
    if review is None:
        return
    if review.case_id != case.case_id:
        raise ReportError("invalid_review_identity", "review case_id does not match the declared case")
    expected = NORMAL_REVIEWER_BY_WORKER_ROLE[case.role]
    if review.reviewer_role == "adjudicator":
        _validate_adjudication(case, machine, escalation, expected)
        return
    if review.reviewer_role != expected:
        raise ReportError("invalid_reviewer_rotation", f"{case.role} cases require a {expected} reviewer")


def _validate_adjudication(case, machine, escalation: dict[str, object] | None, expected_reviewer: str) -> None:
    if escalation is None:
        raise ReportError("invalid_reviewer_rotation", "adjudicator requires documented normal-review escalation")
    if set(escalation) != {"normal_review", "reason", "machine_check_codes"}:
        raise ReportError("invalid_reviewer_rotation", "adjudication escalation has an invalid schema")
    try:
        normal_review = ReviewReport.model_validate(escalation["normal_review"])
    except ValidationError as exc:
        raise ReportError("invalid_reviewer_rotation", "adjudication normal review is invalid", details=exc.errors()) from exc
    if normal_review.case_id != case.case_id or normal_review.reviewer_role != expected_reviewer:
        raise ReportError("invalid_reviewer_rotation", "adjudication must retain the normal rotating reviewer evidence")
    reason = escalation["reason"]
    codes = escalation["machine_check_codes"]
    if reason == "normal_review_critical" and normal_review.critical_issues:
        return
    if reason == "machine_conflict" and isinstance(codes, list) and codes and all(
        isinstance(code, str) and any(issue.code == code for issue in machine.issues) for code in codes
    ):
        return
    raise ReportError("invalid_reviewer_rotation", "adjudication escalation does not prove a critical review or machine-check conflict")


def _reject_output_inside_run_dir(run_dir: Path, output_dir: Path) -> None:
    try:
        output_dir.relative_to(run_dir)
    except ValueError:
        return
    raise ReportError(
        "unsafe_output_path",
        f"output directory must not be inside the input run directory: {output_dir}",
    )


def _print_error(code: str, message: str, details: object | None = None) -> None:
    payload: dict[str, object] = {"ok": False, "error": code, "message": message}
    if details is not None:
        payload["details"] = details
    print(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
