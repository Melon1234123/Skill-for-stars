"""MCP adapter for the traceable StarSkill astronomy workflows."""

import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from starskill.observation_planner import VisibilityCriteria
from starskill.pipeline import run_pipeline, utc_now
from starskill.public_data_fetcher import (
    ImageBackend,
    PublicDataError,
    UrlImageBackend,
    fetch_sdss_image,
    write_public_image_metadata,
)
from starskill.schemas import (
    ObservationTask,
    SDSSImageRequest,
    SolarSystemRelationshipTask,
)
from starskill.solar_system_relationship import (
    calculate_solar_system_relationship,
    write_relationship_csv,
    write_relationship_json,
)
from starskill.target_resolver import (
    SimbadBackend,
    TargetBackend,
    TargetResolutionError,
    resolve_target,
)


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,95}$")
RUN_RESOURCE_PATHS = {
    "manifest": "run.json",
    "result": "result.json",
    "report": "report.md",
    "review-checklist": "review_checklist.md",
    "target": "intermediate/target_resolved.json",
    "ephemeris": "intermediate/ephemeris.csv",
    "visibility": "intermediate/visibility.csv",
    "relationship": "relationship.json",
    "relationship-table": "relationship.csv",
    "image-metadata": "image_metadata.json",
}


def _validation_failure(exc: ValidationError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "validation_error",
        "details": [
            {
                "location": list(error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors(include_url=False, include_context=False)
        ],
    }


class StarSkillMcpService:
    """Own StarSkill state while exposing side-effecting workflows as MCP tools."""

    def __init__(
        self,
        *,
        runs_root: Path,
        target_cache_dir: Path,
        image_cache_dir: Path,
        target_backend_factory: Callable[[], TargetBackend] = SimbadBackend,
        image_backend_factory: Callable[[], ImageBackend] = UrlImageBackend,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.runs_root = runs_root.resolve()
        self.target_cache_dir = target_cache_dir.resolve()
        self.image_cache_dir = image_cache_dir.resolve()
        self.target_backend_factory = target_backend_factory
        self.image_backend_factory = image_backend_factory
        self.clock = clock

    def validate_observation_task(self, task: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = ObservationTask.model_validate(task)
        except ValidationError as exc:
            return _validation_failure(exc)
        return {"ok": True, "task": validated.model_dump(mode="json")}

    def resolve_target(self, target: str) -> dict[str, Any]:
        try:
            resolved = resolve_target(
                target,
                backend=self.target_backend_factory(),
                cache_dir=self.target_cache_dir,
                clock=self.clock,
            )
        except (TargetResolutionError, ValueError) as exc:
            return {
                "ok": False,
                "error": getattr(exc, "code", "target_resolution_error"),
                "message": str(exc),
            }
        return {"ok": True, "target": resolved.model_dump(mode="json")}

    def plan_observation(
        self,
        task: dict[str, Any],
        min_target_altitude_deg: float = 30.0,
        max_sun_altitude_deg: float = -12.0,
    ) -> dict[str, Any]:
        try:
            validated_task = ObservationTask.model_validate(task)
            criteria = VisibilityCriteria(
                min_target_altitude_deg=min_target_altitude_deg,
                max_sun_altitude_deg=max_sun_altitude_deg,
            )
        except ValidationError as exc:
            return _validation_failure(exc)

        run_id, output_dir = self._new_run("observation")
        try:
            outcome = run_pipeline(
                validated_task,
                output_dir=output_dir,
                cache_dir=self.target_cache_dir,
                backend=self.target_backend_factory(),
                criteria=criteria,
                clock=self.clock,
            )
        except (TargetResolutionError, ValueError) as exc:
            return self._run_failure(run_id, exc)
        return {
            "ok": True,
            "status": outcome.status,
            "run_id": run_id,
            "cache_hit": outcome.manifest.cache_hit,
            "resources": self._resources_for_run(run_id),
        }

    def calculate_moon_jupiter_relationship(
        self, task: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            validated_task = SolarSystemRelationshipTask.model_validate(task)
        except ValidationError as exc:
            return _validation_failure(exc)

        run_id, output_dir = self._new_run("relationship")
        result = calculate_solar_system_relationship(validated_task, clock=self.clock)
        csv_path = output_dir / "relationship.csv"
        metadata_path = output_dir / "relationship.json"
        write_relationship_csv(result, csv_path)
        write_relationship_json(result, metadata_path)
        separations = [sample.angular_separation_deg for sample in result.samples]
        return {
            "ok": True,
            "run_id": run_id,
            "sample_count": len(result.samples),
            "minimum_separation_deg": min(separations),
            "maximum_separation_deg": max(separations),
            "resources": self._resources_for_run(run_id),
        }

    def fetch_m51_sdss_image(
        self, request: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            validated_request = SDSSImageRequest.model_validate(request or {})
        except ValidationError as exc:
            return _validation_failure(exc)

        run_id, output_dir = self._new_run("m51")
        try:
            result = fetch_sdss_image(
                validated_request,
                cache_dir=self.image_cache_dir,
                source_path=output_dir / "data" / "m51_sdss.jpg",
                display_path=output_dir / "figures" / "m51_display.png",
                backend=self.image_backend_factory(),
                clock=self.clock,
            )
        except PublicDataError as exc:
            return self._run_failure(run_id, exc)
        metadata_path = output_dir / "image_metadata.json"
        write_public_image_metadata(result, metadata_path)
        return {
            "ok": True,
            "run_id": run_id,
            "from_cache": result.source.from_cache,
            "source": result.source.model_dump(mode="json"),
            "resources": self._resources_for_run(run_id),
        }

    def read_run_resource(self, run_id: str, resource: str) -> str:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id is invalid")
        relative_path = RUN_RESOURCE_PATHS.get(resource)
        if relative_path is None:
            raise ValueError("resource is not available")
        run_dir = self.runs_root / run_id
        path = run_dir / relative_path
        if not path.is_file():
            raise FileNotFoundError("resource does not exist for this run")
        return path.read_text(encoding="utf-8")

    def _new_run(self, workflow: str) -> tuple[str, Path]:
        self.runs_root.mkdir(parents=True, exist_ok=True)
        timestamp = self.clock().strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}-{workflow}-{uuid4().hex[:12]}"
        output_dir = self.runs_root / run_id
        output_dir.mkdir()
        return run_id, output_dir

    def _resources_for_run(self, run_id: str) -> dict[str, str]:
        resources: dict[str, str] = {}
        run_dir = self.runs_root / run_id
        for name, relative_path in RUN_RESOURCE_PATHS.items():
            if (run_dir / relative_path).is_file():
                resources[name] = f"starskill://runs/{run_id}/{name}"
        return resources

    def _run_failure(self, run_id: str, exc: Exception) -> dict[str, Any]:
        return {
            "ok": False,
            "error": getattr(exc, "code", "workflow_error"),
            "message": str(exc),
            "run_id": run_id,
            "resources": self._resources_for_run(run_id),
        }


def service_from_environment() -> StarSkillMcpService:
    return StarSkillMcpService(
        runs_root=Path(os.environ.get("STARSKILL_RUNS_DIR", "runs/mcp")),
        target_cache_dir=Path(
            os.environ.get("STARSKILL_TARGET_CACHE_DIR", "cache/targets")
        ),
        image_cache_dir=Path(
            os.environ.get("STARSKILL_IMAGE_CACHE_DIR", "cache/sdss")
        ),
    )


def build_mcp_server(service: StarSkillMcpService | None = None) -> FastMCP:
    service = service or service_from_environment()
    server = FastMCP(
        "StarSkill",
        instructions=(
            "Run traceable astronomy training workflows. Treat observation windows as "
            "geometry-based candidates and preserve required human review for weather, "
            "site conditions, equipment, and safety."
        ),
    )

    @server.tool(structured_output=True)
    def validate_observation_task(task: dict[str, Any]) -> dict[str, Any]:
        """Validate an observation task before querying external services."""
        return service.validate_observation_task(task)

    @server.tool(structured_output=True)
    def resolve_astronomy_target(target: str) -> dict[str, Any]:
        """Resolve a target name through SIMBAD and return cached provenance when available."""
        return service.resolve_target(target)

    @server.tool(structured_output=True)
    def plan_observation(
        task: dict[str, Any],
        min_target_altitude_deg: float = 30.0,
        max_sun_altitude_deg: float = -12.0,
    ) -> dict[str, Any]:
        """Create a fully audited observation plan in the server-owned run directory."""
        return service.plan_observation(
            task,
            min_target_altitude_deg=min_target_altitude_deg,
            max_sun_altitude_deg=max_sun_altitude_deg,
        )

    @server.tool(structured_output=True)
    def calculate_moon_jupiter_relationship(task: dict[str, Any]) -> dict[str, Any]:
        """Calculate the Moon-Jupiter apparent sky relationship for a task."""
        return service.calculate_moon_jupiter_relationship(task)

    @server.tool(structured_output=True)
    def fetch_m51_sdss_image(
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fetch the bounded SDSS DR18 M51 image and preserve its provenance."""
        return service.fetch_m51_sdss_image(request)

    @server.resource(
        "starskill://runs/{run_id}/{resource}",
        name="starskill-run-artifact",
        description="Read a text artifact from a StarSkill run using an approved resource name.",
    )
    def read_run_resource(run_id: str, resource: str) -> str:
        return service.read_run_resource(run_id, resource)

    return server


def main() -> None:
    build_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
