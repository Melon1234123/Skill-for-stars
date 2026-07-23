"""Run the observation workflow and preserve an auditable artifact set."""

import hashlib
import platform
from collections.abc import Callable
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from starskill.ephemeris_calculator import (
    calculate_ephemeris,
    write_ephemeris_csv,
    write_ephemeris_json,
)
from starskill.observation_planner import (
    plan_observation,
    write_observation_plan_json,
    write_visibility_csv,
)
from starskill.recommendations import HUMAN_REVIEW_ITEMS
from starskill.schemas import (
    ArtifactRecord,
    ObservationPlanResult,
    ObservationTask,
    PipelineIssue,
    PipelineManifest,
    PipelineOutcome,
    VisibilityCriteria,
)
from starskill.target_resolver import (
    TargetBackend,
    TargetResolutionError,
    resolve_target,
)
from starskill.visualizer import plot_visibility


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


def _dependency_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "starskill": _package_version("starskill"),
        "astropy": _package_version("astropy"),
        "astroquery": _package_version("astroquery"),
        "matplotlib": _package_version("matplotlib"),
        "numpy": _package_version("numpy"),
        "pydantic": _package_version("pydantic"),
    }


def _artifact_record(output_dir: Path, path: Path) -> ArtifactRecord:
    content = path.read_bytes()
    return ArtifactRecord(
        path=path.relative_to(output_dir).as_posix(),
        bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _write_report(
    plan: ObservationPlanResult,
    path: Path,
    issues: list[PipelineIssue],
    language: str,
) -> None:
    peak_altitude = max(sample.target_altitude_deg for sample in plan.samples)
    if language == "zh-CN":
        lines = [
            "# 观测报告",
            "",
            "## 计算事实",
            "",
            f"- 目标：{plan.target.canonical_name}",
            f"- ICRS 坐标：赤经 {plan.target.ra_deg:.6f}°，赤纬 {plan.target.dec_deg:.6f}°",
            f"- 采样：{len(plan.samples)} 个，每 {plan.interval_minutes} 分钟一次",
            f"- 目标最高高度角：{peak_altitude:.6f}°",
            "",
            "## 规则判定",
            "",
            f"- 最低目标高度角：{plan.criteria.min_target_altitude_deg:g}°",
            f"- 最高太阳高度角：{plan.criteria.max_sun_altitude_deg:g}°",
            f"- 候选观测窗口：{len(plan.windows)} 个",
        ]
        for window in plan.windows:
            lines.append(
                f"- {window.start_local.isoformat()} 至 {window.end_local.isoformat()} "
                f"（{window.sample_count} 个采样点）"
            )
        if issues:
            lines.extend(["", "## 降级输出", ""])
            lines.extend(f"- {issue.stage}：{issue.message}" for issue in issues)
        lines.extend(
            [
                "",
                "## 需要人工复核",
                "",
                "- 确认天气、云量和大气透明度。",
                "- 确认本地地平线遮挡和光污染。",
                "- 确认设备视场、架设情况和观测安全。",
                "",
            ]
        )
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    lines = [
        "# Observation Report",
        "",
        "## Calculated Facts",
        "",
        f"- Target: {plan.target.canonical_name}",
        f"- ICRS coordinates: RA {plan.target.ra_deg:.6f} deg, Dec {plan.target.dec_deg:.6f} deg",
        f"- Samples: {len(plan.samples)} at {plan.interval_minutes}-minute intervals",
        f"- Peak target altitude: {peak_altitude:.6f} deg",
        "",
        "## Rule-based Assessment",
        "",
        f"- Minimum target altitude: {plan.criteria.min_target_altitude_deg:g} deg",
        f"- Maximum Sun altitude: {plan.criteria.max_sun_altitude_deg:g} deg",
        f"- Candidate windows: {len(plan.windows)}",
    ]
    for window in plan.windows:
        lines.append(
            f"- {window.start_local.isoformat()} to {window.end_local.isoformat()} "
            f"({window.sample_count} samples)"
        )
    if issues:
        lines.extend(["", "## Degraded Outputs", ""])
        lines.extend(f"- {issue.stage}: {issue.message}" for issue in issues)
    lines.extend(
        [
            "",
            "## Human Review Required",
            "",
            "- Confirm weather, cloud cover, and transparency.",
            "- Confirm local horizon obstructions and light pollution.",
            "- Confirm equipment field of view and observing safety.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_review_checklist(path: Path) -> None:
    path.write_text(
        "\n".join(
            ["# Human Review Checklist", ""]
            + [f"- [ ] {item}" for item in HUMAN_REVIEW_ITEMS]
            + [""]
        ),
        encoding="utf-8",
    )


def run_pipeline(
    task: ObservationTask,
    *,
    output_dir: Path,
    cache_dir: Path,
    backend: TargetBackend,
    criteria: VisibilityCriteria | None = None,
    plotter: Callable[[ObservationPlanResult, Path], None] = plot_visibility,
    clock: Callable[[], datetime] = utc_now,
) -> PipelineOutcome:
    """Run resolution through reporting, degrading only optional visualization."""
    started_at = clock()
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir = output_dir / "intermediate"
    figures_dir = output_dir / "figures"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    input_path = output_dir / "input.json"
    input_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")
    try:
        target = resolve_target(
            task.target,
            backend=backend,
            cache_dir=cache_dir,
            clock=clock,
        )
    except TargetResolutionError as exc:
        issue = PipelineIssue(
            stage="target_resolution",
            code=exc.code,
            message=str(exc),
        )
        manifest = PipelineManifest(
            run_id=f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-failed",
            status="failed",
            started_at=started_at,
            completed_at=clock(),
            input_task=task,
            cache_hit=False,
            target_source=None,
            dependencies=_dependency_versions(),
            artifacts=[_artifact_record(output_dir, input_path)],
            issues=[issue],
        )
        (output_dir / "run.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        raise
    target_path = intermediate_dir / "target_resolved.json"
    target_path.write_text(target.model_dump_json(indent=2), encoding="utf-8")

    ephemeris = calculate_ephemeris(task, target, clock=clock)
    ephemeris_csv_path = intermediate_dir / "ephemeris.csv"
    ephemeris_json_path = intermediate_dir / "ephemeris.json"
    write_ephemeris_csv(ephemeris, ephemeris_csv_path)
    write_ephemeris_json(ephemeris, ephemeris_json_path)

    plan = plan_observation(ephemeris, criteria)
    visibility_path = intermediate_dir / "visibility.csv"
    result_path = output_dir / "result.json"
    write_visibility_csv(plan, visibility_path)
    write_observation_plan_json(plan, result_path)

    issues: list[PipelineIssue] = []
    figure_path = figures_dir / "visibility_curve.png"
    try:
        plotter(plan, figure_path)
    except Exception as exc:
        issues.append(
            PipelineIssue(
                stage="visualization",
                code="figure_generation_failed",
                message=str(exc),
            )
        )

    report_path = output_dir / "report.md"
    checklist_path = output_dir / "review_checklist.md"
    _write_report(plan, report_path, issues, task.output.language)
    _write_review_checklist(checklist_path)

    artifact_paths = [
        input_path,
        target_path,
        ephemeris_csv_path,
        ephemeris_json_path,
        visibility_path,
        result_path,
        report_path,
        checklist_path,
    ]
    if figure_path.exists():
        artifact_paths.append(figure_path)
    status = "degraded" if issues else "success"
    manifest = PipelineManifest(
        run_id=f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{target.query_name.lower().replace(' ', '-')}",
        status=status,
        started_at=started_at,
        completed_at=clock(),
        input_task=task,
        cache_hit=target.source.from_cache,
        target_source=target.source,
        dependencies=_dependency_versions(),
        artifacts=[_artifact_record(output_dir, path) for path in artifact_paths],
        issues=issues,
    )
    (output_dir / "run.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return PipelineOutcome(
        status=status,
        output_dir=str(output_dir),
        manifest=manifest,
    )
