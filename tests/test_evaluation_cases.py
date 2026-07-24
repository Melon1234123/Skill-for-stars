import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from scripts.evaluate_starskill import _validate_replay_identity
from starskill.evaluation.cases import CaseManifestError, load_case, load_cases
from starskill.evaluation.reporting import (
    NORMAL_REVIEWER_BY_WORKER_ROLE,
    RawRunInputs,
    ReportError,
    ScoreBundle,
    _EXECUTION_RECORD_FIELDS,
    _validate_review,
)
from starskill.evaluation.models import EvaluationCase, MachineCheckReport, ReviewReport
from starskill.schemas import (
    AstronomicalRelationshipTask,
    ObservationTask,
    SDSSImageRequest,
    SolarSystemRelationshipTask,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_REPORT_FIELDS = (
    "case_id",
    "reviewer_role",
    "role_usability_points",
    "safety_review_points",
    "critical_issues",
    "issues",
    "confidence",
    "recommendation",
)


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

    assert len(cases) == 22
    assert len({case.case_id for case in cases}) == 22
    assert {case.kind for case in cases} == {"core", "variant", "failure", "open"}
    assert all(case.review_focus for case in cases)


def test_load_cases_resolves_existing_task_and_prompt_paths_in_sorted_order() -> None:
    cases = load_cases(PROJECT_ROOT / "evaluation/cases")

    assert [case.case_id for case in cases] == [
        "core-m42-beijing",
        "core-m51-sdss",
        "core-moon-jupiter-shanghai",
        "failure-invalid-observation-input",
        "failure-invalid-timezone",
        "failure-no-observation-window",
        "failure-sdss-invalid-response",
        "failure-sdss-service",
        "failure-target-service",
        "generic-coordinate-coordinate",
        "generic-m31-coordinate",
        "generic-mars-m31",
        "generic-mars-saturn",
        "open-outreach-boundary",
        "open-research-boundary",
        "open-teacher-boundary",
        "variant-m42-location-time",
        "variant-m42-no-window",
        "variant-m51-cache-reuse",
        "variant-m51-request-parameters",
        "variant-moon-jupiter-interval",
        "variant-moon-jupiter-location-time",
    ]
    assert all(Path(case.task_path).is_file() for case in cases)
    assert all(Path(case.prompt_file).is_file() for case in cases)
    assert {
        case.case_id: Path(case.prompt_file).as_posix().split("/evaluation/prompts/")[1]
        for case in cases
    } == {
        "core-m42-beijing": "workers/teacher.md",
        "core-m51-sdss": "workers/research.md",
        "core-moon-jupiter-shanghai": "workers/outreach.md",
        "failure-invalid-observation-input": "workers/teacher.md",
        "failure-invalid-timezone": "workers/teacher.md",
        "failure-no-observation-window": "workers/teacher.md",
        "failure-sdss-invalid-response": "workers/research.md",
        "failure-sdss-service": "workers/research.md",
        "failure-target-service": "workers/teacher.md",
        "generic-coordinate-coordinate": "workers/outreach.md",
        "generic-m31-coordinate": "workers/outreach.md",
        "generic-mars-m31": "workers/outreach.md",
        "generic-mars-saturn": "workers/outreach.md",
        "open-outreach-boundary": "workers/outreach.md",
        "open-research-boundary": "workers/research.md",
        "open-teacher-boundary": "workers/teacher.md",
        "variant-m42-location-time": "workers/teacher.md",
        "variant-m42-no-window": "workers/teacher.md",
        "variant-m51-cache-reuse": "workers/research.md",
        "variant-m51-request-parameters": "workers/research.md",
        "variant-moon-jupiter-interval": "workers/outreach.md",
        "variant-moon-jupiter-location-time": "workers/outreach.md",
    }


def test_load_cases_rejects_missing_or_empty_canonical_root(tmp_path: Path) -> None:
    with pytest.raises(CaseManifestError, match="canonical cases root"):
        load_cases(tmp_path / "missing")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(CaseManifestError, match="canonical cases root"):
        load_cases(empty)


def test_load_cases_has_exact_workflow_and_exit_mapping() -> None:
    cases = load_cases(PROJECT_ROOT / "evaluation/cases")

    assert {
        case.case_id: (case.workflow, case.expected_exit_code)
        for case in cases
    } == {
        "core-m42-beijing": ("run", 0),
        "core-m51-sdss": ("fetch-image", 0),
        "core-moon-jupiter-shanghai": ("relationship", 0),
        "failure-invalid-observation-input": ("validate", 2),
        "failure-invalid-timezone": ("validate", 2),
        "failure-no-observation-window": ("run", 0),
        "failure-sdss-invalid-response": ("fetch-image", 9),
        "failure-sdss-service": ("fetch-image", 7),
        "failure-target-service": ("run", 4),
        "generic-coordinate-coordinate": ("relationship", 0),
        "generic-m31-coordinate": ("relationship", 0),
        "generic-mars-m31": ("relationship", 0),
        "generic-mars-saturn": ("relationship", 0),
        "open-outreach-boundary": ("relationship", 2),
        "open-research-boundary": ("fetch-image", 2),
        "open-teacher-boundary": ("run", 0),
        "variant-m42-location-time": ("run", 0),
        "variant-m42-no-window": ("run", 0),
        "variant-m51-cache-reuse": ("fetch-image", 0),
        "variant-m51-request-parameters": ("fetch-image", 0),
        "variant-moon-jupiter-interval": ("relationship", 0),
        "variant-moon-jupiter-location-time": ("relationship", 0),
    }


def test_case_task_payloads_match_declared_workflows() -> None:
    cases = load_cases(PROJECT_ROOT / "evaluation/cases")
    intentional_validation_failures = {
        "failure-invalid-observation-input",
        "failure-invalid-timezone",
    }

    for case in cases:
        payload = json.loads(Path(case.task_path).read_text(encoding="utf-8"))

        if case.case_id in intentional_validation_failures:
            with pytest.raises(ValidationError):
                ObservationTask.model_validate(payload)
            continue

        if case.workflow in {"run", "validate"}:
            task = ObservationTask.model_validate(payload)
            assert task.task_type == "observation_plan"
        elif case.workflow == "relationship":
            task = TypeAdapter(
                AstronomicalRelationshipTask | SolarSystemRelationshipTask
            ).validate_python(payload)
            assert task.task_type in {
                "astronomical_relationship",
                "solar_system_relationship",
            }
        elif case.workflow == "fetch-image":
            request = SDSSImageRequest.model_validate(payload)
            assert request.target_name == "M51"
        else:
            pytest.fail(f"unexpected workflow in test coverage: {case.workflow}")


def test_load_case_rejects_array_wildcard_json_pointer(tmp_path: Path) -> None:
    case_path = tmp_path / "bad-case.json"
    case_path.write_text(
        """
        {
          "case_id": "open-bad-pointer",
          "kind": "open",
          "role": "teacher",
          "task_path": "examples/observation_m42_beijing.json",
          "workflow": "run",
          "expected_exit_code": 0,
          "expected_status": "success",
          "required_files": ["run.json"],
          "json_assertions": [
            {"file": "run.json", "pointer": "/items/*/status", "exists": true}
          ],
          "review_focus": ["reject unsupported wildcard pointers"],
          "prompt_file": "prompts/evaluation/open-bad-pointer.md"
        }
        """.strip(),
        encoding="utf-8",
    )

    with pytest.raises(CaseManifestError, match="required schema"):
        load_case(case_path)


def test_worker_prompts_require_real_artifacts_and_exit_codes() -> None:
    for name in ("teacher", "outreach", "research"):
        text = (PROJECT_ROOT / f"evaluation/prompts/workers/{name}.md").read_text(
            encoding="utf-8"
        )
        assert "exit code" in text.lower()
        assert "不要伪造" in text
        assert "tool_calls.jsonl" in text


def test_execution_record_protocol_docs_match_validator_schema() -> None:
    expected_fields = {
        "tool", "command", "case_id", "case_kind", "worker_role", "task_path", "workflow",
        "run_dir", "output_dir", "return_code", "stdout_file", "stderr_file", "response_file", "result",
    }
    assert _EXECUTION_RECORD_FIELDS == expected_fields

    documentation_paths = [
        PROJECT_ROOT / "evaluation/prompts/workers/teacher.md",
        PROJECT_ROOT / "evaluation/prompts/workers/outreach.md",
        PROJECT_ROOT / "evaluation/prompts/workers/research.md",
        PROJECT_ROOT / "skills/run-starskill/references/cli-contract.md",
        PROJECT_ROOT / "evaluation/README.md",
    ]
    for path in documentation_paths:
        text = path.read_text(encoding="utf-8")
        assert "exactly these keys" in text
        assert "absolute path" in text
        assert "must not include `arguments`" in text
        assert "nested `result` object" in text
        for field_name in expected_fields:
            assert f"`{field_name}`" in text


def test_evaluation_readme_documents_external_orchestration() -> None:
    text = (PROJECT_ROOT / "evaluation/README.md").read_text(encoding="utf-8")

    assert "不创建 Agent" in text
    assert "evaluate_starskill.py replay" in text
    assert "live smoke" in text.lower()


def test_public_contracts_document_generalized_relationship_semantics() -> None:
    paths = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "skills/run-starskill/SKILL.md",
        PROJECT_ROOT / "skills/run-starskill/references/cli-contract.md",
        PROJECT_ROOT / "docs/starskill-evaluation/acceptance-2026-07-23.md",
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8").lower()
        assert "relationship v2" in text
        assert "dynamic apparent positions" in text
        assert "fixed icrs positions" in text
        assert "physical distance" in text
        assert "unsupported_solar_system_body" in text


def test_reviewer_rotation_mapping_is_exact_in_readme_and_prompts() -> None:
    readme = (PROJECT_ROOT / "evaluation/README.md").read_text(encoding="utf-8")
    prompt_texts = {
        "teacher": (
            PROJECT_ROOT / "evaluation/prompts/reviewers/teacher-review.md"
        ).read_text(encoding="utf-8"),
        "outreach": (
            PROJECT_ROOT / "evaluation/prompts/reviewers/outreach-review.md"
        ).read_text(encoding="utf-8"),
        "research": (
            PROJECT_ROOT / "evaluation/prompts/reviewers/research-review.md"
        ).read_text(encoding="utf-8"),
    }

    assert "teacher reviewer reviews outreach Worker output" in readme
    assert "outreach reviewer reviews research Worker output" in readme
    assert "research reviewer reviews teacher Worker output" in readme
    assert "rotates that assignment across cases or batches" not in readme

    assert "Review only outreach Worker output." in prompt_texts["teacher"]
    assert "Review only research Worker output." in prompt_texts["outreach"]
    assert "Review only teacher Worker output." in prompt_texts["research"]
    documented_by_worker_role = {
        "teacher": "research",
        "outreach": "teacher",
        "research": "outreach",
    }
    assert NORMAL_REVIEWER_BY_WORKER_ROLE == documented_by_worker_role

    machine = MachineCheckReport(
        case_id="case",
        case_kind="core",
        hard_gate_passed=True,
        exit_code=0,
        dimension_points={},
        issues=[],
        checked_files=[],
    )
    base_case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    for worker_role, reviewer_role in documented_by_worker_role.items():
        case = base_case.model_copy(update={"case_id": f"case-{worker_role}", "role": worker_role})
        review = ReviewReport(
            case_id=case.case_id,
            reviewer_role=reviewer_role,
            role_usability_points=5,
            safety_review_points=6,
            confidence=1,
            recommendation="pass",
        )
        _validate_replay_identity(case, review, worker_role, machine, None)
        bundle = ScoreBundle(
            run_id="run",
            run_dir=str(PROJECT_ROOT),
            case_id=case.case_id,
            case_kind=case.kind,
            worker_role=worker_role,
            machine_checks_path="machine_checks.json",
            summary_path="summary.md",
            raw_inputs=RawRunInputs(return_code=0),
            review=review.model_dump(mode="json"),
            score={
                "case_id": case.case_id,
                "case_kind": case.kind,
                "hard_gate_passed": True,
                "base_score": 100,
                "bonus_score": 0,
                "total_score": 100,
                "dimensions": {},
                "issues": [],
            },
        )
        with pytest.raises(ReportError, match="review evidence path and hash"):
            _validate_review(bundle, case, machine)


def test_reviewer_prompts_list_all_reviewreport_fields_exactly() -> None:
    for name in ("teacher", "outreach", "research"):
        text = (
            PROJECT_ROOT / f"evaluation/prompts/reviewers/{name}-review.md"
        ).read_text(encoding="utf-8")
        for field_name in REVIEW_REPORT_FIELDS:
            assert field_name in text


def test_adjudicator_prompt_is_escalation_only_and_requires_adjudicator_role() -> None:
    text = (
        PROJECT_ROOT / "evaluation/prompts/reviewers/adjudicator.md"
    ).read_text(encoding="utf-8")

    assert (
        "Use this prompt only when a normal rotating reviewer has already reported "
        "a critical issue or when reviewer conclusions conflict with machine checks."
        in text
    )
    assert "Do not use it for routine review." in text
    assert '"reviewer_role": "adjudicator"' in text
    assert "`reviewer_role` must be `adjudicator`." in text


def test_evaluation_readme_contains_exact_ordered_sequence_and_thresholds() -> None:
    text = (PROJECT_ROOT / "evaluation/README.md").read_text(encoding="utf-8")

    expected_steps = [
        "1. Load one case manifest.",
        "2. Create a new Worker Agent with only its role prompt and case input.",
        "3. Capture its response, tool calls, stdout, stderr, exit code, and output directory.",
        "4. Repeat the Worker three times for each fixed core case.",
        "5. Run the replay CLI for machine checks.",
        "6. Create one rotating reviewer Agent after all Workers finish.",
        "7. Run replay again with the reviewer JSON.",
        "8. Aggregate score reports and write the summary.",
    ]
    positions = [text.index(step) for step in expected_steps]
    assert positions == sorted(positions)

    for snippet in (
        "2 | input validation failure",
        "4 | SIMBAD service failure",
        "7 | public data service failure",
        "9 | public response validation failure",
        "9 independent core Worker runs total",
        "core average base score at least 80/100",
        "per-case population standard deviation at most 5",
    ):
        assert snippet in text


def test_readme_and_skill_docs_state_no_child_agent_or_llm_orchestration() -> None:
    readme = (PROJECT_ROOT / "evaluation/README.md").read_text(encoding="utf-8")
    skill = (PROJECT_ROOT / "skills/run-starskill/SKILL.md").read_text(
        encoding="utf-8"
    )
    cli_contract = (
        PROJECT_ROOT / "skills/run-starskill/references/cli-contract.md"
    ).read_text(encoding="utf-8")

    assert "does not create child Agents" in readme
    assert "does not call an LLM API" in readme
    assert "does not create child Agents" in skill
    assert "does not call an LLM API" in skill
    assert "does not create child Agents" in cli_contract
    assert "does not call an LLM API" in cli_contract
