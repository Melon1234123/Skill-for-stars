"""Deterministic persona/task generation for the existing evaluation system."""

from __future__ import annotations

import copy
import hashlib
import json
import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar, cast

from starskill.evaluation.models import (
    GeneratedEvaluationTask,
    PersonaName,
    PersonaProfile,
    TaskExpectedOutcome,
    TaskFamily,
)


class PersonaGenerationError(ValueError):
    """A structured input or output failure from persona task generation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TaskTemplate:
    template_id: str
    prompt: str
    task_input: Mapping[str, object]
    required_tools: tuple[str, ...]
    expected_evidence: tuple[str, ...]
    expected_outcome: TaskExpectedOutcome


PERSONA_REGISTRY: Mapping[PersonaName, PersonaProfile] = MappingProxyType(
    {
        "student": PersonaProfile(
            name="student",
            knowledge_level="middle_school_to_introductory_undergraduate",
            goals=("完成明确的天文实训任务", "理解结论依据"),
            preferred_answer_style="分步骤、少术语、说明下一步",
            expected_evidence=("关键数值", "来源或产物路径", "不确定性说明"),
            common_mistakes=("将候选观测窗口当作天气保证", "混淆角距离与真实空间距离"),
            failure_sensitivity="high",
        ),
        "teacher": PersonaProfile(
            name="teacher",
            knowledge_level="experienced_educator_with_astronomy_domain_context",
            goals=("设计可复现课堂活动", "检查学生结论是否可验证"),
            preferred_answer_style="结构化教学说明，给出可检查的中间证据",
            expected_evidence=("输入参数", "结果产物", "复核边界"),
            common_mistakes=("省略时区或地点", "把工具输出当作未经检查的事实"),
            failure_sensitivity="high",
        ),
        "outreach": PersonaProfile(
            name="outreach",
            knowledge_level="public_communication_practitioner",
            goals=("面向公众准确解释天象", "避免过度承诺观测条件"),
            preferred_answer_style="简明通俗，保留科学限定条件",
            expected_evidence=("可信来源", "面向公众的限制说明", "可复核结果"),
            common_mistakes=("把可见性等同于一定能看到", "遗漏设备和地平线限制"),
            failure_sensitivity="high",
        ),
        "amateur_observer": PersonaProfile(
            name="amateur_observer",
            knowledge_level="hands_on_observer_with_practical_experience",
            goals=("决定是否值得安排观测", "获取可执行的目标和时间信息"),
            preferred_answer_style="紧凑、操作导向、优先给出约束条件",
            expected_evidence=("地点与时间", "高度角或可见窗口", "人工复核项"),
            common_mistakes=("忽视本地遮挡和天气", "使用未经确认的目标别名"),
            failure_sensitivity="medium",
        ),
        "undergraduate_researcher": PersonaProfile(
            name="undergraduate_researcher",
            knowledge_level="undergraduate_research_training",
            goals=("学习标准化数据查询", "保留可复现分析证据"),
            preferred_answer_style="说明方法、参数和可重跑产物",
            expected_evidence=("ADQL", "provenance", "行数和结果表"),
            common_mistakes=("未限制查询行数", "未报告服务和表版本"),
            failure_sensitivity="high",
        ),
        "researcher": PersonaProfile(
            name="researcher",
            knowledge_level="professional_researcher",
            goals=("获得可审计的科学数据子集", "识别服务和方法边界"),
            preferred_answer_style="精确、简洁、包含假设和可复现证据",
            expected_evidence=("服务标识", "最终 ADQL", "查询哈希", "数据来源"),
            common_mistakes=("忽略选择效应", "将目录匹配误认为物理关联"),
            failure_sensitivity="high",
        ),
        "reviewer": PersonaProfile(
            name="reviewer",
            knowledge_level="independent_quality_reviewer",
            goals=("发现科学和流程错误", "确认失败是否被如实报告"),
            preferred_answer_style="基于证据的判定，明确列出阻断问题",
            expected_evidence=("输入输出链路", "provenance", "失败或人工复核记录"),
            common_mistakes=("只检查自然语言结论", "忽略不可复现的外部服务调用"),
            failure_sensitivity="high",
        ),
    }
)

TASK_FAMILIES: tuple[TaskFamily, ...] = (
    "observation",
    "catalog_query",
    "cone_search",
    "crossmatch",
    "ambiguous_input",
    "service_failure",
    "scientific_adversarial",
)


TASK_TEMPLATES: Mapping[TaskFamily, tuple[TaskTemplate, ...]] = MappingProxyType(
    {
        "observation": (
            TaskTemplate(
                template_id="observation-m42-beijing",
                prompt=(
                    "为北京的 M42 观测活动给出候选观测窗口。先校验输入，再说明结果只代表"
                    "几何可见性，并列出天气、地平线和设备的人工复核项。"
                ),
                task_input={
                    "target": "M42",
                    "location": "Beijing",
                    "date": "2026-01-15",
                    "timezone": "Asia/Shanghai",
                },
                required_tools=("starskill validate", "starskill run"),
                expected_evidence=("run.json", "result.json", "review_checklist.md"),
                expected_outcome="success",
            ),
        ),
        "catalog_query": (
            TaskTemplate(
                template_id="catalog-query-gaia-bright",
                prompt=(
                    "从 Gaia DR3 中查询一个受限的亮星样本。必须使用允许列表服务和结构化目录"
                    "查询参数；报告最终 ADQL、行数、数据来源与 provenance。"
                ),
                task_input={
                    "service": "gaia",
                    "table": "gaiadr3.gaia_source",
                    "columns": ["source_id", "phot_g_mean_mag"],
                    "filters": [{"column": "phot_g_mean_mag", "operator": "<", "value": 12}],
                    "max_rows": 100,
                },
                required_tools=("astronomy_catalog_query",),
                expected_evidence=("request.json", "query.adql", "result.ecsv", "provenance.json"),
                expected_outcome="success",
            ),
        ),
        "cone_search": (
            TaskTemplate(
                template_id="cone-search-vizier-m42",
                prompt=(
                    "在 M42 附近进行有边界的 VizieR 圆锥查询。说明坐标系、半径和行数限制，"
                    "并保留查询证据。"
                ),
                task_input={
                    "service": "vizier",
                    "table": "I/355/gaiadr3",
                    "ra_deg": 83.8221,
                    "dec_deg": -5.3911,
                    "radius_deg": 0.1,
                    "max_rows": 100,
                },
                required_tools=("astronomy_cone_search",),
                expected_evidence=("query.adql", "result.ecsv", "provenance.json"),
                expected_outcome="success",
            ),
        ),
        "crossmatch": (
            TaskTemplate(
                template_id="crossmatch-gaia-vizier-m42",
                prompt=(
                    "为 M42 附近 Gaia 与 VizieR 目录设计一次可复现交叉匹配。先分别执行有行数"
                    "限制的圆锥查询，再明确匹配半径、坐标历元和误匹配风险；不要将目录匹配称为物理关联。"
                ),
                task_input={
                    "center": {"ra_deg": 83.8221, "dec_deg": -5.3911},
                    "radius_deg": 0.05,
                    "match_radius_arcsec": 1.0,
                    "max_rows_per_catalog": 100,
                },
                required_tools=("astronomy_cone_search", "local_coordinate_crossmatch"),
                expected_evidence=("query.adql", "result.ecsv", "provenance.json", "crossmatch.csv"),
                expected_outcome="success",
            ),
        ),
        "ambiguous_input": (
            TaskTemplate(
                template_id="ambiguous-input-target-time",
                prompt=(
                    "用户说“今晚帮我查 M42 附近的星”，但没有地点、时区、日期、目录、搜索半径或"
                    "亮度筛选条件。不要猜测参数；提出最少且必要的澄清问题，并说明收到答案后将保留哪些证据。"
                ),
                task_input={"request": "今晚帮我查 M42 附近的星"},
                required_tools=("clarify_before_tool_call",),
                expected_evidence=("clarification_request", "parameter_checklist"),
                expected_outcome="clarify",
            ),
        ),
        "service_failure": (
            TaskTemplate(
                template_id="service-failure-gaia-timeout",
                prompt=(
                    "Gaia TAP 查询已超时。不要把失败伪装成空结果或成功；返回结构化失败状态，"
                    "保留最终 ADQL、服务端点、查询哈希和 provenance，并给出可重试建议。"
                ),
                task_input={
                    "service": "gaia",
                    "operation": "cone_search",
                    "simulated_failure": "timeout",
                },
                required_tools=("astronomy_cone_search",),
                expected_evidence=("request.json", "query.adql", "result.ecsv", "provenance.json"),
                expected_outcome="structured_failure",
            ),
        ),
        "scientific_adversarial": (
            TaskTemplate(
                template_id="scientific-adversarial-angular-separation",
                prompt=(
                    "审查这项说法：“月亮和木星角距离为 3 度，所以它们在太空中的距离也很近。”"
                    "指出错误，说明角距离的观测含义，要求可复核的计算证据，并避免无依据的物理推断。"
                ),
                task_input={
                    "claim": "月亮和木星角距离为 3 度，所以它们在太空中的距离也很近。",
                    "required_concept": "apparent_angular_separation",
                },
                required_tools=("starskill relationship",),
                expected_evidence=("relationship.csv", "relationship.json", "source_or_method_note"),
                expected_outcome="correct_claim",
            ),
        ),
    }
)


def available_personas() -> tuple[PersonaName, ...]:
    """Return persona names in their documented stable order."""

    return tuple(PERSONA_REGISTRY)


def parse_personas(selector: str | Sequence[str]) -> tuple[PersonaName, ...]:
    """Resolve ``all`` or a comma-separated persona selection without guessing names."""

    if isinstance(selector, str):
        raw_names = tuple(part.strip().lower() for part in selector.split(",") if part.strip())
    else:
        raw_names = tuple(str(name).strip().lower() for name in selector if str(name).strip())
    if not raw_names:
        raise PersonaGenerationError("invalid_personas", "at least one persona must be selected")
    if raw_names == ("all",):
        return available_personas()
    if "all" in raw_names:
        raise PersonaGenerationError("invalid_personas", "'all' cannot be combined with named personas")
    duplicates = {name for name in raw_names if raw_names.count(name) > 1}
    if duplicates:
        raise PersonaGenerationError(
            "invalid_personas", f"duplicate persona selection: {', '.join(sorted(duplicates))}"
        )
    unknown = [name for name in raw_names if name not in PERSONA_REGISTRY]
    if unknown:
        raise PersonaGenerationError(
            "invalid_personas", f"unknown persona: {', '.join(unknown)}"
        )
    return cast(tuple[PersonaName, ...], raw_names)


def generate_tasks(
    *, personas: Sequence[PersonaName] | str, task_count: int, seed: int
) -> list[GeneratedEvaluationTask]:
    """Generate offline evaluation tasks using only a local seeded PRNG."""

    if task_count < 1:
        raise PersonaGenerationError("invalid_task_count", "task count must be at least 1")
    if seed < 0:
        raise PersonaGenerationError("invalid_seed", "seed must be zero or greater")
    selected_personas = parse_personas(personas)
    rng = random.Random(seed)
    persona_cycle = _shuffled_cycle(selected_personas, rng)
    family_cycle = _shuffled_cycle(TASK_FAMILIES, rng)
    tasks: list[GeneratedEvaluationTask] = []

    for index in range(task_count):
        persona = next(persona_cycle)
        family = next(family_cycle)
        template = rng.choice(TASK_TEMPLATES[family])
        tasks.append(
            GeneratedEvaluationTask(
                task_id=f"persona-{seed}-{index + 1:04d}",
                seed=seed,
                persona=persona,
                persona_profile=PERSONA_REGISTRY[persona],
                task_family=family,
                template_id=template.template_id,
                prompt=template.prompt,
                task_input=copy.deepcopy(dict(template.task_input)),
                required_tools=template.required_tools,
                expected_evidence=template.expected_evidence,
                expected_outcome=template.expected_outcome,
            )
        )
    return tasks


def write_task_dataset(
    *,
    tasks: Sequence[GeneratedEvaluationTask],
    output_dir: Path,
    seed: int,
    personas: Sequence[PersonaName],
) -> dict[str, object]:
    """Write a portable JSONL task set and deterministic manifest to a fresh directory."""

    if not tasks:
        raise PersonaGenerationError("invalid_task_count", "task dataset cannot be empty")
    resolved = output_dir.resolve()
    if resolved.exists() and (not resolved.is_dir() or any(resolved.iterdir())):
        raise PersonaGenerationError(
            "unsafe_output_path", f"output directory must be new and empty: {resolved}"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    tasks_file = resolved / "tasks.jsonl"
    task_lines = [json.dumps(task.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) for task in tasks]
    task_text = "\n".join(task_lines) + "\n"
    tasks_file.write_text(task_text, encoding="utf-8")
    task_sha256 = hashlib.sha256(task_text.encode("utf-8")).hexdigest()
    manifest = {
        "schema_version": 1,
        "generator": "starskill.evaluation.personas",
        "seed": seed,
        "personas": list(personas),
        "task_count": len(tasks),
        "task_families": list(TASK_FAMILIES),
        "tasks_file": tasks_file.name,
        "tasks_sha256": task_sha256,
    }
    manifest_file = resolved / "manifest.json"
    manifest_file.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "output_dir": str(resolved),
        "tasks_file": str(tasks_file),
        "manifest_file": str(manifest_file),
        "tasks_sha256": task_sha256,
        "task_count": len(tasks),
    }


_CycleItem = TypeVar("_CycleItem")


def _shuffled_cycle(items: Sequence[_CycleItem], rng: random.Random) -> Iterator[_CycleItem]:
    while True:
        cycle = list(items)
        rng.shuffle(cycle)
        yield from cycle
