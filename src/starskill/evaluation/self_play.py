"""Provider-neutral self-play evidence capture and post-training dataset export."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from pydantic import ValidationError

from starskill.evaluation.models import (
    AgentResponse,
    GeneratedEvaluationTask,
    PersonaSatisfaction,
    SelfPlayDimensionScore,
    SelfPlayPrompt,
    SelfPlayScore,
    SelfPlayTrace,
    ToolCallRecord,
)


class SelfPlayError(ValueError):
    """Structured self-play capture or dataset-export failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class AgentProvider(Protocol):
    """External harness contract; StarSkill intentionally supplies no LLM implementation."""

    def respond(self, prompt: SelfPlayPrompt) -> AgentResponse:
        """Return the response, observed tool calls, and text artifacts for one prompt."""


@runtime_checkable
class SelfPlayScorer(Protocol):
    """Optional external scorer contract for replacing the transparent default heuristic."""

    def score(
        self,
        prompt: SelfPlayPrompt,
        response: AgentResponse,
        artifact_names: Sequence[str],
    ) -> SelfPlayScore:
        """Return a complete six-dimension score for one captured response."""


def run_self_play(
    *,
    task: GeneratedEvaluationTask,
    provider: AgentProvider,
    output_dir: Path,
    run_id: str | None = None,
    scorer: SelfPlayScorer | None = None,
) -> SelfPlayTrace:
    """Capture exactly one injected-Agent response into an auditable fresh directory."""

    resolved_output = _prepare_fresh_directory(output_dir)
    resolved_run_id = run_id or task.task_id
    prompt = SelfPlayPrompt(
        run_id=resolved_run_id,
        task=task,
        prompt=task.prompt,
        requirements=(
            "Use only supported StarSkill tools and retain the tool evidence actually observed.",
            "Do not present an external service failure as a successful empty result.",
            "State scientific and observational limits when the task requires them.",
        ),
    )
    _write_json(resolved_output / "prompt.json", prompt.model_dump(mode="json"))
    artifacts_dir = resolved_output / "artifacts"
    artifacts_dir.mkdir()

    failure: dict[str, str] | None = None
    try:
        supplied = provider.respond(prompt)
        response = _coerce_agent_response(supplied)
    except Exception as exc:  # Provider boundaries must retain a failure record, not raise partial runs.
        response = AgentResponse(response_markdown="")
        failure = {
            "code": "agent_provider_error",
            "message": f"AgentProvider raised {type(exc).__name__}",
        }

    (resolved_output / "response.md").write_text(response.response_markdown, encoding="utf-8")
    _write_tool_calls(resolved_output / "tool_calls.jsonl", response.tool_calls)
    try:
        artifact_names = _write_agent_artifacts(artifacts_dir, response.artifacts)
    except SelfPlayError as exc:
        artifact_names = ()
        failure = {"code": exc.code, "message": str(exc)}
    if failure is not None:
        score = _failed_score(task, failure)
    elif scorer is not None:
        try:
            score = scorer.score(prompt, response, artifact_names)
            _validate_external_score(score, task.task_id)
        except Exception as exc:
            failure = {
                "code": "self_play_scorer_error",
                "message": f"SelfPlayScorer raised {type(exc).__name__}",
            }
            score = _failed_score(task, failure)
    else:
        score = score_self_play(prompt, response, artifact_names)
    satisfaction = assess_persona_satisfaction(task, score)
    _write_json(resolved_output / "score.json", score.model_dump(mode="json"))
    _write_json(resolved_output / "satisfaction.json", satisfaction.model_dump(mode="json"))
    return SelfPlayTrace(
        run_id=resolved_run_id,
        run_dir=str(resolved_output),
        prompt=prompt,
        response_markdown=response.response_markdown,
        tool_calls=response.tool_calls,
        score=score,
        satisfaction=satisfaction,
        artifact_sha256=_artifact_hashes(artifacts_dir),
    )


def run_self_play_batch(
    *,
    tasks: Iterable[GeneratedEvaluationTask],
    provider: AgentProvider,
    output_root: Path,
    scorer: SelfPlayScorer | None = None,
) -> list[SelfPlayTrace]:
    """Run an injected provider over generated tasks without overwriting an existing batch."""

    root = _prepare_fresh_directory(output_root)
    traces: list[SelfPlayTrace] = []
    for index, task in enumerate(tasks, start=1):
        run_id = f"{task.task_id}-{index:04d}"
        traces.append(
            run_self_play(
                task=task,
                provider=provider,
                output_dir=root / run_id,
                run_id=run_id,
                scorer=scorer,
            )
        )
    if not traces:
        raise SelfPlayError("empty_task_set", "self-play batch requires at least one task")
    return traces


def score_self_play(
    prompt: SelfPlayPrompt,
    response: AgentResponse,
    artifact_names: Sequence[str],
) -> SelfPlayScore:
    """Score observable task-contract evidence; it is not a substitute for peer review."""

    task = prompt.task
    text = response.response_markdown.lower()
    tool_names = {call.tool for call in response.tool_calls}
    evidence_text = " ".join(
        [text, *artifact_names, *(json.dumps(call.result, ensure_ascii=False).lower() for call in response.tool_calls)]
    )
    task_success = _score_task_success(task, text, tool_names)
    scientific_correctness = _score_scientific_contract(task, text)
    tool_selection = _score_tool_selection(task, response.tool_calls)
    evidence_quality = _score_evidence(task, evidence_text)
    reproducibility = _score_reproducibility(response.tool_calls, artifact_names)
    dimensions = (
        task_success,
        scientific_correctness,
        tool_selection,
        evidence_quality,
        reproducibility,
    )
    satisfaction_score = _persona_score(task, dimensions)
    persona_satisfaction = SelfPlayDimensionScore(
        score=satisfaction_score,
        reasons=(
            "Derived from task completion, scientific contract markers, tool evidence, and the persona's failure sensitivity.",
        ),
        evidence=(f"failure_sensitivity={task.persona_profile.failure_sensitivity}",),
    )
    overall_score = round(sum(item.score for item in (*dimensions, persona_satisfaction)) / 6, 4)
    return SelfPlayScore(
        task_id=task.task_id,
        status="completed",
        task_success=task_success,
        scientific_correctness=scientific_correctness,
        tool_selection=tool_selection,
        evidence_quality=evidence_quality,
        reproducibility=reproducibility,
        persona_satisfaction=persona_satisfaction,
        overall_score=overall_score,
    )


def assess_persona_satisfaction(
    task: GeneratedEvaluationTask, score: SelfPlayScore
) -> PersonaSatisfaction:
    """Convert the scored persona dimension into an explicit satisfaction record."""

    threshold = 0.8 if task.persona_profile.failure_sensitivity == "high" else 0.65
    satisfied = score.status == "completed" and score.persona_satisfaction.score >= threshold
    reason = (
        f"persona threshold {threshold:.2f} based on {task.persona_profile.failure_sensitivity} failure sensitivity"
    )
    return PersonaSatisfaction(
        task_id=task.task_id,
        persona=task.persona,
        satisfaction=score.persona_satisfaction.score,
        satisfied=satisfied,
        reasons=(reason, *score.persona_satisfaction.reasons),
    )


def load_self_play_trace(run_dir: Path) -> SelfPlayTrace:
    """Load and validate an existing self-play evidence directory for dataset export."""

    resolved = run_dir.resolve()
    if not resolved.is_dir():
        raise SelfPlayError("input_not_found", f"self-play run directory does not exist: {resolved}")
    prompt = _load_model(resolved / "prompt.json", SelfPlayPrompt, "prompt")
    score = _load_model(resolved / "score.json", SelfPlayScore, "score")
    satisfaction = _load_model(resolved / "satisfaction.json", PersonaSatisfaction, "satisfaction")
    response_path = resolved / "response.md"
    tool_calls_path = resolved / "tool_calls.jsonl"
    if not response_path.is_file() or not tool_calls_path.is_file():
        raise SelfPlayError("incomplete_self_play_run", f"missing response or tool calls in {resolved}")
    try:
        response = response_path.read_text(encoding="utf-8")
        tool_calls = tuple(
            ToolCallRecord.model_validate(json.loads(line))
            for line in tool_calls_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise SelfPlayError("invalid_self_play_run", f"invalid response or tool calls in {resolved}") from exc
    _validate_trace_identity(prompt, score, satisfaction, resolved)
    artifacts_dir = resolved / "artifacts"
    if not artifacts_dir.is_dir():
        raise SelfPlayError("incomplete_self_play_run", f"missing artifacts directory in {resolved}")
    return SelfPlayTrace(
        run_id=prompt.run_id,
        run_dir=str(resolved),
        prompt=prompt,
        response_markdown=response,
        tool_calls=tool_calls,
        score=score,
        satisfaction=satisfaction,
        artifact_sha256=_artifact_hashes(artifacts_dir),
    )


def export_post_training_datasets(*, run_root: Path, output_dir: Path) -> dict[str, object]:
    """Export validated captured traces as regression, success, and preference JSONL datasets."""

    root = run_root.resolve()
    if not root.is_dir():
        raise SelfPlayError("input_not_found", f"self-play run root does not exist: {root}")
    run_dirs = sorted(path.parent for path in root.rglob("score.json"))
    if not run_dirs:
        raise SelfPlayError("input_not_found", f"no self-play score.json found under {root}")
    traces = [load_self_play_trace(path) for path in run_dirs]
    destination = _prepare_fresh_directory(output_dir)
    regression_records = [_trace_record(trace) for trace in traces]
    successful_records = [
        _trace_record(trace)
        for trace in traces
        if trace.score.status == "completed"
        and trace.satisfaction.satisfied
        and min(
            trace.score.task_success.score,
            trace.score.scientific_correctness.score,
            trace.score.tool_selection.score,
            trace.score.evidence_quality.score,
            trace.score.reproducibility.score,
        ) >= 0.8
    ]
    preference_records = _preference_records(traces)
    files = {
        "regression": destination / "regression.jsonl",
        "successful_traces": destination / "successful_traces.jsonl",
        "preferences": destination / "preferences.jsonl",
    }
    _write_jsonl(files["regression"], regression_records)
    _write_jsonl(files["successful_traces"], successful_records)
    _write_jsonl(files["preferences"], preference_records)
    return {
        "output_dir": str(destination),
        "regression": str(files["regression"]),
        "successful_traces": str(files["successful_traces"]),
        "preferences": str(files["preferences"]),
        "counts": {
            "regression": len(regression_records),
            "successful_traces": len(successful_records),
            "preferences": len(preference_records),
        },
    }


def _score_task_success(
    task: GeneratedEvaluationTask, text: str, tool_names: set[str]
) -> SelfPlayDimensionScore:
    if task.expected_outcome == "clarify":
        markers = ("地点", "日期", "时区", "半径")
        matches = tuple(marker for marker in markers if marker in text)
        complete = len(matches) >= 3 and not tool_names
        return _dimension(
            1.0 if complete else len(matches) / len(markers),
            "Clarification task requires required missing parameters before a tool call.",
            matches,
        )
    if task.expected_outcome == "structured_failure":
        markers = ("失败", "failed", "超时", "timeout")
        matches = tuple(marker for marker in markers if marker in text)
        return _dimension(
            1.0 if len(matches) >= 2 else len(matches) / 2,
            "Failure task requires an explicit failure rather than an empty successful result.",
            matches,
        )
    if task.expected_outcome == "correct_claim":
        markers = ("角距", "角距离", "angular separation", "不是", "物理")
        matches = tuple(marker for marker in markers if marker in text)
        return _dimension(
            1.0 if len(matches) >= 3 else len(matches) / 3,
            "Adversarial claim must be corrected with the observation/physical distinction.",
            matches,
        )
    expected_tools = set(task.required_tools)
    matches = tuple(sorted(expected_tools & tool_names))
    return _dimension(
        len(matches) / len(expected_tools),
        "Successful task completion is evidenced by the required recorded tool calls.",
        matches,
    )


def _score_scientific_contract(task: GeneratedEvaluationTask, text: str) -> SelfPlayDimensionScore:
    markers_by_family = {
        "observation": ("几何", "天气", "地平"),
        "catalog_query": ("adql", "provenance", "行"),
        "cone_search": ("坐标", "半径", "provenance"),
        "crossmatch": ("匹配半径", "历元", "物理关联"),
        "ambiguous_input": ("地点", "日期", "时区"),
        "service_failure": ("失败", "超时", "provenance"),
        "scientific_adversarial": ("角", "不是", "物理"),
    }
    markers = markers_by_family[task.task_family]
    matches = tuple(marker for marker in markers if marker in text)
    return _dimension(
        len(matches) / len(markers),
        "Scientific correctness is a visible contract-marker check and requires human review for scientific publication.",
        matches,
    )


def _score_tool_selection(
    task: GeneratedEvaluationTask, calls: Sequence[ToolCallRecord]) -> SelfPlayDimensionScore:
    actual = {call.tool for call in calls}
    if task.expected_outcome == "clarify":
        return _dimension(
            1.0 if not actual else 0.0,
            "Ambiguous requests must be clarified before selecting a tool.",
            tuple(sorted(actual)),
        )
    expected = set(task.required_tools)
    matches = tuple(sorted(expected & actual))
    extras = tuple(sorted(actual - expected))
    score = len(matches) / len(expected)
    if extras:
        score = max(0.0, score - 0.2)
    return _dimension(score, "Required tools are compared with captured tool names.", (*matches, *extras))


def _score_evidence(task: GeneratedEvaluationTask, evidence_text: str) -> SelfPlayDimensionScore:
    matches = tuple(name for name in task.expected_evidence if name.lower() in evidence_text)
    return _dimension(
        len(matches) / len(task.expected_evidence),
        "Expected evidence filenames or identifiers must occur in captured output or artifacts.",
        matches,
    )


def _score_reproducibility(
    calls: Sequence[ToolCallRecord], artifact_names: Sequence[str]
) -> SelfPlayDimensionScore:
    if not calls:
        return _dimension(
            1.0 if artifact_names else 0.0,
            "No tool call was required; reproducibility is based on retained artifacts.",
            tuple(artifact_names),
        )
    complete = tuple(
        call.tool
        for call in calls
        if call.arguments and call.result and call.status in {"success", "failed"}
    )
    score = (len(complete) / len(calls)) * (1.0 if artifact_names else 0.5)
    return _dimension(
        score,
        "Recorded arguments, results, statuses, and retained artifacts support replay.",
        (*complete, *artifact_names),
    )


def _persona_score(task: GeneratedEvaluationTask, dimensions: Sequence[SelfPlayDimensionScore]) -> float:
    score = sum(item.score for item in dimensions) / len(dimensions)
    if task.persona_profile.failure_sensitivity == "high" and dimensions[0].score < 1.0:
        score = min(score, 0.5)
    if task.persona_profile.failure_sensitivity == "medium" and dimensions[0].score < 0.5:
        score = min(score, 0.6)
    return round(score, 4)


def _failed_score(task: GeneratedEvaluationTask, failure: dict[str, str]) -> SelfPlayScore:
    dimension = _dimension(0.0, "AgentProvider did not return a usable response.", ())
    return SelfPlayScore(
        task_id=task.task_id,
        status="failed",
        task_success=dimension,
        scientific_correctness=dimension,
        tool_selection=dimension,
        evidence_quality=dimension,
        reproducibility=dimension,
        persona_satisfaction=dimension,
        overall_score=0.0,
        failure=failure,
    )


def _dimension(score: float, reason: str, evidence: Sequence[str]) -> SelfPlayDimensionScore:
    return SelfPlayDimensionScore(
        score=round(max(0.0, min(1.0, score)), 4), reasons=(reason,), evidence=tuple(evidence)
    )


def _coerce_agent_response(value: AgentResponse) -> AgentResponse:
    if isinstance(value, AgentResponse):
        return value
    try:
        return AgentResponse.model_validate(value)
    except ValidationError as exc:
        raise SelfPlayError("invalid_agent_response", "AgentProvider returned an invalid response") from exc


def _validate_external_score(score: SelfPlayScore, task_id: str) -> None:
    if score.task_id != task_id:
        raise SelfPlayError("invalid_external_score", "external scorer returned a score for another task")


def _write_tool_calls(path: Path, calls: Sequence[ToolCallRecord]) -> None:
    _write_jsonl(path, [call.model_dump(mode="json") for call in calls])


def _write_agent_artifacts(directory: Path, artifacts: dict[str, str]) -> tuple[str, ...]:
    names: list[str] = []
    for name, content in sorted(artifacts.items()):
        relative = PurePosixPath(name)
        if not name or relative.is_absolute() or ".." in relative.parts:
            raise SelfPlayError("unsafe_artifact_path", f"artifact path must be relative: {name!r}")
        destination = directory.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        names.append(relative.as_posix())
    return tuple(names)


def _prepare_fresh_directory(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise SelfPlayError("unsafe_output_path", f"output directory must be new and empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _artifact_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, records: Sequence[object]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def _load_model(path: Path, model_type, label: str):
    if not path.is_file():
        raise SelfPlayError("incomplete_self_play_run", f"missing {label} file: {path}")
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise SelfPlayError("invalid_self_play_run", f"invalid {label} file: {path}") from exc


def _validate_trace_identity(
    prompt: SelfPlayPrompt,
    score: SelfPlayScore,
    satisfaction: PersonaSatisfaction,
    run_dir: Path,
) -> None:
    if score.task_id != prompt.task.task_id or satisfaction.task_id != prompt.task.task_id:
        raise SelfPlayError("invalid_self_play_run", f"task identity mismatch in {run_dir}")
    if satisfaction.persona != prompt.task.persona:
        raise SelfPlayError("invalid_self_play_run", f"persona identity mismatch in {run_dir}")


def _trace_record(trace: SelfPlayTrace) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": trace.run_id,
        "task": trace.prompt.task.model_dump(mode="json"),
        "prompt": trace.prompt.prompt,
        "response": trace.response_markdown,
        "tool_calls": [call.model_dump(mode="json") for call in trace.tool_calls],
        "score": trace.score.model_dump(mode="json"),
        "satisfaction": trace.satisfaction.model_dump(mode="json"),
        "artifact_sha256": trace.artifact_sha256,
    }


def _preference_records(traces: Sequence[SelfPlayTrace]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[SelfPlayTrace]] = defaultdict(list)
    for trace in traces:
        grouped[(trace.prompt.task.task_id, trace.prompt.task.persona)].append(trace)
    records: list[dict[str, object]] = []
    for (_task_id, persona), candidates in sorted(grouped.items()):
        ordered = sorted(candidates, key=lambda trace: (-trace.score.overall_score, trace.run_id))
        if len(ordered) < 2 or ordered[0].score.overall_score <= ordered[-1].score.overall_score:
            continue
        chosen, rejected = ordered[0], ordered[-1]
        records.append(
            {
                "prompt": chosen.prompt.prompt,
                "persona": persona,
                "chosen": chosen.response_markdown,
                "rejected": rejected.response_markdown,
                "reasons": [
                    f"chosen overall score {chosen.score.overall_score:.4f} exceeds rejected score {rejected.score.overall_score:.4f}",
                    f"chosen satisfaction={chosen.satisfaction.satisfied}; rejected satisfaction={rejected.satisfaction.satisfied}",
                ],
            }
        )
    return records
