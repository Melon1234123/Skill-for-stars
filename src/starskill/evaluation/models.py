"""Typed evaluation models for the StarSkill evaluation layer."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PersonaName = Literal[
    "student",
    "teacher",
    "outreach",
    "amateur_observer",
    "undergraduate_researcher",
    "researcher",
    "reviewer",
]

TaskFamily = Literal[
    "observation",
    "catalog_query",
    "cone_search",
    "crossmatch",
    "ambiguous_input",
    "service_failure",
    "scientific_adversarial",
]

TaskExpectedOutcome = Literal["success", "clarify", "structured_failure", "correct_claim"]


class PersonaProfile(EvaluationModel):
    """Stable requirements for one simulated StarSkill user persona."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: PersonaName
    knowledge_level: str = Field(min_length=1)
    goals: tuple[str, ...] = Field(min_length=1)
    preferred_answer_style: str = Field(min_length=1)
    expected_evidence: tuple[str, ...] = Field(min_length=1)
    common_mistakes: tuple[str, ...] = Field(min_length=1)
    failure_sensitivity: Literal["low", "medium", "high"]


class GeneratedEvaluationTask(EvaluationModel):
    """One portable, deterministic persona-evaluation task record."""

    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    persona: PersonaName
    persona_profile: PersonaProfile
    task_family: TaskFamily
    template_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    task_input: dict[str, Any]
    required_tools: tuple[str, ...] = Field(min_length=1)
    expected_evidence: tuple[str, ...] = Field(min_length=1)
    expected_outcome: TaskExpectedOutcome


class ToolCallRecord(EvaluationModel):
    """One external-Agent tool call captured for self-play evidence."""

    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "failed"] = "success"


class AgentResponse(EvaluationModel):
    """LLM-provider-neutral response returned by an external harness."""

    response_markdown: str
    tool_calls: tuple[ToolCallRecord, ...] = Field(default_factory=tuple)
    artifacts: dict[str, str] = Field(default_factory=dict)


class SelfPlayPrompt(EvaluationModel):
    """Portable prompt supplied to an AgentProvider for one generated task."""

    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    task: GeneratedEvaluationTask
    prompt: str = Field(min_length=1)
    requirements: tuple[str, ...] = Field(min_length=1)


class SelfPlayDimensionScore(EvaluationModel):
    score: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[str, ...] = Field(default_factory=tuple)


class SelfPlayScore(EvaluationModel):
    """Transparent heuristic score for a captured self-play response."""

    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    status: Literal["completed", "failed"]
    task_success: SelfPlayDimensionScore
    scientific_correctness: SelfPlayDimensionScore
    tool_selection: SelfPlayDimensionScore
    evidence_quality: SelfPlayDimensionScore
    reproducibility: SelfPlayDimensionScore
    persona_satisfaction: SelfPlayDimensionScore
    overall_score: float = Field(ge=0, le=1)
    failure: dict[str, str] | None = None


class PersonaSatisfaction(EvaluationModel):
    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    persona: PersonaName
    satisfaction: float = Field(ge=0, le=1)
    satisfied: bool
    reasons: tuple[str, ...] = Field(min_length=1)


class SelfPlayTrace(EvaluationModel):
    """Validated in-memory representation of a persisted self-play run."""

    run_id: str = Field(min_length=1)
    run_dir: str = Field(min_length=1)
    prompt: SelfPlayPrompt
    response_markdown: str
    tool_calls: tuple[ToolCallRecord, ...]
    score: SelfPlayScore
    satisfaction: PersonaSatisfaction
    artifact_sha256: dict[str, str] = Field(default_factory=dict)


class ArtifactExpectation(EvaluationModel):
    path: str
    non_empty: bool = True
    kind: Literal["file", "json", "csv", "image", "markdown"] = "file"


class JsonAssertion(EvaluationModel):
    file: str
    pointer: str
    equals: str | int | float | bool | list[Any] | None = None
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


class ExecutionRecordV1(EvaluationModel):
    recorder: Literal["starskill.evaluation.runner"]
    schema_version: Literal[1]
    case_id: str = Field(min_length=1)
    case_kind: Literal["core", "variant", "failure", "open"]
    role: Literal["teacher", "outreach", "research"]
    workflow: Literal[
        "validate", "resolve", "ephemeris", "plan", "run", "relationship", "fetch-image"
    ]
    task_path: str = Field(min_length=1)
    run_dir: str = Field(min_length=1)
    working_directory: str = Field(min_length=1)
    command_argv: list[str] = Field(min_length=5)
    return_code: int
    started_at: str = Field(min_length=1)
    completed_at: str = Field(min_length=1)
    stdout_file: str = Field(min_length=1)
    stderr_file: str = Field(min_length=1)
    exit_code_file: str = Field(min_length=1)
    artifact_sha256: dict[str, str]


class ExecutionRecord(ExecutionRecordV1):
    schema_version: Literal[2]
    source_path: str = Field(min_length=1)
    environment: dict[str, str]


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
