"""Command-line entry point for StarSkill."""

import argparse
import contextlib
import io
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from starskill.envelope import (
    artifact_record,
    emit,
    failure_payload,
    success_payload,
)
from starskill.ephemeris_calculator import (
    calculate_ephemeris,
    write_ephemeris_csv,
    write_ephemeris_json,
)
from starskill.light_pollution import (
    BLACK_MARBLE_PROVIDER,
    BLACK_MARBLE_SOURCE_URL,
    BlackMarbleLightPollutionProvider,
)
from starskill.nasa import NasaApodProvider
from starskill.observation_planner import (
    plan_observation,
    write_observation_plan_json,
    write_visibility_csv,
)
from starskill.external_data import UrlJsonBackend
from starskill.pipeline import run_pipeline, utc_now
from starskill.public_data_fetcher import (
    PublicDataError,
    PublicDataNotFoundError,
    PublicDataServiceError,
    PublicDataSizeError,
    PublicDataValidationError,
    UrlImageBackend,
    fetch_sdss_image,
    image_slug,
    write_public_image_metadata,
)
from starskill.recommendations import HUMAN_REVIEW_ITEMS, recommend_tonight
from starskill.schemas import (
    AstronomicalRelationshipTask,
    EphemerisResult,
    ExternalSource,
    LightPollutionResult,
    ObservationPlanResult,
    ObservationTask,
    ObservingConditionsRequest,
    ResolvedTarget,
    SDSSImageRequest,
    SolarSystemRelationshipTask,
    StellariumSyncRequest,
    TargetRef,
    VisibilityCriteria,
    WeatherForecast,
)
from starskill.solar_system_relationship import (
    calculate_astronomical_relationship,
    calculate_solar_system_relationship,
    write_astronomical_relationship_csv,
    write_relationship_csv,
    write_relationship_json,
)
from starskill.sky_chart_catalog import (
    CatalogDownloadError,
    FullCatalogCache,
    load_hyg_source,
)
from starskill.stellarium_bridge import DEFAULT_BASE_URL, StellariumBridge
from starskill.target_resolver import (
    InvalidTargetNameError,
    SimbadBackend,
    TargetNotFoundError,
    TargetResolutionError,
    TargetServiceError,
    resolve_target,
)
from starskill.target_references import resolve_target_ref
from starskill.visualizer import plot_visibility
from starskill.weather import OPEN_METEO_ENDPOINT, OpenMeteoWeatherProvider
from starskill.web_api import HttpCatalogFetcher, run_web_server


class InputValidationError(ValueError):
    """A user-provided input file cannot be parsed as a JSON object."""


TARGET_REF_ADAPTER = TypeAdapter(TargetRef)
RELATIONSHIP_TASK_ADAPTER = TypeAdapter(
    AstronomicalRelationshipTask | SolarSystemRelationshipTask
)
TARGET_BEARING_TASK_ADAPTER = TypeAdapter(
    ObservationTask | AstronomicalRelationshipTask | SolarSystemRelationshipTask
)
TARGET_BEARING_TASK_MODELS = {
    "observation_plan": ObservationTask,
    "astronomical_relationship": AstronomicalRelationshipTask,
    "solar_system_relationship": SolarSystemRelationshipTask,
}

AVAILABLE_EVIDENCE = ("fresh", "cached")


def load_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputValidationError(f"invalid JSON input: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InputValidationError("JSON input must be an object")
    return payload


def print_resolution_error(exc: TargetResolutionError, workflow: str) -> None:
    emit(
        failure_payload(
            workflow,
            error=exc.code,
            message=str(exc),
            legacy={"resolved": False},
        ),
        stream=sys.stderr,
    )


def resolution_error_exit_code(exc: TargetResolutionError) -> int:
    if isinstance(exc, InvalidTargetNameError):
        return 2
    if isinstance(exc, TargetNotFoundError):
        return 3
    if isinstance(exc, TargetServiceError):
        return 4
    return 2


def print_validation_error(exc: ValidationError, workflow: str) -> None:
    details = [
        {
            "location": list(error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors(include_url=False, include_context=False)
    ]
    emit(
        failure_payload(
            workflow,
            error="validation_error",
            details=details,
            legacy={"valid": False},
        ),
        stream=sys.stderr,
    )


def print_input_validation_error(exc: InputValidationError, workflow: str) -> None:
    emit(
        failure_payload(
            workflow,
            error="validation_error",
            details=[
                {
                    "location": [],
                    "message": str(exc),
                    "type": "json_invalid",
                }
            ],
            legacy={"valid": False},
        ),
        stream=sys.stderr,
    )


def print_public_data_error(exc: PublicDataError, workflow: str) -> None:
    emit(
        failure_payload(
            workflow,
            error=exc.code,
            message=str(exc),
            legacy={"downloaded": False},
        ),
        stream=sys.stderr,
    )


def download_full_catalog(cache_dir: Path) -> dict[str, object]:
    """Download and publish the one fixed HYG source without exposing its URL."""
    try:
        summary = FullCatalogCache(cache_dir, load_hyg_source()).download_and_publish(
            HttpCatalogFetcher()
        )
    except CatalogDownloadError:
        raise
    except (OSError, ValueError) as error:
        raise CatalogDownloadError("catalog cache setup failed") from error
    return {
        "downloaded": True,
        "version": summary.version,
        "row_count": summary.row_count,
        "compressed_sha256": summary.compressed_sha256,
        "csv_sha256": summary.csv_sha256,
        "cache_status": summary.status,
    }


def _weather_forecast_or_unavailable(
    provider: OpenMeteoWeatherProvider, request: ObservingConditionsRequest
) -> WeatherForecast:
    try:
        return provider.get_forecast(request)
    except Exception:
        return WeatherForecast(
            samples=[],
            source=ExternalSource(
                provider="Open-Meteo",
                source_url=OPEN_METEO_ENDPOINT,
                accessed_at=utc_now(),
                from_cache=False,
                availability="unavailable",
                issue_code="weather_provider_error",
            ),
        )


def _light_pollution_or_unavailable(
    provider: BlackMarbleLightPollutionProvider, observer: object
) -> LightPollutionResult:
    try:
        return provider.lookup(observer)
    except Exception:
        return LightPollutionResult(
            source=ExternalSource(
                provider=BLACK_MARBLE_PROVIDER,
                source_url=BLACK_MARBLE_SOURCE_URL,
                accessed_at=utc_now(),
                from_cache=False,
                availability="unavailable",
                issue_code="light_pollution_provider_error",
            )
        )


def _external_source_summary(source: ExternalSource) -> dict[str, object]:
    return source.model_dump(mode="json")


def _resolved_target_summary(target: object) -> dict[str, object]:
    """Summarize either a SIMBAD-resolved or a typed astronomical target."""
    summary: dict[str, object] = {
        "canonical_name": target.canonical_name,
        "ra_deg": target.ra_deg,
        "dec_deg": target.dec_deg,
    }
    for optional_field in ("object_type", "motion", "kind"):
        value = getattr(target, optional_field, None)
        if value is not None:
            summary[optional_field] = value
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starskill")
    commands = parser.add_subparsers(dest="command", required=True)

    validate_parser = commands.add_parser("validate", help="validate a task JSON file")
    validate_parser.add_argument("input_path", type=Path)

    resolve_parser = commands.add_parser("resolve", help="resolve an astronomy target")
    resolve_parser.add_argument("target")
    resolve_parser.add_argument("--cache-dir", type=Path, default=Path("cache/targets"))
    resolve_parser.add_argument("--output", type=Path)

    resolve_target_parser = commands.add_parser(
        "resolve-target", help="resolve a typed astronomy target reference"
    )
    resolve_target_parser.add_argument("input_path", type=Path)
    resolve_target_parser.add_argument(
        "--cache-dir", type=Path, default=Path("cache/targets")
    )
    resolve_target_parser.add_argument("--output", type=Path)

    ephemeris_parser = commands.add_parser(
        "ephemeris", help="calculate target, Sun, and Moon ephemerides"
    )
    ephemeris_parser.add_argument("input_path", type=Path)
    ephemeris_parser.add_argument("--target-file", type=Path)
    ephemeris_parser.add_argument(
        "--cache-dir", type=Path, default=Path("cache/targets")
    )
    ephemeris_parser.add_argument("--output", type=Path, required=True)
    ephemeris_parser.add_argument("--metadata", type=Path, required=True)

    plan_parser = commands.add_parser(
        "plan", help="create candidate observation windows and a visibility chart"
    )
    plan_parser.add_argument("ephemeris_path", type=Path)
    plan_parser.add_argument("--output", type=Path, required=True)
    plan_parser.add_argument("--metadata", type=Path, required=True)
    plan_parser.add_argument("--figure", type=Path, required=True)
    plan_parser.add_argument("--min-target-altitude-deg", type=float, default=30.0)
    plan_parser.add_argument("--max-sun-altitude-deg", type=float, default=-12.0)

    run_parser = commands.add_parser(
        "run", help="run the complete observation workflow and write an audit bundle"
    )
    run_parser.add_argument("input_path", type=Path)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--cache-dir", type=Path, default=Path("cache/targets"))
    run_parser.add_argument("--min-target-altitude-deg", type=float, default=30.0)
    run_parser.add_argument("--max-sun-altitude-deg", type=float, default=-12.0)

    relationship_parser = commands.add_parser(
        "relationship",
        help="calculate an apparent astronomical target relationship",
        description="Calculate an apparent astronomical target relationship.",
    )
    relationship_parser.add_argument("input_path", type=Path)
    relationship_parser.add_argument("--output", type=Path, required=True)
    relationship_parser.add_argument("--metadata", type=Path, required=True)
    relationship_parser.add_argument(
        "--cache-dir", type=Path, default=Path("cache/targets")
    )

    image_parser = commands.add_parser(
        "fetch-image", help="fetch and process a bounded SDSS DR18 cutout"
    )
    image_parser.add_argument("input_path", type=Path)
    image_parser.add_argument("--output-dir", type=Path, required=True)
    image_parser.add_argument("--cache-dir", type=Path, default=Path("cache/sdss"))

    conditions_parser = commands.add_parser(
        "conditions", help="fetch auditable Open-Meteo forecast evidence"
    )
    conditions_parser.add_argument("input_path", type=Path)
    conditions_parser.add_argument("--output", type=Path, required=True)
    conditions_parser.add_argument(
        "--cache-dir", type=Path, default=Path("cache/weather")
    )

    recommend_parser = commands.add_parser(
        "recommend",
        help="combine geometry, weather, and light pollution into a reviewed recommendation",
    )
    recommend_parser.add_argument("input_path", type=Path)
    recommend_parser.add_argument("--output-dir", type=Path, required=True)
    recommend_parser.add_argument(
        "--cache-dir", type=Path, default=Path("cache/targets")
    )
    recommend_parser.add_argument(
        "--weather-cache-dir", type=Path, default=Path("cache/weather")
    )
    recommend_parser.add_argument(
        "--light-pollution-snapshot",
        type=Path,
        default=Path("data/black_marble_snapshot.json"),
    )
    recommend_parser.add_argument("--min-target-altitude-deg", type=float, default=30.0)
    recommend_parser.add_argument("--max-sun-altitude-deg", type=float, default=-12.0)

    apod_parser = commands.add_parser(
        "apod", help="fetch NASA APOD metadata without exposing the API key"
    )
    apod_parser.add_argument("--date")
    apod_parser.add_argument("--output", type=Path, required=True)
    apod_parser.add_argument("--cache-dir", type=Path, default=Path("cache/nasa"))

    stellarium_parser = commands.add_parser(
        "stellarium-sync",
        help="synchronize a validated request with local Stellarium RemoteControl",
    )
    stellarium_parser.add_argument("input_path", type=Path)
    stellarium_parser.add_argument("--output", type=Path, required=True)
    stellarium_parser.add_argument(
        "--base-url",
        default=os.environ.get("STARSKILL_STELLARIUM_BASE_URL") or DEFAULT_BASE_URL,
    )

    sky_chart_parser = commands.add_parser(
        "sky-chart", help="start the local Python sky chart"
    )
    sky_chart_parser.add_argument("--port", type=int, default=8000)
    sky_chart_parser.add_argument("--open", action="store_true")
    sky_chart_parser.add_argument("--download-catalog", action="store_true")
    sky_chart_parser.add_argument(
        "--catalog-cache-dir", type=Path, default=Path("cache/sky-chart")
    )

    args = parser.parse_args(argv)

    if args.command == "sky-chart":
        if not 1024 <= args.port <= 65535:
            parser.error("--port must be between 1024 and 65535")
        if args.download_catalog:
            try:
                summary = download_full_catalog(args.catalog_cache_dir)
            except CatalogDownloadError:
                emit(
                    failure_payload(
                        "sky-chart-catalog",
                        error="catalog_download_failed",
                        legacy={"downloaded": False},
                    ),
                    stream=sys.stderr,
                )
                return 1
            emit(
                success_payload(
                    "sky-chart-catalog",
                    summary={
                        "version": summary["version"],
                        "row_count": summary["row_count"],
                        "cache_status": summary["cache_status"],
                    },
                    legacy=summary,
                )
            )
            return 0
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                run_web_server(
                    port=args.port,
                    open_browser=args.open,
                    catalog_cache_dir=args.catalog_cache_dir,
                )
        except SystemExit as error:
            if error.code != 1:
                raise
        except (OSError, RuntimeError):
            pass
        else:
            return 0
        emit(
            failure_payload(
                "sky-chart",
                error="web_server_start_failed",
                legacy={"started": False},
            ),
            stream=sys.stderr,
        )
        return 1

    if args.command == "resolve":
        try:
            target = resolve_target(
                args.target,
                backend=SimbadBackend(),
                cache_dir=args.cache_dir,
            )
        except InvalidTargetNameError as exc:
            print_resolution_error(exc, "resolve")
            return 2
        except TargetNotFoundError as exc:
            print_resolution_error(exc, "resolve")
            return 3
        except TargetServiceError as exc:
            print_resolution_error(exc, "resolve")
            return 4
        artifacts = []
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(target.model_dump_json(indent=2), encoding="utf-8")
            artifacts.append(artifact_record(args.output))
        emit(
            success_payload(
                "resolve",
                summary=_resolved_target_summary(target),
                artifacts=artifacts,
                sources=[target.source.model_dump(mode="json")],
                legacy={"resolved": True, "target": target.model_dump(mode="json")},
            )
        )
        return 0

    if args.command == "resolve-target":
        try:
            reference = TARGET_REF_ADAPTER.validate_python(
                load_json_object(args.input_path)
            )
        except InputValidationError as exc:
            print_input_validation_error(exc, "resolve-target")
            return 2
        except ValidationError as exc:
            print_validation_error(exc, "resolve-target")
            return 2
        try:
            target = resolve_target_ref(
                reference,
                backend=SimbadBackend() if reference.kind == "simbad" else None,
                cache_dir=args.cache_dir,
            )
        except (InvalidTargetNameError, TargetResolutionError) as exc:
            print_resolution_error(exc, "resolve-target")
            return resolution_error_exit_code(exc)
        artifacts = []
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(target.model_dump_json(indent=2), encoding="utf-8")
            artifacts.append(artifact_record(args.output))
        emit(
            success_payload(
                "resolve-target",
                summary=_resolved_target_summary(target),
                artifacts=artifacts,
                sources=[target.source.model_dump(mode="json")],
                legacy={"resolved": True, "target": target.model_dump(mode="json")},
            )
        )
        return 0

    if args.command == "plan":
        try:
            ephemeris = EphemerisResult.model_validate(
                load_json_object(args.ephemeris_path)
            )
            criteria = VisibilityCriteria(
                min_target_altitude_deg=args.min_target_altitude_deg,
                max_sun_altitude_deg=args.max_sun_altitude_deg,
            )
        except InputValidationError as exc:
            print_input_validation_error(exc, "plan")
            return 2
        except ValidationError as exc:
            print_validation_error(exc, "plan")
            return 2
        plan = plan_observation(ephemeris, criteria)
        write_visibility_csv(plan, args.output)
        write_observation_plan_json(plan, args.metadata)
        plot_visibility(plan, args.figure)
        emit(
            success_payload(
                "plan",
                summary={
                    "sample_count": len(plan.samples),
                    "window_count": len(plan.windows),
                },
                artifacts=[
                    artifact_record(args.output),
                    artifact_record(args.metadata),
                    artifact_record(args.figure),
                ],
                human_review=list(HUMAN_REVIEW_ITEMS),
                legacy={
                    "planned": True,
                    "sample_count": len(plan.samples),
                    "window_count": len(plan.windows),
                    "csv": str(args.output),
                    "metadata": str(args.metadata),
                    "figure": str(args.figure),
                },
            )
        )
        return 0

    if args.command == "relationship":
        try:
            payload = load_json_object(args.input_path)
        except InputValidationError as exc:
            print_input_validation_error(exc, "relationship")
            return 2
        try:
            relationship_task = RELATIONSHIP_TASK_ADAPTER.validate_python(payload)
        except ValidationError as exc:
            print_validation_error(exc, "relationship")
            return 2
        if isinstance(relationship_task, SolarSystemRelationshipTask):
            result = calculate_solar_system_relationship(relationship_task)
            write_relationship_csv(result, args.output)
        else:
            target_kinds = {
                relationship_task.primary.kind,
                relationship_task.secondary.kind,
            }
            try:
                result = calculate_astronomical_relationship(
                    relationship_task,
                    target_backend=(
                        SimbadBackend() if "simbad" in target_kinds else None
                    ),
                    horizons_backend=(
                        UrlJsonBackend() if "horizons" in target_kinds else None
                    ),
                    cache_dir=args.cache_dir,
                )
            except (InvalidTargetNameError, TargetResolutionError) as exc:
                print_resolution_error(exc, "relationship")
                return resolution_error_exit_code(exc)
            write_astronomical_relationship_csv(result, args.output)
        write_relationship_json(result, args.metadata)
        separations = [sample.angular_separation_deg for sample in result.samples]
        emit(
            success_payload(
                "relationship",
                summary={
                    "sample_count": len(result.samples),
                    "minimum_separation_deg": min(separations),
                    "maximum_separation_deg": max(separations),
                },
                artifacts=[
                    artifact_record(args.output),
                    artifact_record(args.metadata),
                ],
                human_review=[
                    "Angular separation is an apparent sky angle, not physical distance.",
                ],
                legacy={
                    "calculated": True,
                    "sample_count": len(result.samples),
                    "minimum_separation_deg": min(separations),
                    "maximum_separation_deg": max(separations),
                    "csv": str(args.output),
                    "metadata": str(args.metadata),
                },
            )
        )
        return 0

    if args.command == "fetch-image":
        try:
            payload = load_json_object(args.input_path)
        except InputValidationError as exc:
            print_input_validation_error(exc, "fetch-image")
            return 2
        try:
            image_request = SDSSImageRequest.model_validate(payload)
        except ValidationError as exc:
            print_validation_error(exc, "fetch-image")
            return 2
        slug = image_slug(image_request.target_name)
        try:
            result = fetch_sdss_image(
                image_request,
                cache_dir=args.cache_dir,
                source_path=args.output_dir / f"data/{slug}_sdss.jpg",
                display_path=args.output_dir / f"figures/{slug}_display.png",
                backend=UrlImageBackend(),
            )
        except PublicDataNotFoundError as exc:
            print_public_data_error(exc, "fetch-image")
            return 6
        except PublicDataServiceError as exc:
            print_public_data_error(exc, "fetch-image")
            return 7
        except PublicDataSizeError as exc:
            print_public_data_error(exc, "fetch-image")
            return 8
        except PublicDataValidationError as exc:
            print_public_data_error(exc, "fetch-image")
            return 9
        metadata_path = args.output_dir / "image_metadata.json"
        write_public_image_metadata(result, metadata_path)
        emit(
            success_payload(
                "fetch-image",
                summary={
                    "target_name": image_request.target_name,
                    "from_cache": result.source.from_cache,
                    "processing_steps": result.processing_steps,
                },
                artifacts=[
                    artifact_record(Path(result.source_path)),
                    artifact_record(Path(result.display_path)),
                    artifact_record(metadata_path),
                ],
                sources=[result.source.model_dump(mode="json")],
                human_review=[
                    "The display image is contrast-adjusted; do not present it as raw scientific data.",
                    "Preserve SDSS attribution and the license notice.",
                ],
                legacy={
                    "downloaded": True,
                    "from_cache": result.source.from_cache,
                    "source_image": result.source_path,
                    "display_image": result.display_path,
                    "metadata": str(metadata_path),
                },
            )
        )
        return 0

    if args.command == "conditions":
        try:
            request = ObservingConditionsRequest.model_validate(
                load_json_object(args.input_path)
            )
        except InputValidationError as exc:
            print_input_validation_error(exc, "conditions")
            return 2
        except ValidationError as exc:
            print_validation_error(exc, "conditions")
            return 2
        provider = OpenMeteoWeatherProvider(cache_dir=args.cache_dir)
        forecast = _weather_forecast_or_unavailable(provider, request)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(forecast.model_dump_json(indent=2), encoding="utf-8")
        available = forecast.source.availability in AVAILABLE_EVIDENCE
        emit(
            success_payload(
                "conditions",
                status="success" if available else "degraded",
                summary={
                    "sample_count": len(forecast.samples),
                    "availability": forecast.source.availability,
                    "issue_code": forecast.source.issue_code,
                },
                artifacts=[artifact_record(args.output)],
                sources=[_external_source_summary(forecast.source)],
                human_review=[
                    "Forecast data is planning evidence, not a go/no-go safety decision.",
                ],
            )
        )
        return 0 if available else 5

    if args.command == "recommend":
        try:
            task = ObservationTask.model_validate(load_json_object(args.input_path))
            criteria = VisibilityCriteria(
                min_target_altitude_deg=args.min_target_altitude_deg,
                max_sun_altitude_deg=args.max_sun_altitude_deg,
            )
        except InputValidationError as exc:
            print_input_validation_error(exc, "recommend")
            return 2
        except ValidationError as exc:
            print_validation_error(exc, "recommend")
            return 2
        try:
            outcome = run_pipeline(
                task,
                output_dir=args.output_dir,
                cache_dir=args.cache_dir,
                backend=SimbadBackend(),
                criteria=criteria,
            )
        except InvalidTargetNameError as exc:
            print_resolution_error(exc, "recommend")
            return 2
        except TargetNotFoundError as exc:
            print_resolution_error(exc, "recommend")
            return 3
        except TargetServiceError as exc:
            print_resolution_error(exc, "recommend")
            return 4
        try:
            geometry = ObservationPlanResult.model_validate_json(
                (Path(outcome.output_dir) / "result.json").read_text(encoding="utf-8")
            )
        except (OSError, ValidationError):
            emit(
                failure_payload(
                    "recommend",
                    error="recommendation_geometry_missing",
                    message="the pipeline did not produce a readable result.json",
                ),
                stream=sys.stderr,
            )
            return 5
        weather_provider = OpenMeteoWeatherProvider(cache_dir=args.weather_cache_dir)
        weather = _weather_forecast_or_unavailable(
            weather_provider,
            ObservingConditionsRequest(observer=task.observer, time_range=task.time_range),
        )
        light_provider = BlackMarbleLightPollutionProvider(
            snapshot_path=args.light_pollution_snapshot
        )
        light_pollution = _light_pollution_or_unavailable(light_provider, task.observer)
        recommendation = recommend_tonight(geometry, weather, light_pollution)
        conditions_path = args.output_dir / "conditions.json"
        recommendation_path = args.output_dir / "recommendation.json"
        conditions_path.write_text(weather.model_dump_json(indent=2), encoding="utf-8")
        recommendation_path.write_text(
            recommendation.model_dump_json(indent=2), encoding="utf-8"
        )
        weather_available = weather.source.availability in AVAILABLE_EVIDENCE
        status = (
            "success" if outcome.status == "success" and weather_available else "degraded"
        )
        grades = [window.grade for window in recommendation.recommendations]
        emit(
            success_payload(
                "recommend",
                status=status,
                summary={
                    "run_id": outcome.manifest.run_id,
                    "pipeline_status": outcome.status,
                    "window_count": len(recommendation.recommendations),
                    "grades": {
                        grade: grades.count(grade)
                        for grade in ("recommended", "caution", "not_recommended")
                    },
                    "weather_availability": weather.source.availability,
                    "light_pollution_availability": (
                        light_pollution.source.availability
                    ),
                    "output_dir": outcome.output_dir,
                },
                artifacts=[
                    artifact_record(conditions_path),
                    artifact_record(recommendation_path),
                ],
                sources=[
                    _external_source_summary(source)
                    for source in recommendation.provenance
                ],
                human_review=recommendation.human_review,
            )
        )
        return 0 if status == "success" else 5

    if args.command == "apod":
        provider = NasaApodProvider(
            api_key=os.environ.get("STARSKILL_NASA_API_KEY"),
            cache_dir=args.cache_dir,
        )
        feature = provider.get_feature(args.date)
        if feature.source.issue_code == "nasa_apod_date_invalid":
            emit(
                failure_payload(
                    "apod",
                    error="validation_error",
                    details=[
                        {
                            "location": ["date"],
                            "message": "APOD date must be an ISO calendar date",
                            "type": "date_invalid",
                        }
                    ],
                    legacy={"valid": False},
                ),
                stream=sys.stderr,
            )
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(feature.model_dump_json(indent=2), encoding="utf-8")
        available = feature.source.availability in AVAILABLE_EVIDENCE
        emit(
            success_payload(
                "apod",
                status="success" if available else "degraded",
                summary={
                    "date": feature.date,
                    "title": feature.title,
                    "media_type": feature.media_type,
                    "availability": feature.source.availability,
                    "issue_code": feature.source.issue_code,
                },
                artifacts=[artifact_record(args.output)],
                sources=[_external_source_summary(feature.source)],
                human_review=[
                    "Preserve NASA APOD attribution and any copyright notice before reuse.",
                ],
            )
        )
        return 0 if available else 5

    if args.command == "stellarium-sync":
        try:
            request = StellariumSyncRequest.model_validate(
                load_json_object(args.input_path)
            )
        except InputValidationError as exc:
            print_input_validation_error(exc, "stellarium-sync")
            return 2
        except ValidationError as exc:
            print_validation_error(exc, "stellarium-sync")
            return 2
        try:
            bridge = StellariumBridge(base_url=args.base_url)
        except ValueError as exc:
            emit(
                failure_payload(
                    "stellarium-sync",
                    error="invalid_base_url",
                    message=str(exc),
                ),
                stream=sys.stderr,
            )
            return 2
        outcome = bridge.sync(request)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not outcome.get("ok"):
            emit(
                failure_payload(
                    "stellarium-sync",
                    error="connection_error",
                    message="local Stellarium RemoteControl is unreachable",
                    legacy={
                        "synced": False,
                        "operations": outcome.get("operations", []),
                        "output": str(args.output),
                    },
                ),
                stream=sys.stderr,
            )
            return 10
        emit(
            success_payload(
                "stellarium-sync",
                summary={
                    "base_url": outcome.get("base_url"),
                    "operations": outcome.get("operations", []),
                    "target": request.target,
                },
                artifacts=[artifact_record(args.output)],
                legacy={"synced": True},
            )
        )
        return 0

    try:
        payload = load_json_object(args.input_path)
    except InputValidationError as exc:
        print_input_validation_error(exc, args.command)
        return 2
    if args.command == "validate":
        discriminator = payload.get("task_type", "observation_plan")
        task_model = (
            TARGET_BEARING_TASK_MODELS.get(discriminator)
            if isinstance(discriminator, str)
            else None
        )
        if task_model is None:
            try:
                TARGET_BEARING_TASK_ADAPTER.validate_python(payload)
            except ValidationError as exc:
                print_validation_error(exc, "validate")
                return 2
            raise AssertionError("unreachable task discriminator")
        try:
            task = task_model.model_validate(payload)
        except ValidationError as exc:
            print_validation_error(exc, "validate")
            return 2
        emit(
            success_payload(
                "validate",
                summary={"task_type": task.task_type},
                legacy={"valid": True, "task": task.model_dump(mode="json")},
            )
        )
        return 0

    try:
        task = ObservationTask.model_validate(payload)
    except ValidationError as exc:
        print_validation_error(exc, args.command)
        return 2

    if args.command == "ephemeris":
        if args.target_file is not None:
            try:
                target = ResolvedTarget.model_validate(
                    load_json_object(args.target_file)
                )
            except InputValidationError as exc:
                print_input_validation_error(exc, "ephemeris")
                return 2
            except ValidationError as exc:
                print_validation_error(exc, "ephemeris")
                return 2
        else:
            try:
                target = resolve_target_ref(
                    task.target,
                    backend=(
                        SimbadBackend() if task.target.kind == "simbad" else None
                    ),
                    cache_dir=args.cache_dir,
                )
            except (InvalidTargetNameError, TargetResolutionError) as exc:
                print_resolution_error(exc, "ephemeris")
                return resolution_error_exit_code(exc)
        result = calculate_ephemeris(task, target)
        write_ephemeris_csv(result, args.output)
        write_ephemeris_json(result, args.metadata)
        emit(
            success_payload(
                "ephemeris",
                summary={"sample_count": len(result.samples)},
                artifacts=[
                    artifact_record(args.output),
                    artifact_record(args.metadata),
                ],
                legacy={
                    "calculated": True,
                    "sample_count": len(result.samples),
                    "csv": str(args.output),
                    "metadata": str(args.metadata),
                },
            )
        )
        return 0

    if args.command == "run":
        try:
            criteria = VisibilityCriteria(
                min_target_altitude_deg=args.min_target_altitude_deg,
                max_sun_altitude_deg=args.max_sun_altitude_deg,
            )
        except ValidationError as exc:
            print_validation_error(exc, "run")
            return 2
        try:
            outcome = run_pipeline(
                task,
                output_dir=args.output_dir,
                cache_dir=args.cache_dir,
                backend=SimbadBackend(),
                criteria=criteria,
            )
        except InvalidTargetNameError as exc:
            print_resolution_error(exc, "run")
            return 2
        except TargetNotFoundError as exc:
            print_resolution_error(exc, "run")
            return 3
        except TargetServiceError as exc:
            print_resolution_error(exc, "run")
            return 4
        emit(
            success_payload(
                "run",
                status=outcome.status,
                summary={
                    "run_id": outcome.manifest.run_id,
                    "cache_hit": outcome.manifest.cache_hit,
                    "output_dir": outcome.output_dir,
                    "issues": [
                        issue.model_dump(mode="json")
                        for issue in outcome.manifest.issues
                    ],
                },
                artifacts=[
                    record.model_dump(mode="json")
                    for record in outcome.manifest.artifacts
                ],
                human_review=list(HUMAN_REVIEW_ITEMS),
                legacy={
                    "status": outcome.status,
                    "run_id": outcome.manifest.run_id,
                    "cache_hit": outcome.manifest.cache_hit,
                    "output_dir": outcome.output_dir,
                },
            )
        )
        return 0 if outcome.status == "success" else 5

    raise AssertionError(f"unhandled command: {args.command}")
