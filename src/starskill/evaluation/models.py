"""Typed evaluation models for the StarSkill evaluation layer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactExpectation(EvaluationModel):
    path: str
    non_empty: bool = True
    kind: Literal["file", "json", "csv", "image", "markdown"] = "file"


class JsonAssertion(EvaluationModel):
    file: str
    pointer: str
    equals: str | int | float | bool | None = None
    exists: bool = True

    @field_validator("pointer")
    @classmethod
    def pointer_must_use_supported_json_pointer_syntax(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("pointer must start with '/'")
        tokens = value.split("/")[1:]
        if any(token == "*" or "[" in token or "]" in token for token in tokens):
            raise ValueError("pointer must not use array wildcard syntax")
        return value


class NumericAssertion(EvaluationModel):
    file: str
    pointer: str
    expected: float
    absolute_tolerance: float = Field(ge=0)

    @field_validator("pointer")
    @classmethod
    def pointer_must_use_supported_json_pointer_syntax(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("pointer must start with '/'")
        tokens = value.split("/")[1:]
        if any(token == "*" or "[" in token or "]" in token for token in tokens):
            raise ValueError("pointer must not use array wildcard syntax")
        return value


class CsvAssertion(EvaluationModel):
    file: str
    column: str = Field(min_length=1)
    expected: float
    absolute_tolerance: float = Field(ge=0)
    row: int = Field(default=0, ge=0)


class EvaluationCase(EvaluationModel):
    case_id: str = Field(min_length=1)
    kind: Literal["core", "variant", "failure", "open"]
    role: Literal["teacher", "outreach", "research"]
    task_path: str
    workflow: Literal[
        "validate", "resolve", "ephemeris", "plan", "run", "relationship", "fetch-image"
    ]
    expected_exit_code: int = Field(ge=0, le=9)
    expected_status: Literal["success", "degraded", "failed", "not_applicable"]
    required_files: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactExpectation] = Field(default_factory=list)
    json_assertions: list[JsonAssertion] = Field(default_factory=list)
    numeric_assertions: list[NumericAssertion] = Field(default_factory=list)
    csv_assertions: list[CsvAssertion] = Field(default_factory=list)
    review_focus: list[str] = Field(min_length=1)
    prompt_file: str


class CheckIssue(EvaluationModel):
    code: str
    message: str
    evidence_path: str | None = None
    severity: Literal["info", "warning", "critical"]


class MachineCheckReport(EvaluationModel):
    case_id: str
    case_kind: Literal["core", "variant", "failure", "open"]
    hard_gate_passed: bool
    exit_code: int
    dimension_points: dict[str, float]
    issues: list[CheckIssue]
    checked_files: list[str]


class ReviewReport(EvaluationModel):
    case_id: str
    reviewer_role: Literal["teacher", "outreach", "research", "adjudicator"]
    role_usability_points: float = Field(ge=0, le=5)
    safety_review_points: float = Field(ge=0, le=6)
    critical_issues: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    recommendation: Literal["pass", "review", "fail"]


class ScoreReport(EvaluationModel):
    case_id: str
    case_kind: Literal["core", "variant", "failure", "open"]
    hard_gate_passed: bool
    base_score: float = Field(ge=0, le=100)
    bonus_score: float = Field(ge=0, le=10)
    total_score: float = Field(ge=0, le=110)
    dimensions: dict[str, float]
    issues: list[CheckIssue]


class EvaluationSummary(EvaluationModel):
    total_runs: int = Field(ge=0)
    hard_gate_pass_rate: float = Field(ge=0, le=1)
    core_hard_gate_pass_rate: float = Field(ge=0, le=1)
    variant_hard_gate_pass_rate: float = Field(ge=0, le=1)
    average_base_score: float = Field(ge=0, le=100)
    core_average_base_score: float = Field(ge=0, le=100)
    per_case_standard_deviation: dict[str, float]
    open_task_scores: dict[str, float]
    critical_failures: int = Field(ge=0)
    passed: bool
    thresholds: dict[str, float]
    decisions: dict[str, bool]
    reports: list[str]
