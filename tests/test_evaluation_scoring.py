import pytest
from pydantic import ValidationError

from starskill.evaluation.models import CheckIssue, MachineCheckReport, ReviewReport, ScoreReport
from starskill.evaluation.scoring import aggregate_scores, score_case


def passing_machine(case_id: str, case_kind: str = "core") -> MachineCheckReport:
    return MachineCheckReport(
        case_id=case_id,
        case_kind=case_kind,
        hard_gate_passed=True,
        exit_code=0,
        dimension_points={
            "closed_loop": 40,
            "scientific_correctness": 25,
            "reproducibility": 20,
            "machine_safety": 4,
        },
        issues=[],
        checked_files=["run.json"],
    )


def critical_machine(
    case_id: str,
    code: str = "missing_artifact",
    case_kind: str = "core",
) -> MachineCheckReport:
    return MachineCheckReport(
        case_id=case_id,
        case_kind=case_kind,
        hard_gate_passed=False,
        exit_code=1,
        dimension_points={
            "closed_loop": 0,
            "scientific_correctness": 0,
            "reproducibility": 0,
            "machine_safety": 0,
        },
        issues=[
            CheckIssue(
                code=code,
                message="critical evaluation failure",
                evidence_path="run.json",
                severity="critical",
            )
        ],
        checked_files=["run.json"],
    )


def passing_review(case_id: str) -> ReviewReport:
    return ReviewReport(
        case_id=case_id,
        reviewer_role="teacher",
        role_usability_points=5,
        safety_review_points=6,
        confidence=0.9,
        recommendation="pass",
    )


def bonus_claim(awarded: float) -> dict[str, object]:
    return {
        "awarded": awarded,
        "evidence_paths": ["evidence.txt"],
        "baseline": {"path": "baseline.txt", "description": "baseline measurement"},
        "comparison": {"path": "comparison.txt", "description": "comparison measurement"},
        "verification": {"path": "verification.txt", "description": "focused test output"},
    }


def test_score_case_combines_machine_and_review_points() -> None:
    report = score_case(passing_machine("core-m42"), passing_review("core-m42"), {})

    assert report.hard_gate_passed is True
    assert report.base_score == 100
    assert report.bonus_score == 0
    assert report.total_score == 100


def test_critical_machine_issue_cannot_be_repaired_by_bonus() -> None:
    machine = critical_machine("core-m42")

    report = score_case(machine, passing_review("core-m42"), {"standardization": bonus_claim(3)})

    assert report.hard_gate_passed is False
    assert report.base_score == 0
    assert report.bonus_score == 0
    assert report.total_score == 0
    assert report.issues == machine.issues


def test_score_case_returns_zero_when_reviewer_is_missing() -> None:
    report = score_case(passing_machine("core-m51"), None, {"acceleration": bonus_claim(3)})

    assert report.hard_gate_passed is False
    assert report.base_score == 0
    assert report.bonus_score == 0
    assert report.total_score == 0
    assert report.issues == []


def test_score_case_uses_only_machine_dimensions_for_script_owned_engineering() -> None:
    report = score_case(
        passing_machine("core-m51"),
        None,
        {},
        script_owned_engineering=True,
    )

    assert report.hard_gate_passed is True
    assert report.base_score == 89
    assert report.bonus_score == 0
    assert report.total_score == 89
    assert report.dimensions["error_and_safety"] == 4
    assert report.dimensions["role_usability"] == 0


def test_score_case_returns_zero_when_reviewer_has_critical_issue() -> None:
    review = passing_review("core-moon").model_copy(
        update={"critical_issues": ["unsafe guidance"]}
    )

    report = score_case(passing_machine("core-moon"), review, {"acceleration": bonus_claim(3)})

    assert report.hard_gate_passed is False
    assert report.base_score == 0
    assert report.bonus_score == 0
    assert report.total_score == 0
    assert report.issues == []


def test_score_case_awards_bonus_up_to_the_category_and_total_caps() -> None:
    report = score_case(
        passing_machine("variant-m42-location-time", "variant"),
        passing_review("variant-m42-location-time"),
        {"standardization": bonus_claim(3), "acceleration": bonus_claim(3), "reproducible_refactor": bonus_claim(4)},
    )

    assert report.base_score == 100
    assert report.bonus_score == 10
    assert report.total_score == 110


def test_score_case_rejects_bonus_category_above_cap() -> None:
    with pytest.raises(ValueError, match="standardization"):
        score_case(
            passing_machine("variant-m51-cache-reuse", "variant"),
            passing_review("variant-m51-cache-reuse"),
            {"standardization": bonus_claim(3.1)},
        )


def test_score_case_rejects_unexpected_bonus_key() -> None:
    with pytest.raises(ValidationError, match="surprise"):
        score_case(
            passing_machine("core-m42"),
            passing_review("core-m42"),
            {"surprise": bonus_claim(1)},
        )


def test_score_case_clamps_machine_safety_to_four_before_reviewer_safety() -> None:
    report = score_case(
        passing_machine("core-m42").model_copy(
            update={
                "dimension_points": {
                    "closed_loop": 40,
                    "scientific_correctness": 25,
                    "reproducibility": 20,
                    "machine_safety": 99,
                }
            }
        ),
        passing_review("core-m42").model_copy(update={"safety_review_points": 1}),
        {},
    )

    assert report.dimensions["error_and_safety"] == 5
    assert report.base_score == 95


def test_aggregate_reports_standard_deviation_and_thresholds() -> None:
    reports = [
        score_case(passing_machine("core-m42"), passing_review("core-m42"), {}),
        score_case(passing_machine("core-m42"), passing_review("core-m42"), {}),
        score_case(passing_machine("core-m42"), passing_review("core-m42"), {}),
    ]

    summary = aggregate_scores(reports)

    assert summary.total_runs == 3
    assert summary.hard_gate_pass_rate == 1
    assert summary.core_hard_gate_pass_rate == 1
    assert summary.variant_hard_gate_pass_rate == 0
    assert summary.average_base_score == 100
    assert summary.core_average_base_score == 100
    assert summary.per_case_standard_deviation["core-m42"] == 0
    assert summary.open_task_scores == {}
    assert summary.thresholds == {
        "baseline_hard_gate_rate": 1.0,
        "variant_hard_gate_rate": 0.9,
        "core_average_base_score": 80.0,
        "per_case_stddev_max": 5.0,
    }
    assert summary.decisions == {
        "baseline_all_passed": True,
        "variants_passed": True,
        "core_average_passed": True,
        "stability_passed": True,
        "passed": True,
    }
    assert summary.passed is True


def test_aggregate_scores_keeps_open_task_scores_out_of_core_pass_boolean() -> None:
    reports = [
        score_case(passing_machine("core-m42"), passing_review("core-m42"), {}),
        score_case(
            passing_machine("variant-m42-location-time", "variant"),
            passing_review("variant-m42-location-time"),
            {},
        ),
        score_case(
            critical_machine("open-teacher-boundary", case_kind="open"),
            passing_review("open-teacher-boundary"),
            {},
        ),
    ]

    summary = aggregate_scores(reports)

    assert summary.open_task_scores == {"open-teacher-boundary": 0}
    assert summary.passed is True


def test_aggregate_scores_allows_one_failed_variant_out_of_six() -> None:
    reports = [
        score_case(passing_machine("core-m42"), passing_review("core-m42"), {}),
        score_case(passing_machine("variant-a", "variant"), passing_review("variant-a"), {}),
        score_case(passing_machine("variant-b", "variant"), passing_review("variant-b"), {}),
        score_case(passing_machine("variant-c", "variant"), passing_review("variant-c"), {}),
        score_case(passing_machine("variant-d", "variant"), passing_review("variant-d"), {}),
        score_case(passing_machine("variant-e", "variant"), passing_review("variant-e"), {}),
        score_case(critical_machine("variant-f", case_kind="variant"), passing_review("variant-f"), {}),
    ]

    summary = aggregate_scores(reports)

    assert summary.variant_hard_gate_pass_rate == pytest.approx(5 / 6)
    assert summary.passed is False


def test_aggregate_scores_accepts_population_standard_deviation_at_five() -> None:
    reports = [
        score_case(
            passing_machine("core-m51").model_copy(
                update={
                    "dimension_points": {
                        "closed_loop": 40,
                        "scientific_correctness": 25,
                        "reproducibility": 15,
                        "machine_safety": 0,
                    }
                }
            ),
            passing_review("core-m51").model_copy(
                update={"role_usability_points": 0, "safety_review_points": 0}
            ),
            {},
        ),
        score_case(
            passing_machine("core-m51").model_copy(
                update={
                    "dimension_points": {
                        "closed_loop": 40,
                        "scientific_correctness": 25,
                        "reproducibility": 20,
                        "machine_safety": 0,
                    }
                }
            ),
            passing_review("core-m51").model_copy(
                update={"role_usability_points": 5, "safety_review_points": 0}
            ),
            {},
        ),
    ]

    summary = aggregate_scores(reports)

    assert summary.per_case_standard_deviation["core-m51"] == 5
    assert summary.passed is True


def test_aggregate_scores_rejects_population_standard_deviation_above_five() -> None:
    reports = [
        score_case(
            passing_machine("core-m51").model_copy(
                update={
                    "dimension_points": {
                        "closed_loop": 40,
                        "scientific_correctness": 25,
                        "reproducibility": 15,
                        "machine_safety": 0,
                    }
                }
            ),
            passing_review("core-m51").model_copy(
                update={"role_usability_points": 0, "safety_review_points": 0}
            ),
            {},
        ),
        score_case(
            passing_machine("core-m51").model_copy(
                update={
                    "dimension_points": {
                        "closed_loop": 40,
                        "scientific_correctness": 25,
                        "reproducibility": 20,
                        "machine_safety": 2,
                    }
                }
            ),
            passing_review("core-m51").model_copy(
                update={"role_usability_points": 5, "safety_review_points": 0}
            ),
            {},
        ),
    ]

    summary = aggregate_scores(reports)

    assert summary.per_case_standard_deviation["core-m51"] == 6
    assert summary.passed is False


def test_aggregate_scores_uses_unrounded_stddev_for_pass_fail() -> None:
    reports = [
        ScoreReport(
            case_id="core-stability",
            case_kind="core",
            hard_gate_passed=True,
            base_score=80.0,
            bonus_score=0.0,
            total_score=80.0,
            dimensions={},
            issues=[],
        ),
        ScoreReport(
            case_id="core-stability",
            case_kind="core",
            hard_gate_passed=True,
            base_score=90.008,
            bonus_score=0.0,
            total_score=90.008,
            dimensions={},
            issues=[],
        ),
    ]

    summary = aggregate_scores(reports)

    assert summary.per_case_standard_deviation["core-stability"] == 5.0
    assert summary.decisions["stability_passed"] is False
    assert summary.passed is False


def test_aggregate_scores_groups_by_case_kind_not_case_id_prefix() -> None:
    reports = [
        score_case(passing_machine("alpha", "core"), passing_review("alpha"), {}),
        score_case(passing_machine("beta", "variant"), passing_review("beta"), {}),
        score_case(critical_machine("gamma", case_kind="variant"), passing_review("gamma"), {}),
        score_case(critical_machine("delta", case_kind="open"), passing_review("delta"), {}),
    ]

    summary = aggregate_scores(reports)

    assert summary.core_hard_gate_pass_rate == 1
    assert summary.variant_hard_gate_pass_rate == pytest.approx(0.5)
    assert summary.open_task_scores == {"delta": 0}
    assert summary.decisions["baseline_all_passed"] is True
