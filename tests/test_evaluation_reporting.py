import json
from pathlib import Path

import pytest

from starskill.evaluation.cases import load_case
from starskill.evaluation.checks import check_run
from starskill.evaluation.models import ReviewReport
from starskill.evaluation.reporting import (
    ReportError,
    ScoreBundle,
    collect_score_reports,
    write_aggregate_reports,
    write_case_reports,
)
from starskill.evaluation.scoring import aggregate_scores, score_case


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _score_payload(
    *,
    run_dir: Path,
    machine_checks_path: Path,
    summary_path: Path,
    case_id: str = "core-m42",
    case_kind: str = "core",
    nested_case_id: str | None = None,
    nested_case_kind: str | None = None,
    review: dict[str, object] | None = None,
    bonus: dict[str, float] | None = None,
) -> dict[str, object]:
    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "case_id": case_id,
        "case_kind": case_kind,
        "machine_checks_path": str(machine_checks_path),
        "summary_path": str(summary_path),
        "raw_inputs": {
            "return_code": 0,
            "stdout": "",
            "stderr": "",
            "stdout_file": None,
            "stderr_file": None,
        },
        "review": review,
        "bonus": bonus or {},
        "score": {
            "case_id": nested_case_id or case_id,
            "case_kind": nested_case_kind or case_kind,
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
    }


def _write_complete_bundle(root: Path, *, payload: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    machine_checks_path = Path(str(payload["machine_checks_path"]))
    summary_path = Path(str(payload["summary_path"]))
    machine_checks_path.write_text(
        json.dumps({"ok": True}, indent=2, sort_keys=True), encoding="utf-8"
    )
    summary_path.write_text("# summary\n", encoding="utf-8")
    (root / "score.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def test_write_case_reports_serializes_json_and_markdown(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stderr_text = json.dumps({"valid": False, "error": "validation_error"})
    (run_dir / "stderr.json").write_text(stderr_text, encoding="utf-8")
    machine = check_run(case, run_dir, 2, "", stderr_text)
    review = ReviewReport.model_validate(
        {
            "case_id": case.case_id,
            "reviewer_role": "teacher",
            "role_usability_points": 5,
            "safety_review_points": 6,
            "critical_issues": [],
            "issues": [],
            "confidence": 0.9,
            "recommendation": "pass",
        }
    )
    score = score_case(machine, review, {})
    output_dir = tmp_path / "report"

    bundle = write_case_reports(
        case=case,
        run_dir=run_dir,
        return_code=2,
        stdout_text="",
        stderr_text=stderr_text,
        review=review,
        score=score,
        machine=machine,
        output_dir=output_dir,
    )

    machine_payload = json.loads((output_dir / "machine_checks.json").read_text(encoding="utf-8"))
    score_payload = json.loads((output_dir / "score.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "summary.md").read_text(encoding="utf-8")

    assert bundle.run_id == "run"
    assert machine_payload["run"]["stderr"] == stderr_text
    assert machine_payload["machine_check"]["hard_gate_passed"] is True
    assert score_payload["score"]["case_id"] == case.case_id
    assert score_payload["score"]["hard_gate_passed"] is True
    assert score_payload["review"]["recommendation"] == "pass"
    assert score_payload["bonus"] == {}
    assert "Calculated facts" in markdown
    assert "Rule-based conclusions" in markdown
    assert "Human review" in markdown
    assert "critical issues" in markdown.lower()
    assert "checked artifact paths" in markdown.lower()
    assert case.case_id in markdown


def test_write_case_reports_includes_reviewer_critical_issues_and_bonus_categories(
    tmp_path,
) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stderr_text = json.dumps({"valid": False, "error": "validation_error"})
    machine = check_run(case, run_dir, 2, "", stderr_text)
    review = ReviewReport.model_validate(
        {
            "case_id": case.case_id,
            "reviewer_role": "teacher",
            "role_usability_points": 5,
            "safety_review_points": 6,
            "critical_issues": ["unsafe boundary advice"],
            "issues": [],
            "confidence": 0.9,
            "recommendation": "fail",
        }
    )
    score = score_case(machine, review, {"standardization": 3, "acceleration": 2})
    output_dir = tmp_path / "report"

    write_case_reports(
        case=case,
        run_dir=run_dir,
        return_code=2,
        stdout_text="",
        stderr_text=stderr_text,
        review=review,
        score=score,
        machine=machine,
        output_dir=output_dir,
        bonus={"standardization": 3, "acceleration": 2},
    )

    markdown = (output_dir / "summary.md").read_text(encoding="utf-8")
    score_payload = json.loads((output_dir / "score.json").read_text(encoding="utf-8"))

    assert "unsafe boundary advice" in markdown
    assert "standardization" in markdown
    assert "acceleration" in markdown
    assert score_payload["bonus"] == {"acceleration": 2, "standardization": 3}


def test_collect_and_write_aggregate_reports_requires_complete_valid_scores(tmp_path) -> None:
    score_root = tmp_path / "scores"
    first = score_root / "run-a"
    second = score_root / "run-b"
    _write_complete_bundle(
        first,
        payload=_score_payload(
            run_dir=first,
            machine_checks_path=first / "machine_checks.json",
            summary_path=first / "summary.md",
        ),
    )
    _write_complete_bundle(
        second,
        payload=_score_payload(
            run_dir=second,
            machine_checks_path=second / "machine_checks.json",
            summary_path=second / "summary.md",
            case_id="core-m42",
            case_kind="core",
        )
    )
    second_payload = json.loads((second / "score.json").read_text(encoding="utf-8"))
    second_payload["score"]["base_score"] = 90
    second_payload["score"]["total_score"] = 90
    second_payload["score"]["dimensions"]["reproducibility"] = 15
    second_payload["score"]["dimensions"]["error_and_safety"] = 5
    (second / "score.json").write_text(
        json.dumps(second_payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    output_dir = tmp_path / "aggregate"

    bundles = collect_score_reports(score_root)
    summary = aggregate_scores([bundle.score for bundle in bundles])
    write_aggregate_reports(summary, bundles, output_dir)

    summary_payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    markdown = (output_dir / "summary.md").read_text(encoding="utf-8")

    assert [bundle.run_id for bundle in bundles] == ["run-a", "run-b"]
    assert summary_payload["total_runs"] == 2
    assert "core-m42" in markdown
    assert "## Critical failure evidence\n\n- None" in markdown
    assert "| case_id | run_id | case_kind | hard_gate | base | bonus | total |" not in markdown


def test_aggregate_summary_lists_only_failed_runs_in_critical_failure_table(tmp_path) -> None:
    run_dir = tmp_path / "run-a"
    payload = _score_payload(
        run_dir=run_dir,
        machine_checks_path=run_dir / "machine_checks.json",
        summary_path=run_dir / "summary.md",
    )
    score = payload["score"]
    assert isinstance(score, dict)
    score.update(
        {
            "hard_gate_passed": False,
            "base_score": 0,
            "total_score": 0,
            "dimensions": {
                "closed_loop": 0,
                "scientific_correctness": 0,
                "reproducibility": 0,
                "error_and_safety": 0,
                "role_usability": 0,
            },
        }
    )
    bundle = ScoreBundle.model_validate(payload)
    summary = aggregate_scores([bundle.score])

    write_aggregate_reports(summary, [bundle], tmp_path / "aggregate")

    markdown = (tmp_path / "aggregate" / "summary.md").read_text(encoding="utf-8")
    assert "| case_id | run_id | case_kind | hard_gate | base | bonus | total |" in markdown
    assert "| core-m42 | run-a | core | False | 0.0 | 0.0 | 0.0 |" in markdown


def test_collect_score_reports_allows_reused_run_id_in_distinct_run_directories(tmp_path) -> None:
    score_root = tmp_path / "scores"
    first = score_root / "first" / "run"
    second = score_root / "second" / "run"
    for run_dir in (first, second):
        _write_complete_bundle(
            run_dir,
            payload=_score_payload(
                run_dir=run_dir,
                machine_checks_path=run_dir / "machine_checks.json",
                summary_path=run_dir / "summary.md",
            ),
        )

    bundles = collect_score_reports(score_root)

    assert [bundle.run_id for bundle in bundles] == ["run", "run"]


def test_collect_score_reports_rejects_wrapper_case_id_mismatch(tmp_path) -> None:
    score_root = tmp_path / "scores"
    run_dir = score_root / "run-a"
    _write_complete_bundle(
        run_dir,
        payload=_score_payload(
            run_dir=run_dir,
            machine_checks_path=run_dir / "machine_checks.json",
            summary_path=run_dir / "summary.md",
            case_id="core-m42",
            nested_case_id="core-m51",
        ),
    )

    with pytest.raises(ReportError, match="case_id"):
        collect_score_reports(score_root)


def test_collect_score_reports_rejects_wrapper_case_kind_mismatch(tmp_path) -> None:
    score_root = tmp_path / "scores"
    run_dir = score_root / "run-a"
    _write_complete_bundle(
        run_dir,
        payload=_score_payload(
            run_dir=run_dir,
            machine_checks_path=run_dir / "machine_checks.json",
            summary_path=run_dir / "summary.md",
            case_kind="core",
            nested_case_kind="variant",
        ),
    )

    with pytest.raises(ReportError, match="case_kind"):
        collect_score_reports(score_root)


def test_collect_score_reports_rejects_score_only_bundle_missing_references(tmp_path) -> None:
    score_root = tmp_path / "scores"
    run_dir = score_root / "run-a"
    run_dir.mkdir(parents=True)
    (run_dir / "score.json").write_text(
        json.dumps(
            {
                "run_id": "run-a",
                "run_dir": str(run_dir),
                "case_id": "core-m42",
                "case_kind": "core",
                "raw_inputs": {
                    "return_code": 0,
                    "stdout": "",
                    "stderr": "",
                    "stdout_file": None,
                    "stderr_file": None,
                },
                "review": None,
                "bonus": {},
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

    with pytest.raises(ReportError, match="machine_checks_path"):
        collect_score_reports(score_root)
