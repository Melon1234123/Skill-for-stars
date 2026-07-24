"""Scoring and aggregation for deterministic evaluation reports."""

from __future__ import annotations

from collections import defaultdict
from math import sqrt

from pydantic import BaseModel, ConfigDict, Field

from starskill.evaluation.models import (
    EvaluationSummary,
    MachineCheckReport,
    ReviewReport,
    ScoreReport,
)


BASE_DIMENSION_LIMITS = {
    "closed_loop": 40.0,
    "scientific_correctness": 25.0,
    "reproducibility": 20.0,
    "error_and_safety": 10.0,
    "role_usability": 5.0,
}

THRESHOLDS = {
    "baseline_hard_gate_rate": 1.0,
    "variant_hard_gate_rate": 0.9,
    "core_average_base_score": 80.0,
    "per_case_stddev_max": 5.0,
}


class BonusEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standardization: "BonusClaim | None" = None
    acceleration: "BonusClaim | None" = None
    reproducible_refactor: "BonusClaim | None" = None


class BonusClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    awarded: float = Field(ge=0)
    evidence_paths: list[str] = Field(min_length=1)
    baseline: "BonusReference"
    comparison: "BonusReference"
    verification: "BonusReference"


class BonusReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    description: str = Field(min_length=1)


def score_case(
    machine: MachineCheckReport,
    review: ReviewReport | None,
    bonus: dict[str, object],
    *,
    script_owned_engineering: bool = False,
) -> ScoreReport:
    zero_dimensions = {name: 0.0 for name in BASE_DIMENSION_LIMITS}

    if not machine.hard_gate_passed:
        return ScoreReport(
            case_id=machine.case_id,
            case_kind=machine.case_kind,
            hard_gate_passed=False,
            base_score=0,
            bonus_score=0,
            total_score=0,
            dimensions=zero_dimensions,
            issues=machine.issues,
        )

    if review is None and not script_owned_engineering:
        return ScoreReport(
            case_id=machine.case_id,
            case_kind=machine.case_kind,
            hard_gate_passed=False,
            base_score=0,
            bonus_score=0,
            total_score=0,
            dimensions=zero_dimensions,
            issues=machine.issues,
        )
    if review is not None and review.critical_issues:
        return ScoreReport(
            case_id=machine.case_id,
            case_kind=machine.case_kind,
            hard_gate_passed=False,
            base_score=0,
            bonus_score=0,
            total_score=0,
            dimensions=zero_dimensions,
            issues=machine.issues,
        )
    if script_owned_engineering and review is not None:
        raise ValueError("script-owned engineering scoring cannot include reviewer evidence")

    bonus_points = BonusEvidence.model_validate(bonus)
    if script_owned_engineering and bonus:
        raise ValueError("script-owned engineering scoring cannot include bonus evidence")
    machine_safety = min(4.0, max(0.0, float(machine.dimension_points["machine_safety"])))
    dimensions = {
        "closed_loop": min(
            BASE_DIMENSION_LIMITS["closed_loop"],
            max(0.0, float(machine.dimension_points["closed_loop"])),
        ),
        "scientific_correctness": min(
            BASE_DIMENSION_LIMITS["scientific_correctness"],
            max(0.0, float(machine.dimension_points["scientific_correctness"])),
        ),
        "reproducibility": min(
            BASE_DIMENSION_LIMITS["reproducibility"],
            max(0.0, float(machine.dimension_points["reproducibility"])),
        ),
        "error_and_safety": min(
            BASE_DIMENSION_LIMITS["error_and_safety"],
            machine_safety + (review.safety_review_points if review is not None else 0),
        ),
        "role_usability": min(
            BASE_DIMENSION_LIMITS["role_usability"],
            review.role_usability_points if review is not None else 0,
        ),
    }
    base_score = round(sum(dimensions.values()), 2)
    if machine.case_kind == "open":
        return ScoreReport(
            case_id=machine.case_id,
            case_kind=machine.case_kind,
            hard_gate_passed=True,
            base_score=round(base_score / 5, 2),
            bonus_score=0,
            total_score=round(base_score / 5, 2),
            dimensions=dimensions,
            issues=machine.issues,
        )
    awarded = (
        (bonus_points.standardization.awarded if bonus_points.standardization else 0)
        + (bonus_points.acceleration.awarded if bonus_points.acceleration else 0)
        + (bonus_points.reproducible_refactor.awarded if bonus_points.reproducible_refactor else 0)
    )
    category_caps = {
        "standardization": 3,
        "acceleration": 3,
        "reproducible_refactor": 4,
    }
    for category, cap in category_caps.items():
        claim = getattr(bonus_points, category)
        if claim is not None and claim.awarded > cap:
            raise ValueError(f"{category} bonus may not exceed {cap}")
    bonus_score = min(10.0, round(awarded, 2))
    return ScoreReport(
        case_id=machine.case_id,
        case_kind=machine.case_kind,
        hard_gate_passed=True,
        base_score=base_score,
        bonus_score=bonus_score,
        total_score=round(base_score + bonus_score, 2),
        dimensions=dimensions,
        issues=machine.issues,
    )


def aggregate_scores(reports: list[ScoreReport]) -> EvaluationSummary:
    total_runs = len(reports)
    fixed_reports = [report for report in reports if report.case_kind != "open"]
    baseline_reports = [report for report in fixed_reports if report.case_kind != "variant"]
    core_reports = [report for report in fixed_reports if report.case_kind == "core"]
    variant_reports = [report for report in fixed_reports if report.case_kind == "variant"]
    open_reports = [report for report in reports if report.case_kind == "open"]

    per_case_base_scores: dict[str, list[float]] = defaultdict(list)
    for report in fixed_reports:
        per_case_base_scores[report.case_id].append(report.base_score)

    per_case_stddev_raw = {
        case_id: _population_standard_deviation(scores)
        for case_id, scores in per_case_base_scores.items()
    }
    per_case_standard_deviation = {
        case_id: round(value, 2) for case_id, value in per_case_stddev_raw.items()
    }
    open_task_scores = {
        case_id: round(sum(case_scores) / len(case_scores), 2)
        for case_id, case_scores in _group_open_scores(open_reports).items()
    }

    critical_failures = sum(1 for report in reports if not report.hard_gate_passed)
    hard_gate_pass_rate = _pass_rate(reports)
    core_hard_gate_pass_rate = _pass_rate(core_reports)
    variant_hard_gate_pass_rate = _pass_rate(variant_reports)
    average_base_score = _average([report.base_score for report in fixed_reports])
    core_average_base_score = _average([report.base_score for report in core_reports])

    baseline_all_passed = not baseline_reports or all(
        report.hard_gate_passed for report in baseline_reports
    )
    variants_passed = (
        not variant_reports
        or variant_hard_gate_pass_rate >= THRESHOLDS["variant_hard_gate_rate"]
    )
    core_average_passed = (
        not core_reports
        or core_average_base_score >= THRESHOLDS["core_average_base_score"]
    )
    stability_passed = all(
        value <= THRESHOLDS["per_case_stddev_max"] for value in per_case_stddev_raw.values()
    )
    passed = (
        baseline_all_passed
        and variants_passed
        and core_average_passed
        and stability_passed
    )
    decisions = {
        "baseline_all_passed": baseline_all_passed,
        "variants_passed": variants_passed,
        "core_average_passed": core_average_passed,
        "stability_passed": stability_passed,
        "passed": passed,
    }

    return EvaluationSummary(
        total_runs=total_runs,
        hard_gate_pass_rate=hard_gate_pass_rate,
        core_hard_gate_pass_rate=core_hard_gate_pass_rate,
        variant_hard_gate_pass_rate=variant_hard_gate_pass_rate,
        average_base_score=average_base_score,
        core_average_base_score=core_average_base_score,
        per_case_standard_deviation=per_case_standard_deviation,
        open_task_scores=open_task_scores,
        critical_failures=critical_failures,
        passed=passed,
        thresholds=THRESHOLDS.copy(),
        decisions=decisions,
        reports=[
            f"{report.case_id}: hard_gate={report.hard_gate_passed}, "
            f"base={report.base_score}, bonus={report.bonus_score}, total={report.total_score}"
            for report in reports
        ],
    )


def _group_open_scores(reports: list[ScoreReport]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for report in reports:
        grouped[report.case_id].append(report.base_score)
    return grouped


def _population_standard_deviation(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return sqrt(variance)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _pass_rate(reports: list[ScoreReport]) -> float:
    if not reports:
        return 0.0
    return sum(1 for report in reports if report.hard_gate_passed) / len(reports)
