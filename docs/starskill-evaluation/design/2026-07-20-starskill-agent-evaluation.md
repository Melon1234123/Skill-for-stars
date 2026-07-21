# StarSkill Agent Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral evaluation layer that lets externally orchestrated worker and reviewer Agents run StarSkill workflows, validates their artifacts deterministically, and produces quantitative closed-loop performance reports.

**Architecture:** Keep Agent creation outside the repository. Add typed evaluation models and case manifests under `src/starskill/evaluation` and `evaluation/`, implement deterministic artifact checks and scoring, and expose a replay CLI that accepts captured worker runs and reviewer JSON. Preserve the existing astronomy calculations and `run-starskill` workflow as the product under test.

**Tech Stack:** Python 3.11+, Pydantic 2.x, standard library (`json`, `hashlib`, `pathlib`, `argparse`), existing StarSkill CLI and schemas, Pytest, Markdown/JSON/CSV artifacts, Pillow only through existing project dependencies for image checks.

## Global Constraints

- The product remains an AI-callable `run-starskill` Skills package; do not add a web UI or PPT/PDF output.
- The repository must not call an LLM API or create child Agents; Codex or another host performs external Agent orchestration.
- Fixed evaluation cases use validated real caches or response snapshots; live SIMBAD/SDSS checks are separate smoke tests.
- Three fixed cases are repeated three times each, for 9 independent Worker runs.
- The six parameter variants must have a hard-gate pass rate of at least 90%; with six samples this is 6/6.
- Core average base score must be at least 80/100, and each fixed case's three-run score standard deviation must be at most 5.
- Hard-gate failures cannot be repaired by bonus points.
- Never accept fabricated coordinates, images, sources, success states, weather guarantees, safety guarantees, or physical Moon-Jupiter proximity claims.
- Machine checks are authoritative for exits, files, schemas, values, sources, hashes, and image properties; reviewer Agents add role and boundary judgments.
- Do not initialize or rewrite Git metadata in `F:\Skill-for-stars`; the current project root is not a Git worktree.

---

## File Map

Create the following focused modules and data files:

- `src/starskill/evaluation/__init__.py`: public evaluation imports only.
- `src/starskill/evaluation/models.py`: Pydantic models for cases, assertions, machine checks, reviews, scores, and aggregate summaries.
- `src/starskill/evaluation/cases.py`: case loading, path resolution, JSON-pointer reads, and case-kind validation.
- `src/starskill/evaluation/checks.py`: deterministic run checks with no model or network calls.
- `src/starskill/evaluation/scoring.py`: hard-gate logic, base score calculation, bonus validation, and aggregate statistics.
- `src/starskill/evaluation/reporting.py`: JSON and Markdown report serialization.
- `scripts/evaluate_starskill.py`: replay CLI; it consumes saved Worker outputs and reviewer JSON but never launches an Agent.
- `evaluation/cases/core/*.json`: the three fixed cases.
- `evaluation/cases/variants/*.json`: six parameter variants.
- `evaluation/cases/failures/*.json`: the six explicit failure cases.
- `evaluation/cases/open/*.json`: three open pressure task definitions.
- `evaluation/prompts/workers/*.md`: the three Worker role prompts.
- `evaluation/prompts/reviewers/*.md`: the three rotating reviewer prompts and the escalation prompt.
- `evaluation/README.md`: external orchestration and replay protocol.
- `tests/test_evaluation_models.py`: case and result model contracts.
- `tests/test_evaluation_checks.py`: deterministic artifact and process checks.
- `tests/test_evaluation_scoring.py`: hard gates, dimensions, bonuses, and aggregate statistics.
- `tests/test_evaluation_reporting.py`: JSON/Markdown output contracts.
- `tests/test_evaluation_cli.py`: replay CLI behavior.
- `tests/test_evaluation_cases.py`: all required case and prompt files are present and valid.
- `.gitignore`: add `evaluation-runs/` so captured runs are not accidentally committed.
- `skills/run-starskill/SKILL.md`: add the evaluation/replay boundary and required captured fields.
- `skills/run-starskill/references/cli-contract.md`: add evaluation artifact and exit-code capture requirements.

Do not modify `src/starskill/ephemeris_calculator.py`, `observation_planner.py`, `target_resolver.py`, `public_data_fetcher.py`, or the existing CLI command behavior unless a contract test demonstrates a specific evaluation integration defect.

## Task 1: Define Evaluation Models and Case Manifests

**Files:**
- Create: `src/starskill/evaluation/__init__.py`
- Create: `src/starskill/evaluation/models.py`
- Create: `src/starskill/evaluation/cases.py`
- Create: `evaluation/cases/core/core-m42-beijing.json`
- Create: `evaluation/cases/core/core-moon-jupiter-shanghai.json`
- Create: `evaluation/cases/core/core-m51-sdss.json`
- Create: `evaluation/cases/variants/variant-m42-location-time.json`
- Create: `evaluation/cases/variants/variant-m42-no-window.json`
- Create: `evaluation/cases/variants/variant-moon-jupiter-location-time.json`
- Create: `evaluation/cases/variants/variant-moon-jupiter-interval.json`
- Create: `evaluation/cases/variants/variant-m51-request-parameters.json`
- Create: `evaluation/cases/variants/variant-m51-cache-reuse.json`
- Create: `evaluation/cases/failures/failure-invalid-observation-input.json`
- Create: `evaluation/cases/failures/failure-invalid-timezone.json`
- Create: `evaluation/cases/failures/failure-target-service.json`
- Create: `evaluation/cases/failures/failure-no-observation-window.json`
- Create: `evaluation/cases/failures/failure-sdss-service.json`
- Create: `evaluation/cases/failures/failure-sdss-invalid-response.json`
- Create: `evaluation/cases/open/open-teacher-boundary.json`
- Create: `evaluation/cases/open/open-outreach-boundary.json`
- Create: `evaluation/cases/open/open-research-boundary.json`
- Test: `tests/test_evaluation_models.py`
- Test: `tests/test_evaluation_cases.py`

**Interfaces:**
- Produces `EvaluationCase`, `ArtifactExpectation`, `JsonAssertion`, `NumericAssertion`, `MachineCheckReport`, `ReviewReport`, `ScoreReport`, and `EvaluationSummary` Pydantic models.
- Produces `load_case(path: Path) -> EvaluationCase` and `load_cases(root: Path) -> list[EvaluationCase]`.
- Later tasks consume `EvaluationCase.expected_exit_code`, `EvaluationCase.required_files`, `EvaluationCase.json_assertions`, `EvaluationCase.numeric_assertions`, and `EvaluationCase.review_focus`.

- [ ] **Step 1: Write failing model tests.**

```python
from pathlib import Path

from starskill.evaluation.cases import load_case, load_cases
from starskill.evaluation.models import EvaluationCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_m42_case_has_workflow_and_audit_contract() -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")

    assert isinstance(case, EvaluationCase)
    assert case.case_id == "core-m42-beijing"
    assert case.kind == "core"
    assert case.role == "teacher"
    assert case.workflow == "run"
    assert case.expected_exit_code == 0
    assert "run.json" in case.required_files
    assert "/status" in {item.pointer for item in case.json_assertions}


def test_all_case_kinds_have_unique_ids_and_review_focus() -> None:
    cases = load_cases(PROJECT_ROOT / "evaluation/cases")

    assert len(cases) == 18
    assert len({case.case_id for case in cases}) == 18
    assert {case.kind for case in cases} == {"core", "variant", "failure", "open"}
    assert all(case.review_focus for case in cases)
```

- [ ] **Step 2: Run the focused tests and verify they fail for missing models/files.**

Run:

```powershell
python -m pytest tests/test_evaluation_models.py tests/test_evaluation_cases.py -q
```

Expected: FAIL because `starskill.evaluation` and the case files do not exist yet.

- [ ] **Step 3: Add the typed models and loader.**

Implement `models.py` with these exact fields and constraints:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class NumericAssertion(EvaluationModel):
    file: str
    pointer: str
    expected: float
    absolute_tolerance: float = Field(ge=0)


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
    review_focus: list[str] = Field(min_length=1)
    prompt_file: str


class CheckIssue(EvaluationModel):
    code: str
    message: str
    evidence_path: str | None = None
    severity: Literal["info", "warning", "critical"]


class MachineCheckReport(EvaluationModel):
    case_id: str
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
    reports: list[str]
```

Implement `cases.py` using `Path.read_text(encoding="utf-8")`, Pydantic validation, deterministic sorted traversal, and a JSON-pointer reader that accepts `/status` and nested object keys but rejects array wildcard syntax. Resolve `task_path` and `prompt_file` relative to the project root supplied to `load_case`; never construct shell commands from case text.

Create the 15 manifests with these exact categories and workflows:

| IDs | Role | Workflow | Expected exit | Kind |
|---|---|---|---:|---|
| `core-m42-beijing` | teacher | `run` | 0 | core |
| `core-moon-jupiter-shanghai` | outreach | `relationship` | 0 | core |
| `core-m51-sdss` | research | `fetch-image` | 0 | core |
| `variant-m42-location-time`, `variant-m42-no-window` | teacher | `run` | 0 | variant |
| `variant-moon-jupiter-location-time`, `variant-moon-jupiter-interval` | outreach | `relationship` | 0 | variant |
| `variant-m51-request-parameters`, `variant-m51-cache-reuse` | research | `fetch-image` | 0 | variant |
| `failure-invalid-observation-input` | teacher | `validate` | 2 | failure |
| `failure-invalid-timezone` | teacher | `validate` | 2 | failure |
| `failure-target-service` | teacher | `run` | 4 | failure |
| `failure-no-observation-window` | teacher | `run` | 0 | failure |
| `failure-sdss-service` | research | `fetch-image` | 7 | failure |
| `failure-sdss-invalid-response` | research | `fetch-image` | 9 | failure |
| `open-teacher-boundary` | teacher | `run` | 0 | open |
| `open-outreach-boundary` | outreach | `relationship` | 2 | open |
| `open-research-boundary` | research | `fetch-image` | 2 | open |

The three core task paths must point to the existing examples. Variants must only use fields already accepted by `ObservationTask`, `SolarSystemRelationshipTask`, or `SDSSImageRequest`. Failure cases must state the injected backend or fixture condition in `review_focus` so a replay runner can distinguish a product error from a test setup error.

- [ ] **Step 4: Run the focused tests and verify they pass.**

Run:

```powershell
python -m pytest tests/test_evaluation_models.py tests/test_evaluation_cases.py -q
```

Expected: PASS with the 15 manifests loaded and validated.

- [ ] **Step 5: Commit when a real Git worktree is available.**

```powershell
git add src/starskill/evaluation evaluation/cases tests/test_evaluation_models.py tests/test_evaluation_cases.py
git commit -m "feat: define agent evaluation cases"
```

In the current workspace, do not initialize Git; record this checkpoint without committing.

## Task 2: Implement Deterministic Artifact and Process Checks

**Files:**
- Create: `src/starskill/evaluation/checks.py`
- Create: `tests/test_evaluation_checks.py`

**Interfaces:**
- Consumes: `EvaluationCase`, `Path run_dir`, captured `return_code`, `stdout`, and `stderr`.
- Produces: `check_run(case, run_dir, return_code, stdout, stderr) -> MachineCheckReport`.
- Later tasks consume `MachineCheckReport.hard_gate_passed`, `dimension_points`, `issues`, and `checked_files`.

- [ ] **Step 1: Write failing checks for success, missing artifacts, wrong hashes, and expected failure.**

```python
import json
from pathlib import Path

from starskill.evaluation.cases import load_case
from starskill.evaluation.checks import check_run


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core_m42_check_requires_a_complete_audit_bundle(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    (tmp_path / "run.json").write_text(
        json.dumps({"status": "success", "artifacts": []}), encoding="utf-8"
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "missing_artifact" for issue in report.issues)


def test_expected_validation_failure_is_not_a_hard_gate_failure(tmp_path) -> None:
    case = load_case(
        PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"
    )
    (tmp_path / "stderr.json").write_text(
        json.dumps({"valid": False, "error": "validation_error"}), encoding="utf-8"
    )

    report = check_run(case, tmp_path, 2, "", (tmp_path / "stderr.json").read_text())

    assert report.hard_gate_passed is True
    assert report.exit_code == 2


def test_hash_mismatch_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    (tmp_path / "run.json").write_text(
        json.dumps({
            "status": "success",
            "artifacts": [{"path": "run.json", "bytes": 1, "sha256": "0" * 64}],
        }), encoding="utf-8"
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "artifact_hash_mismatch" for issue in report.issues)
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run:

```powershell
python -m pytest tests/test_evaluation_checks.py -q
```

Expected: FAIL because `check_run` is not implemented.

- [ ] **Step 3: Implement the checker with explicit, testable sub-checks.**

Use this public shape and keep each sub-check pure except for reading files:

```python
def check_run(
    case: EvaluationCase,
    run_dir: Path,
    return_code: int,
    stdout: str,
    stderr: str,
) -> MachineCheckReport:
    issues: list[CheckIssue] = []
    checked_files: list[str] = []
    points = {
        "closed_loop": 0.0,
        "scientific_correctness": 0.0,
        "reproducibility": 0.0,
        "machine_safety": 0.0,
    }
    _check_exit_code(case, return_code, issues)
    _check_required_artifacts(case, run_dir, checked_files, issues, points)
    _check_json_assertions(case, run_dir, checked_files, issues, points)
    _check_numeric_assertions(case, run_dir, checked_files, issues, points)
    _check_manifest_hashes(case, run_dir, checked_files, issues, points)
    _check_failure_artifacts(case, run_dir, stdout, stderr, issues, points)
    _check_image_properties(case, run_dir, checked_files, issues, points)
    hard_gate_passed = not any(issue.severity == "critical" for issue in issues)
    return MachineCheckReport(
        case_id=case.case_id,
        hard_gate_passed=hard_gate_passed,
        exit_code=return_code,
        dimension_points=points,
        issues=issues,
        checked_files=checked_files,
    )
```

Award deterministic base points only when the corresponding evidence exists: closed-loop points max 40, scientific points max 25, reproducibility points max 20, and machine-safety points max 4. The remaining safety points and all role-usability points come from the structured reviewer report in Task 3. A successful check for a failure case means the expected error path was observed, not that the command returned zero.

Implement JSON-pointer reads without adding a dependency. Verify `run.json` artifact paths remain inside `run_dir` before opening them; reject absolute paths and `..` traversal. For images use Pillow's format, dimensions, verification, and non-uniform pixel check. Do not make network calls from this module.

- [ ] **Step 4: Add boundary tests for all required checker behaviors.**

Add tests covering missing `run.json`, an empty required file, an unexpected exit code, a JSON assertion mismatch, a numeric value outside tolerance, path traversal, a corrupt SHA-256, a corrupt JPEG, an invalid SDSS size, a valid degraded run with exit code 5, and an expected target-service failure with exit code 4.

- [ ] **Step 5: Run the focused and existing tests.**

Run:

```powershell
python -m pytest tests/test_evaluation_checks.py tests/test_pipeline.py tests/test_cli.py -q
```

Expected: PASS; existing StarSkill workflow behavior must remain unchanged.

- [ ] **Step 6: Commit when a real Git worktree is available.**

```powershell
git add src/starskill/evaluation/checks.py tests/test_evaluation_checks.py
git commit -m "feat: add deterministic evaluation checks"
```

## Task 3: Implement Reviewer Schema, Scoring, and Aggregation

**Files:**
- Create: `src/starskill/evaluation/scoring.py`
- Create: `tests/test_evaluation_scoring.py`

**Interfaces:**
- Consumes: `MachineCheckReport`, zero or one normal `ReviewReport`, optional bonus evidence.
- Produces: `score_case(machine, review, bonus) -> ScoreReport` and `aggregate_scores(reports) -> EvaluationSummary`.

- [ ] **Step 1: Write failing scoring tests.**

```python
from starskill.evaluation.models import MachineCheckReport, ReviewReport
from starskill.evaluation.scoring import aggregate_scores, score_case


def passing_machine(case_id: str) -> MachineCheckReport:
    return MachineCheckReport(
        case_id=case_id,
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


def passing_review(case_id: str) -> ReviewReport:
    return ReviewReport(
        case_id=case_id,
        reviewer_role="teacher",
        role_usability_points=5,
        safety_review_points=6,
        confidence=0.9,
        recommendation="pass",
    )


def test_score_case_combines_machine_and_review_points() -> None:
    report = score_case(passing_machine("case-1"), passing_review("case-1"), {})

    assert report.hard_gate_passed is True
    assert report.base_score == 100
    assert report.bonus_score == 0
    assert report.total_score == 100


def test_critical_machine_issue_cannot_be_repaired_by_bonus() -> None:
    machine = passing_machine("case-2").model_copy(update={"hard_gate_passed": False})
    report = score_case(machine, passing_review("case-2"), {"standardization": 3})

    assert report.hard_gate_passed is False
    assert report.base_score == 0
    assert report.bonus_score == 0
    assert report.total_score == 0


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
    assert summary.passed is True
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run:

```powershell
python -m pytest tests/test_evaluation_scoring.py -q
```

Expected: FAIL because the scoring functions are not implemented.

- [ ] **Step 3: Implement hard-gate-first scoring.**

Use the following deterministic shape:

```python
BASE_DIMENSION_LIMITS = {
    "closed_loop": 40.0,
    "scientific_correctness": 25.0,
    "reproducibility": 20.0,
    "error_and_safety": 10.0,
    "role_usability": 5.0,
}


def score_case(
    machine: MachineCheckReport,
    review: ReviewReport | None,
    bonus: dict[str, float],
) -> ScoreReport:
    if not machine.hard_gate_passed:
        return ScoreReport(
            case_id=machine.case_id,
            hard_gate_passed=False,
            base_score=0,
            bonus_score=0,
            total_score=0,
            dimensions={name: 0 for name in BASE_DIMENSION_LIMITS},
            issues=machine.issues,
        )
    if review is None or review.critical_issues:
        return ScoreReport(
            case_id=machine.case_id,
            hard_gate_passed=False,
            base_score=0,
            bonus_score=0,
            total_score=0,
            dimensions={name: 0 for name in BASE_DIMENSION_LIMITS},
            issues=machine.issues,
        )
    dimensions = {
        "closed_loop": machine.dimension_points["closed_loop"],
        "scientific_correctness": machine.dimension_points["scientific_correctness"],
        "reproducibility": machine.dimension_points["reproducibility"],
        "error_and_safety": machine.dimension_points["machine_safety"]
        + review.safety_review_points,
        "role_usability": review.role_usability_points,
    }
    base_score = round(sum(dimensions.values()), 2)
    bonus_score = min(
        10.0,
        sum(float(bonus.get(name, 0)) for name in (
            "standardization", "acceleration", "reproducible_refactor"
        )),
    )
    return ScoreReport(
        case_id=machine.case_id,
        hard_gate_passed=True,
        base_score=base_score,
        bonus_score=bonus_score,
        total_score=round(base_score + bonus_score, 2),
        dimensions=dimensions,
        issues=machine.issues,
    )
```

Reject review safety points above 6, role points above 5, and bonus categories above 3, 3, and 4 respectively through Pydantic validation or a structured scoring issue. `aggregate_scores` must compute hard-gate rate, average base score, per-case population standard deviation, critical failure count, and the approved pass line: baseline all pass, variants at least 90%, core average at least 80, and each fixed case standard deviation at most 5. Open-task scores remain in separate fields and do not affect the core pass boolean.

- [ ] **Step 4: Add score boundary tests.**

Test a missing reviewer, a critical reviewer issue, maximum bonus points, bonus over the cap, one failed variant out of six, a standard deviation exactly 5, and a standard deviation greater than 5. Assert that failed hard gates produce zero base and bonus points and preserve the original critical issue.

- [ ] **Step 5: Run the focused and full unit tests.**

Run:

```powershell
python -m pytest tests/test_evaluation_scoring.py tests/test_evaluation_models.py -q
python -m pytest -q
```

Expected: both commands PASS; the existing test count may increase only from the new evaluation tests.

- [ ] **Step 6: Commit when a real Git worktree is available.**

```powershell
git add src/starskill/evaluation/scoring.py tests/test_evaluation_scoring.py
git commit -m "feat: score agent evaluation runs"
```

## Task 4: Add Replay CLI and Machine/Markdown Reports

**Files:**
- Create: `src/starskill/evaluation/reporting.py`
- Create: `scripts/evaluate_starskill.py`
- Create: `tests/test_evaluation_reporting.py`
- Create: `tests/test_evaluation_cli.py`

**Interfaces:**
- Consumes: case JSON, a saved run directory, captured `stdout`, `stderr`, return code, and optional reviewer JSON.
- Produces: `machine_checks.json`, `score.json`, and `summary.md` without invoking a network or a model.

- [ ] **Step 1: Write failing replay and report tests.**

```python
import json
from pathlib import Path

from scripts.evaluate_starskill import main


def test_replay_command_writes_machine_and_score_reports(tmp_path) -> None:
    case = Path("evaluation/cases/failures/failure-invalid-timezone.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stderr.json").write_text(
        json.dumps({"valid": False, "error": "validation_error"}), encoding="utf-8"
    )
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps({
            "case_id": "failure-invalid-timezone",
            "reviewer_role": "teacher",
            "role_usability_points": 5,
            "safety_review_points": 6,
            "critical_issues": [],
            "issues": [],
            "confidence": 0.9,
            "recommendation": "pass",
        }), encoding="utf-8"
    )
    output = tmp_path / "report"

    assert main([
        "replay",
        "--case", str(case),
        "--run-dir", str(run_dir),
        "--return-code", "2",
        "--stderr-file", str(run_dir / "stderr.json"),
        "--review-file", str(review),
        "--output-dir", str(output),
    ]) == 0
    assert (output / "machine_checks.json").is_file()
    assert (output / "score.json").is_file()
    assert (output / "summary.md").is_file()
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run:

```powershell
python -m pytest tests/test_evaluation_reporting.py tests/test_evaluation_cli.py -q
```

Expected: FAIL because the replay CLI and report serializer are missing.

- [ ] **Step 3: Implement JSON/Markdown reporting and the replay CLI.**

The CLI must expose exactly these subcommands:

```text
python scripts/evaluate_starskill.py replay --case CASE --run-dir RUN_DIR --return-code N --stdout-file FILE --stderr-file FILE --review-file FILE --output-dir OUTPUT_DIR
python scripts/evaluate_starskill.py aggregate --score-root SCORE_ROOT --output-dir OUTPUT_DIR
```

`--stdout-file`, `--stderr-file`, and `--review-file` are optional only for workflows whose case manifest does not require them. Validate all paths before reading; reject output directories that are inside the input run directory. Write reports using UTF-8 and stable `indent=2`, `sort_keys=True` JSON. The Markdown report must contain the case ID, hard-gate status, all five base dimensions, bonus evidence, checked artifact paths, critical issues, reviewer recommendation, and the distinction between calculated facts, rule-based conclusions, and human review.

Implement `aggregate` to load all `score.json` files below `--score-root`, require unique case/run IDs, and serialize the `EvaluationSummary` plus a Markdown table. It must not silently skip malformed or incomplete reports.

- [ ] **Step 4: Add CLI error-path tests.**

Cover a missing case file, malformed reviewer JSON, an output path traversal attempt, a malformed score file during aggregation, and a mixed directory containing one incomplete run. Each error must return a nonzero exit code and structured stderr JSON; no partial success report may claim the failed item passed.

- [ ] **Step 5: Run CLI and full tests.**

Run:

```powershell
python -m pytest tests/test_evaluation_reporting.py tests/test_evaluation_cli.py -q
python -m pytest -q
python scripts/evaluate_starskill.py --help
```

Expected: focused tests and the full suite PASS; help lists `replay` and `aggregate`.

- [ ] **Step 6: Commit when a real Git worktree is available.**

```powershell
git add src/starskill/evaluation/reporting.py scripts/evaluate_starskill.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py
git commit -m "feat: replay and report agent evaluations"
```

## Task 5: Add External Agent Protocol, Prompts, and Skill Documentation

**Files:**
- Create: `evaluation/prompts/workers/teacher.md`
- Create: `evaluation/prompts/workers/outreach.md`
- Create: `evaluation/prompts/workers/research.md`
- Create: `evaluation/prompts/reviewers/teacher-review.md`
- Create: `evaluation/prompts/reviewers/outreach-review.md`
- Create: `evaluation/prompts/reviewers/research-review.md`
- Create: `evaluation/prompts/reviewers/adjudicator.md`
- Create: `evaluation/README.md`
- Modify: `skills/run-starskill/SKILL.md`
- Modify: `skills/run-starskill/references/cli-contract.md`
- Modify: `.gitignore`
- Test: `tests/test_evaluation_cases.py`

**Interfaces:**
- Consumes: case manifests and `run-starskill` CLI contract.
- Produces: prompts that instruct external Agents to preserve raw outputs, and documentation that describes replay without claiming repository-side Agent orchestration.

- [ ] **Step 1: Write failing documentation contract tests.**

```python
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_worker_prompts_require_real_artifacts_and_exit_codes() -> None:
    for name in ("teacher", "outreach", "research"):
        text = (PROJECT_ROOT / f"evaluation/prompts/workers/{name}.md").read_text(
            encoding="utf-8"
        )
        assert "exit code" in text.lower()
        assert "不要伪造" in text
        assert "tool_calls.jsonl" in text


def test_evaluation_readme_documents_external_orchestration() -> None:
    text = (PROJECT_ROOT / "evaluation/README.md").read_text(encoding="utf-8")

    assert "不创建 Agent" in text
    assert "evaluate_starskill.py replay" in text
    assert "live smoke" in text.lower()
```

- [ ] **Step 2: Run documentation tests and verify they fail.**

Run:

```powershell
python -m pytest tests/test_evaluation_cases.py -q
```

Expected: FAIL because prompts and evaluation documentation do not exist.

- [ ] **Step 3: Write the three Worker prompts.**

Each Worker prompt must include the following exact operating rules:

```text
你是独立运行的评测 Agent。只处理分配给你的 case.json，不读取其他 Agent 的运行目录。
先读取并验证任务输入，再按 run-starskill 的 CLI 契约选择工作流。
必须保存最终回答、每次工具调用、退出码、标准输出/错误和所有实际产物。
不要用文字伪造坐标、图像、来源、成功状态或文件。
候选观测窗口不是天气、设备或安全保证；月亮与木星的角距不是三维空间距离。
外部服务失败时必须保留结构化失败或降级状态。
```

Then add role-specific goals: teacher must request weather/site/equipment/safety review; outreach must explain apparent angular separation; research must preserve SDSS attribution and processing steps. Prompts must tell the Agent to write `response.md`, `tool_calls.jsonl`, and captured stdout/stderr under its assigned run directory.

- [ ] **Step 4: Write rotating reviewer prompts.**

Each reviewer prompt must refuse to override machine evidence, emit the `ReviewReport` JSON fields exactly, and identify critical prohibited claims. The adjudicator prompt must only be used when the normal reviewer reports a critical issue or conflicts with machine checks.

- [ ] **Step 5: Write the external orchestration README.**

Document this exact sequence:

1. Load one case manifest.
2. Create a new Worker Agent with only its role prompt and case input.
3. Capture its response, tool calls, stdout, stderr, exit code, and output directory.
4. Repeat the Worker three times for each fixed core case.
5. Run the replay CLI for machine checks.
6. Create one rotating reviewer Agent after all Workers finish.
7. Run replay again with the reviewer JSON.
8. Aggregate score reports and write the summary.

Document the required directory layout, the six CLI exit codes used by failure cases, the no-fabrication rule, cache/live modes, and the 9-run/80-point/standard-deviation acceptance line. State explicitly that this repository does not create child Agents.

- [ ] **Step 6: Update the Skill and CLI contract.**

Add an `Evaluation Replay` section to `skills/run-starskill/SKILL.md` that says the Skill is evaluated by an external Agent harness, each run uses a new output directory, and the harness must inspect actual files and exit codes. Add the same captured fields and no-fabrication rule to `references/cli-contract.md`. Do not change the existing command syntax or workflow selection rules.

- [ ] **Step 7: Ignore captured evaluation runs and run documentation tests.**

Add exactly this line to `.gitignore`:

```text
evaluation-runs/
```

Run:

```powershell
python -m pytest tests/test_evaluation_cases.py -q
python -m pytest -q
```

Expected: PASS, with no changes to existing CLI behavior.

- [ ] **Step 8: Commit when a real Git worktree is available.**

```powershell
git add evaluation/prompts evaluation/README.md skills/run-starskill/SKILL.md skills/run-starskill/references/cli-contract.md .gitignore tests/test_evaluation_cases.py
git commit -m "docs: define external agent evaluation protocol"
```

## Task 6: Add Replay Fixtures and Run Acceptance Verification

**Files:**
- Create: `tests/fixtures/evaluation/` fixture files generated by test helpers, not live network data.
- Create: `tests/test_evaluation_replay.py`
- Create: `evaluation/reports/README.md`
- Modify: `docs/final-technical-report.md` only after the acceptance run has fresh evidence.

**Interfaces:**
- Consumes: existing fake backend patterns from `tests/test_pipeline.py` and `tests/test_cli.py`, all 15 case manifests, and the replay CLI.
- Produces: deterministic replay coverage and a documented acceptance command sequence; no network-dependent CI requirement.

- [ ] **Step 1: Write a failing replay test using a temporary valid bundle.**

Create a test helper that writes `run.json`, `result.json`, `report.md`, `review_checklist.md`, the expected intermediate JSON/CSV files, and a valid non-empty PNG using Pillow. Register every file in `run.json` with its actual byte count and SHA-256. Then assert that the core M42 case receives a machine report with no critical issues after replay.

- [ ] **Step 2: Run the replay test and verify it fails.**

Run:

```powershell
python -m pytest tests/test_evaluation_replay.py -q
```

Expected: FAIL until the fixture helper and replay integration are wired to the checker and scorer.

- [ ] **Step 3: Implement the fixture helper and replay integration.**

Keep fixture data deterministic: use the existing M42 reference values from `runs/day5_m42` in JSON assertions, write timestamps with explicit offsets, and generate the PNG in memory with a fixed RGB pattern. Do not fetch SIMBAD or SDSS from tests. Exercise both a valid success bundle and a valid degraded bundle with exit code 5.

- [ ] **Step 4: Run the full test and static verification commands.**

Run:

```powershell
python -m pytest -q
python -m compileall src tests scripts
python -m pip check
python scripts/evaluate_starskill.py --help
```

Expected: all tests pass, compilation succeeds, `pip check` reports no broken requirements, and replay help is available.

- [ ] **Step 5: Run the real cached core workflows in new output directories.**

Use new directories under `evaluation-runs/` and never overwrite the existing `runs/` evidence:

```powershell
python -m starskill run examples/observation_m42_beijing.json --output-dir evaluation-runs/live/core-m42 --cache-dir cache/targets
python -m starskill relationship examples/moon_jupiter_shanghai.json --output evaluation-runs/live/core-moon-jupiter/relationship.csv --metadata evaluation-runs/live/core-moon-jupiter/relationship.json
python -m starskill fetch-image examples/m51_sdss_image.json --output-dir evaluation-runs/live/core-m51 --cache-dir cache/sdss
```

Check each exit code and inspect actual files. Treat exit code 5 as degraded and any other nonzero code according to the CLI contract; do not turn a service error into a passing evidence run.

- [ ] **Step 6: Execute external Agent evaluation.**

From a Codex evaluation session, create 9 fresh Worker runs for the three core cases, then six variant runs, six failure runs, and three open runs. Save all raw files before invoking the replay CLI. Create the rotating reviewer runs only after Worker execution is complete. Run:

```powershell
python scripts/evaluate_starskill.py replay --case evaluation/cases/core/core-m42-beijing.json --run-dir evaluation-runs/agents/core-m42/teacher-01 --return-code 0 --stdout-file evaluation-runs/agents/core-m42/teacher-01/stdout.txt --stderr-file evaluation-runs/agents/core-m42/teacher-01/stderr.txt --review-file evaluation-runs/reviews/core-m42.json --output-dir evaluation-runs/scores/core-m42/teacher-01
python scripts/evaluate_starskill.py aggregate --score-root evaluation-runs/scores --output-dir evaluation-runs/reports
```

Use one replay invocation per Worker run; the sample command illustrates the required paths and must not be used to overwrite another run. For failure cases, pass the actual expected nonzero exit code and preserve the structured stderr.

- [ ] **Step 7: Record fresh acceptance evidence.**

Write `evaluation/reports/acceptance-YYYY-MM-DD.md` with the actual date, run counts, hard-gate rate, mean/base scores, per-case standard deviations, critical failures, open-task scores, live smoke status, and any unreviewed risks. Update `docs/final-technical-report.md` only with values observed in this fresh run; do not copy historical claims without rerunning the commands.

- [ ] **Step 8: Commit when a real Git worktree is available.**

```powershell
git add tests/fixtures/evaluation tests/test_evaluation_replay.py evaluation/reports/README.md docs/final-technical-report.md
git commit -m "test: verify agent evaluation replay"
```

Captured `evaluation-runs/` data remains ignored unless a specific small fixture is intentionally copied under `tests/fixtures/evaluation/`.

## Self-Review Checklist

- [ ] Every design requirement maps to a task: three roles and independent runs (Tasks 1, 5, 6), fixed/variant/failure/open matrix (Task 1), deterministic checks (Task 2), 100-point scoring and bonuses (Task 3), external orchestration boundary (Task 5), cross-review and adjudication (Task 5), repeatability and acceptance thresholds (Tasks 3 and 6), and live smoke separation (Task 6).
- [ ] No task requires new astronomy calculations or changes existing CLI contracts.
- [ ] All public function names and model fields used later are defined before use.
- [ ] Hard gates are checked before base or bonus scoring.
- [ ] Open-task scores do not affect the core pass boolean.
- [ ] Network-dependent calls are absent from unit and replay tests.
- [ ] The plan contains no unresolved placeholders or unbounded edge-case instructions.
- [ ] Git commit steps are conditional because the current project root is not a Git worktree.
