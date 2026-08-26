import pytest

from starskill.evaluation.models import GeneratedEvaluationTask
from starskill.evaluation.personas import (
    PERSONA_REGISTRY,
    TASK_FAMILIES,
    PersonaGenerationError,
    available_personas,
    generate_tasks,
    parse_personas,
)


def test_persona_registry_has_all_required_profiles() -> None:
    expected = (
        "student",
        "teacher",
        "outreach",
        "amateur_observer",
        "undergraduate_researcher",
        "researcher",
        "reviewer",
    )

    assert available_personas() == expected
    for name in expected:
        profile = PERSONA_REGISTRY[name]
        assert profile.name == name
        assert profile.knowledge_level
        assert profile.goals
        assert profile.preferred_answer_style
        assert profile.expected_evidence
        assert profile.common_mistakes
        assert profile.failure_sensitivity in {"low", "medium", "high"}


def test_parse_personas_accepts_all_and_a_named_subset() -> None:
    assert parse_personas("all") == available_personas()
    assert parse_personas("student, reviewer") == ("student", "reviewer")


@pytest.mark.parametrize("selector", ["", "all,student", "student,student", "unknown"])
def test_parse_personas_rejects_ambiguous_or_unknown_selection(selector: str) -> None:
    with pytest.raises(PersonaGenerationError) as exc_info:
        parse_personas(selector)

    assert exc_info.value.code == "invalid_personas"


def test_generator_is_deterministic_and_covers_personas_and_families() -> None:
    first = generate_tasks(personas="all", task_count=14, seed=42)
    second = generate_tasks(personas="all", task_count=14, seed=42)
    changed_seed = generate_tasks(personas="all", task_count=14, seed=43)

    assert [task.model_dump(mode="json") for task in first] == [
        task.model_dump(mode="json") for task in second
    ]
    assert [task.model_dump(mode="json") for task in first] != [
        task.model_dump(mode="json") for task in changed_seed
    ]
    assert {task.persona for task in first} == set(available_personas())
    assert {task.task_family for task in first} == set(TASK_FAMILIES)


def test_generated_tasks_are_portable_strongly_typed_records() -> None:
    task = generate_tasks(personas="undergraduate_researcher", task_count=1, seed=8)[0]

    restored = GeneratedEvaluationTask.model_validate(task.model_dump(mode="json"))
    assert restored == task
    assert restored.persona_profile.name == "undergraduate_researcher"
    assert restored.required_tools
    assert restored.expected_evidence


@pytest.mark.parametrize("task_count,seed", [(0, 0), (1, -1)])
def test_generator_rejects_invalid_count_or_seed(task_count: int, seed: int) -> None:
    with pytest.raises(PersonaGenerationError):
        generate_tasks(personas="student", task_count=task_count, seed=seed)
