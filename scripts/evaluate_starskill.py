"""Offline replay and aggregation CLI for StarSkill evaluation reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from starskill.evaluation.runner import ExecutionError, execute_case
from starskill.evaluation.scoring import aggregate_scores, score_case
from tests.fixtures.evaluation.replay_fixtures import (
    write_fixed_m42_cache,
    write_fixed_sdss_cache,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evaluate_starskill")
    commands = parser.add_subparsers(dest="command", required=True)

    execute_parser = commands.add_parser("execute", help="run one case and record the real CLI process")
    execute_parser.add_argument("--case", type=Path, required=True)
    execute_parser.add_argument("--run-dir", type=Path, required=True)
    execute_parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))
    execute_parser.add_argument("--target-cache-dir", type=Path, default=Path("cache/targets"))
    execute_parser.add_argument("--image-cache-dir", type=Path, default=Path("cache/sdss"))

    replay_parser = commands.add_parser("replay", help="replay a saved local evaluation run")
    replay_parser.add_argument("--case", type=Path, required=True)
    replay_parser.add_argument("--run-dir", type=Path, required=True)
    replay_parser.add_argument("--return-code", type=int)
    replay_parser.add_argument("--stdout-file", type=Path)
    replay_parser.add_argument("--stderr-file", type=Path)
    replay_parser.add_argument("--review-file", type=Path)
    replay_parser.add_argument("--bonus-file", type=Path)
    replay_parser.add_argument("--escalation-file", type=Path)
    replay_parser.add_argument("--output-dir", type=Path, required=True)

    aggregate_parser = commands.add_parser("aggregate", help="aggregate replay score reports")
    aggregate_parser.add_argument("--score-root", type=Path, required=True)
    aggregate_parser.add_argument("--output-dir", type=Path, required=True)

    acceptance_parser = commands.add_parser(
        "acceptance",
        help="execute and replay the 19-run script-owned core and variant matrix",
    )
    acceptance_parser.add_argument("--run-root", type=Path)
    acceptance_parser.add_argument("--score-root", type=Path)
    acceptance_parser.add_argument("--output-dir", type=Path, required=True)
    acceptance_parser.add_argument("--python-executable", type=Path, default=Path(sys.executable))

    args = parser.parse_args(argv)

    try:
        if args.command == "execute":
            return _execute(args)
        if args.command == "replay":
            return _replay(args)
        if args.command == "acceptance":
            return _acceptance(args)
        return _aggregate(args)
    except ExecutionError as exc:
        _print_error("execution_error", str(exc))
        return 1
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

    evidence = validate_execution_evidence(case, run_dir, args.return_code, stdout_file, stderr_file)
    evidence_mode = (
        "script_owned_engineering" if evidence.execution_file is not None else "external_worker"
    )
    stdout_text = _read_optional_text(evidence.stdout_file)
    stderr_text = _read_optional_text(evidence.stderr_file)
    review = _read_review(review_file)
    bonus = _read_bonus(bonus_file)
    escalation = _read_escalation(escalation_file)
    if evidence_mode == "script_owned_engineering" and any(
        (review is not None, bonus, escalation is not None)
    ):
        raise ReportError(
            "invalid_engineering_evidence",
            "script-owned engineering replay cannot include reviewer, bonus, or escalation evidence",
        )
    validate_bonus_evidence(bonus, run_dir, case)
    machine = check_run(case, run_dir, evidence.return_code, stdout_text, stderr_text)
    _validate_replay_identity(case, review, evidence.role, machine, escalation)
    try:
        score = score_case(
            machine,
            review,
            bonus,
            script_owned_engineering=evidence_mode == "script_owned_engineering",
        )
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
        return_code=evidence.return_code,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        review=review,
        score=score,
        machine=machine,
        output_dir=output_dir,
        stdout_file=evidence.stdout_file,
        stderr_file=evidence.stderr_file,
        execution_file=evidence.execution_file,
        bonus=bonus,
        review_file=review_file,
        worker_role=evidence.role,
        evidence_mode=evidence_mode,
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


def _execute(args: argparse.Namespace) -> int:
    record = execute_case(
        args.case,
        args.run_dir,
        python_executable=args.python_executable,
        target_cache_dir=args.target_cache_dir,
        image_cache_dir=args.image_cache_dir,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "case_id": record.case_id,
                "return_code": record.return_code,
                "run_dir": record.run_dir,
                "execution_file": str(Path(record.run_dir) / "execution.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _acceptance(args: argparse.Namespace) -> int:
    """Run the script-owned release matrix without Agent claims."""
    run_root, score_root, output_dir = _prepare_acceptance_directories(args)
    _reject_overlapping_directories(run_root, score_root, output_dir)
    cases_root = Path(__file__).resolve().parents[1] / "evaluation" / "cases"
    case_paths = [
        path
        for path in sorted(cases_root.rglob("*.json"))
        if load_case(path).kind in {"core", "variant"}
    ]
    cache_root = run_root / "cache"
    results: list[dict[str, object]] = []
    for case_path in case_paths:
        case = load_case(case_path)
        repetitions = 3 if case.kind == "core" else 1
        for attempt in range(1, repetitions + 1):
            run_name = f"recorded-{attempt:02d}"
            run_dir = run_root / case.case_id / run_name
            score_dir = score_root / case.case_id / run_name
            target_cache_dir, image_cache_dir = _acceptance_cache_dirs(
                cache_root, case.case_id, run_name
            )
            if case.workflow == "run":
                write_fixed_m42_cache(target_cache_dir)
            if case.workflow == "fetch-image":
                write_fixed_sdss_cache(Path(case.task_path), image_cache_dir)
            record = execute_case(
                case_path,
                run_dir,
                python_executable=args.python_executable,
                target_cache_dir=target_cache_dir,
                image_cache_dir=image_cache_dir,
            )
            replay_exit = _replay(
                argparse.Namespace(
                    case=case_path,
                    run_dir=run_dir,
                    return_code=None,
                    stdout_file=None,
                    stderr_file=None,
                    review_file=None,
                    bonus_file=None,
                    escalation_file=None,
                    output_dir=score_dir,
                )
            )
            if replay_exit != 0:
                raise ReportError("acceptance_replay_failed", f"replay failed for {case.case_id}/{run_name}")
            results.append(
                {
                    "case_id": case.case_id,
                    "run_name": run_name,
                    "return_code": record.return_code,
                    "replay_exit_code": replay_exit,
                    "run_dir": str(run_dir.resolve()),
                    "score_dir": str(score_dir.resolve()),
                    "execution_file": str((run_dir / "execution.json").resolve()),
                    "artifact_sha256": record.artifact_sha256,
                }
            )

    bundles = collect_score_reports(score_root, cases_root=cases_root)
    summary = aggregate_scores([bundle.score for bundle in bundles])
    write_aggregate_reports(summary, bundles, output_dir)
    manifest = {
        "ok": summary.passed,
        "mode": "script_owned_engineering_acceptance",
        "total_runs": summary.total_runs,
        "passed": summary.passed,
        "run_root": str(run_root),
        "score_root": str(score_root),
        "output_dir": str(output_dir),
        "runs": results,
    }
    (output_dir / "acceptance.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary.passed else 1


def _acceptance_cache_dirs(cache_root: Path, case_id: str, run_name: str) -> tuple[Path, Path]:
    target_cache_dir = cache_root / "targets" / case_id / run_name
    if case_id == "variant-m51-cache-reuse":
        return target_cache_dir, cache_root / "sdss" / "core-m51-sdss" / "recorded-01"
    return target_cache_dir, cache_root / "sdss" / case_id / run_name


def _prepare_acceptance_directories(
    args: argparse.Namespace,
) -> tuple[Path, Path, Path]:
    if (args.run_root is None) != (args.score_root is None):
        raise ReportError(
            "invalid_acceptance_layout",
            "--run-root and --score-root must be provided together",
        )
    if args.run_root is not None:
        return (
            _prepare_fresh_directory(args.run_root, "run root"),
            _prepare_fresh_directory(args.score_root, "score root"),
            _prepare_fresh_directory(args.output_dir, "aggregate output directory"),
        )

    acceptance_root = _prepare_fresh_directory(args.output_dir, "acceptance output root")
    run_root = acceptance_root / "runs"
    score_root = acceptance_root / "scores"
    aggregate_root = acceptance_root / "reports"
    run_root.mkdir()
    score_root.mkdir()
    aggregate_root.mkdir()
    return run_root, score_root, aggregate_root


def _prepare_fresh_directory(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise ReportError("unsafe_output_path", f"{label} must be new and empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _reject_overlapping_directories(*paths: Path) -> None:
    for index, left in enumerate(paths):
        for right in paths[index + 1 :]:
            try:
                right.relative_to(left)
            except ValueError:
                try:
                    left.relative_to(right)
                except ValueError:
                    continue
            raise ReportError(
                "unsafe_output_path",
                "acceptance run, score, and aggregate directories must not overlap",
            )


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
