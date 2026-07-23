"""MCP adapter for the traceable StarSkill astronomy workflows."""

import json
import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from pydantic import TypeAdapter, ValidationError

from starskill.light_pollution import (
    BLACK_MARBLE_PROVIDER,
    BLACK_MARBLE_SOURCE_URL,
    BlackMarbleLightPollutionProvider,
)
from starskill.nasa import NasaApodProvider
from starskill.observation_planner import VisibilityCriteria
from starskill.pipeline import run_pipeline, utc_now
from starskill.public_data_fetcher import (
    ImageBackend,
    PublicDataError,
    UrlImageBackend,
    fetch_sdss_image,
    write_public_image_metadata,
)
from starskill.recommendations import recommend_tonight
from starskill.schemas import (
    ExternalSource,
    LightPollutionResult,
    NasaFeature,
    ObservationTask,
    ObservingConditionsRequest,
    ObservationPlanResult,
    SDSSImageRequest,
    SolarSystemRelationshipTask,
    StellariumSyncRequest,
    TonightRecommendationRequest,
    WeatherForecast,
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
from starskill.stellarium_bridge import StellariumBridge
from starskill.weather import OPEN_METEO_ENDPOINT, OpenMeteoWeatherProvider


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
    "conditions": "conditions.json",
    "recommendation": "recommendation.json",
    "nasa-feature": "nasa_feature.json",
    "stellarium-sync": "stellarium_sync.json",
}

_NASA_DATE = TypeAdapter(str | None)


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
        weather_cache_dir: Path | None = None,
        light_pollution_snapshot_path: Path | None = None,
        nasa_cache_dir: Path | None = None,
        nasa_api_key: str | None = None,
        weather_provider_factory: Callable[[], OpenMeteoWeatherProvider] | None = None,
        light_pollution_provider_factory: (
            Callable[[], BlackMarbleLightPollutionProvider] | None
        ) = None,
        nasa_provider_factory: Callable[[], NasaApodProvider] | None = None,
        stellarium_bridge_factory: Callable[[], StellariumBridge] | None = None,
    ) -> None:
        self.runs_root = runs_root.resolve()
        self.target_cache_dir = target_cache_dir.resolve()
        self.image_cache_dir = image_cache_dir.resolve()
        self.weather_cache_dir = (weather_cache_dir or Path("cache/weather")).resolve()
        self.light_pollution_snapshot_path = (
            light_pollution_snapshot_path or Path("data/black_marble_snapshot.json")
        ).resolve()
        self.nasa_cache_dir = (nasa_cache_dir or Path("cache/nasa")).resolve()
        self.target_backend_factory = target_backend_factory
        self.image_backend_factory = image_backend_factory
        self.clock = clock
        self.weather_provider_factory = weather_provider_factory or (
            lambda: OpenMeteoWeatherProvider(
                cache_dir=self.weather_cache_dir,
                clock=self.clock,
            )
        )
        self.light_pollution_provider_factory = light_pollution_provider_factory or (
            lambda: BlackMarbleLightPollutionProvider(
                snapshot_path=self.light_pollution_snapshot_path,
                clock=self.clock,
            )
        )
        self.nasa_provider_factory = nasa_provider_factory or (
            lambda: NasaApodProvider(
                api_key=nasa_api_key,
                cache_dir=self.nasa_cache_dir,
                clock=self.clock,
            )
        )
        self.stellarium_bridge_factory = stellarium_bridge_factory or StellariumBridge

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

    def get_observing_conditions(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            validated_request = ObservingConditionsRequest.model_validate(request)
        except ValidationError as exc:
            return _validation_failure(exc)

        run_id, output_dir = self._new_run("conditions")
        result = self._weather_forecast(validated_request)
        self._write_model(output_dir / "conditions.json", result)
        return self._model_result(run_id, result)

    def recommend_tonight(
        self,
        task: dict[str, Any],
        min_target_altitude_deg: float = 30.0,
        max_sun_altitude_deg: float = -12.0,
    ) -> dict[str, Any]:
        try:
            request = TonightRecommendationRequest.model_validate(
                {
                    "task": task,
                    "min_target_altitude_deg": min_target_altitude_deg,
                    "max_sun_altitude_deg": max_sun_altitude_deg,
                }
            )
        except ValidationError as exc:
            return _validation_failure(exc)

        run_id, output_dir = self._new_run("recommendation")
        try:
            outcome = run_pipeline(
                request.task,
                output_dir=output_dir,
                cache_dir=self.target_cache_dir,
                backend=self.target_backend_factory(),
                criteria=VisibilityCriteria(
                    min_target_altitude_deg=request.min_target_altitude_deg,
                    max_sun_altitude_deg=request.max_sun_altitude_deg,
                ),
                clock=self.clock,
            )
            geometry = ObservationPlanResult.model_validate_json(
                (Path(outcome.output_dir) / "result.json").read_text(encoding="utf-8")
            )
        except (TargetResolutionError, ValueError, OSError) as exc:
            return self._run_failure(run_id, exc)

        conditions_request = ObservingConditionsRequest(
            observer=request.task.observer,
            time_range=request.task.time_range,
        )
        weather = self._weather_forecast(conditions_request)
        light_pollution = self._light_pollution(request.task.observer)
        result = recommend_tonight(geometry, weather, light_pollution)
        self._write_model(output_dir / "conditions.json", weather)
        self._write_model(output_dir / "recommendation.json", result)
        return self._model_result(run_id, result)

    def get_nasa_feature(self, date: str | None = None) -> dict[str, Any]:
        try:
            validated_date = _NASA_DATE.validate_python(date)
        except ValidationError as exc:
            return _validation_failure(exc)

        run_id, output_dir = self._new_run("nasa-feature")
        try:
            result = self.nasa_provider_factory().get_feature(validated_date)
        except Exception:
            result = NasaFeature(
                source=ExternalSource(
                    provider="NASA APOD",
                    source_url=None,
                    accessed_at=self.clock(),
                    from_cache=False,
                    availability="unavailable",
                    issue_code="nasa_provider_error",
                )
            )
        self._write_model(output_dir / "nasa_feature.json", result)
        return self._model_result(run_id, result)

    def sync_stellarium(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            validated_request = StellariumSyncRequest.model_validate(request)
        except ValidationError as exc:
            return _validation_failure(exc)

        run_id, output_dir = self._new_run("stellarium-sync")
        result = self.stellarium_bridge_factory().sync(validated_request)
        (output_dir / "stellarium_sync.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "ok": bool(result["ok"]),
            "run_id": run_id,
            "resources": self._resources_for_run(run_id),
            "result": result,
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

    def _weather_forecast(
        self, request: ObservingConditionsRequest
    ) -> WeatherForecast:
        try:
            return self.weather_provider_factory().get_forecast(request)
        except Exception:
            return WeatherForecast(
                samples=[],
                source=ExternalSource(
                    provider="Open-Meteo",
                    source_url=OPEN_METEO_ENDPOINT,
                    accessed_at=self.clock(),
                    from_cache=False,
                    availability="unavailable",
                    issue_code="weather_provider_error",
                ),
            )

    def _light_pollution(self, observer: Any) -> LightPollutionResult:
        try:
            return self.light_pollution_provider_factory().lookup(observer)
        except Exception:
            return LightPollutionResult(
                source=ExternalSource(
                    provider=BLACK_MARBLE_PROVIDER,
                    source_url=BLACK_MARBLE_SOURCE_URL,
                    accessed_at=self.clock(),
                    from_cache=False,
                    availability="unavailable",
                    issue_code="light_pollution_provider_error",
                )
            )

    @staticmethod
    def _write_model(path: Path, model: Any) -> None:
        path.write_text(model.model_dump_json(indent=2), encoding="utf-8")

    def _model_result(self, run_id: str, model: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "run_id": run_id,
            "resources": self._resources_for_run(run_id),
            "result": model.model_dump(mode="json"),
        }

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
        weather_cache_dir=Path(
            os.environ.get("STARSKILL_WEATHER_CACHE_DIR", "cache/weather")
        ),
        light_pollution_snapshot_path=Path(
            os.environ.get(
                "STARSKILL_LIGHT_POLLUTION_SNAPSHOT",
                "data/black_marble_snapshot.json",
            )
        ),
        nasa_cache_dir=Path(os.environ.get("STARSKILL_NASA_CACHE_DIR", "cache/nasa")),
        nasa_api_key=os.environ.get("STARSKILL_NASA_API_KEY"),
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

    @server.tool(structured_output=True)
    def get_observing_conditions(request: dict[str, Any]) -> dict[str, Any]:
        """Fetch auditable Open-Meteo forecast evidence for an observer and time range."""
        return service.get_observing_conditions(request)

    @server.tool(structured_output=True)
    def recommend_tonight(
        task: dict[str, Any],
        min_target_altitude_deg: float = 30.0,
        max_sun_altitude_deg: float = -12.0,
    ) -> dict[str, Any]:
        """Build a geometry-first, weather-aware recommendation with human review."""
        return service.recommend_tonight(
            task,
            min_target_altitude_deg=min_target_altitude_deg,
            max_sun_altitude_deg=max_sun_altitude_deg,
        )

    @server.tool(structured_output=True)
    def get_nasa_feature(date: str | None = None) -> dict[str, Any]:
        """Fetch NASA APOD provenance and metadata without returning API credentials."""
        return service.get_nasa_feature(date)

    @server.tool(structured_output=True)
    def sync_stellarium(request: dict[str, Any]) -> dict[str, Any]:
        """Synchronize a validated request with local Stellarium RemoteControl only."""
        return service.sync_stellarium(request)

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
