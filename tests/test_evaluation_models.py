import pytest
from pydantic import ValidationError

from starskill.evaluation.models import (
    EvaluationCase,
    EvaluationSummary,
    JsonAssertion,
    NumericAssertion,
)


def test_evaluation_case_accepts_expected_task_contract() -> None:
    case = EvaluationCase.model_validate(
        {
            "case_id": "core-m42-beijing",
            "kind": "core",
            "role": "teacher",
            "task_path": "examples/observation_m42_beijing.json",
            "workflow": "run",
            "expected_exit_code": 0,
            "expected_status": "success",
            "required_files": ["run.json"],
            "artifacts": [],
            "json_assertions": [
                {"file": "run.json", "pointer": "/status", "equals": "success"}
            ],
            "numeric_assertions": [],
            "review_focus": ["confirm workflow output integrity"],
            "prompt_file": "prompts/evaluation/core-m42-beijing.md",
        }
    )

    assert case.case_id == "core-m42-beijing"
    assert case.required_files == ["run.json"]
    assert case.review_focus == ["confirm workflow output integrity"]


def test_evaluation_case_requires_review_focus() -> None:
    with pytest.raises(ValidationError, match="review_focus"):
        EvaluationCase.model_validate(
            {
                "case_id": "core-m42-beijing",
                "kind": "core",
                "role": "teacher",
                "task_path": "examples/observation_m42_beijing.json",
                "workflow": "run",
                "expected_exit_code": 0,
                "expected_status": "success",
                "review_focus": [],
                "prompt_file": "prompts/evaluation/core-m42-beijing.md",
            }
        )


def test_numeric_assertion_requires_non_negative_tolerance() -> None:
    with pytest.raises(ValidationError, match="absolute_tolerance"):
        NumericAssertion.model_validate(
            {
                "file": "run.json",
                "pointer": "/metrics/score",
                "expected": 1.0,
                "absolute_tolerance": -0.1,
            }
        )


def test_json_assertion_accepts_an_empty_array_expectation() -> None:
    assertion = JsonAssertion.model_validate(
        {"file": "result.json", "pointer": "/windows", "equals": []}
    )

    assert assertion.equals == []


def test_evaluation_summary_accepts_threshold_metadata_and_decisions() -> None:
    summary = EvaluationSummary.model_validate(
        {
            "total_runs": 1,
            "hard_gate_pass_rate": 1.0,
            "core_hard_gate_pass_rate": 1.0,
            "variant_hard_gate_pass_rate": 1.0,
            "average_base_score": 100.0,
            "core_average_base_score": 100.0,
            "per_case_standard_deviation": {"case-1": 0.0},
            "open_task_scores": {},
            "critical_failures": 0,
            "passed": True,
            "thresholds": {
                "baseline_hard_gate_rate": 1.0,
                "variant_hard_gate_pass_rate": 0.9,
                "core_average_base_score": 80.0,
                "per_case_stddev_max": 5.0,
            },
            "decisions": {
                "baseline_all_passed": True,
                "variants_passed": True,
                "core_average_passed": True,
                "stability_passed": True,
                "passed": True,
            },
            "reports": ["case-1: hard_gate=True, base=100.0, bonus=0.0, total=100.0"],
        }
    )

    assert summary.thresholds["per_case_stddev_max"] == 5.0
    assert summary.decisions["passed"] is True
