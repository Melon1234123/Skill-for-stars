"""Command-line entry point for StarSkill."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

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
from starskill.pipeline import run_pipeline
from starskill.public_data_fetcher import (
    PublicDataError,
    PublicDataNotFoundError,
    PublicDataServiceError,
    PublicDataSizeError,
    PublicDataValidationError,
    UrlImageBackend,
    fetch_sdss_image,
    write_public_image_metadata,
)
from starskill.schemas import (
    EphemerisResult,
    ObservationTask,
    ResolvedTarget,
    SDSSImageRequest,
    SolarSystemRelationshipTask,
    VisibilityCriteria,
)
from starskill.solar_system_relationship import (
    calculate_solar_system_relationship,
    write_relationship_csv,
    write_relationship_json,
)
from starskill.sky_chart_catalog import (
    CatalogDownloadError,
    FullCatalogCache,
    load_hyg_source,
)
from starskill.target_resolver import (
    InvalidTargetNameError,
    SimbadBackend,
    TargetNotFoundError,
    TargetServiceError,
    resolve_target,
)
from starskill.visualizer import plot_visibility
from starskill.web_api import HttpCatalogFetcher, run_web_server


def print_resolution_error(
    exc: InvalidTargetNameError | TargetNotFoundError | TargetServiceError,
) -> None:
    print(
        json.dumps(
            {"resolved": False, "error": exc.code, "message": str(exc)},
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )


def print_validation_error(exc: ValidationError) -> None:
    details = [
        {
            "location": list(error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors(include_url=False, include_context=False)
    ]
    print(
        json.dumps(
            {
                "valid": False,
                "error": "validation_error",
                "details": details,
            },
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )


def print_public_data_error(exc: PublicDataError) -> None:
    print(
        json.dumps(
            {"downloaded": False, "error": exc.code, "message": str(exc)},
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )


def download_full_catalog(cache_dir: Path) -> dict[str, object]:
    """Download and publish the one fixed HYG source without exposing its URL."""
    summary = FullCatalogCache(cache_dir, load_hyg_source()).download_and_publish(
        HttpCatalogFetcher()
    )
    return {
        "downloaded": True,
        "version": summary.version,
        "row_count": summary.row_count,
        "compressed_sha256": summary.compressed_sha256,
        "csv_sha256": summary.csv_sha256,
        "cache_status": summary.status,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starskill")
    commands = parser.add_subparsers(dest="command", required=True)

    validate_parser = commands.add_parser("validate", help="validate a task JSON file")
    validate_parser.add_argument("input_path", type=Path)

    resolve_parser = commands.add_parser("resolve", help="resolve an astronomy target")
    resolve_parser.add_argument("target")
    resolve_parser.add_argument("--cache-dir", type=Path, default=Path("cache/targets"))
    resolve_parser.add_argument("--output", type=Path)

    ephemeris_parser = commands.add_parser(
        "ephemeris", help="calculate target, Sun, and Moon ephemerides"
    )
    ephemeris_parser.add_argument("input_path", type=Path)
    ephemeris_parser.add_argument("--target-file", type=Path, required=True)
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
        "relationship", help="calculate the Moon-Jupiter sky relationship"
    )
    relationship_parser.add_argument("input_path", type=Path)
    relationship_parser.add_argument("--output", type=Path, required=True)
    relationship_parser.add_argument("--metadata", type=Path, required=True)

    image_parser = commands.add_parser(
        "fetch-image", help="fetch and process the bounded SDSS DR18 M51 cutout"
    )
    image_parser.add_argument("input_path", type=Path)
    image_parser.add_argument("--output-dir", type=Path, required=True)
    image_parser.add_argument("--cache-dir", type=Path, default=Path("cache/sdss"))

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
                print(
                    json.dumps(
                        {"downloaded": False, "error": "catalog_download_failed"},
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                )
                return 1
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        try:
            run_web_server(port=args.port, open_browser=args.open)
        except (OSError, RuntimeError):
            print(
                json.dumps(
                    {"started": False, "error": "web_server_start_failed"},
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            return 1
        return 0

    if args.command == "resolve":
        try:
            target = resolve_target(
                args.target,
                backend=SimbadBackend(),
                cache_dir=args.cache_dir,
            )
        except InvalidTargetNameError as exc:
            print_resolution_error(exc)
            return 2
        except TargetNotFoundError as exc:
            print_resolution_error(exc)
            return 3
        except TargetServiceError as exc:
            print_resolution_error(exc)
            return 4
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(target.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"resolved": True, "target": target.model_dump(mode="json")},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "plan":
        try:
            ephemeris = EphemerisResult.model_validate_json(
                args.ephemeris_path.read_text(encoding="utf-8")
            )
            criteria = VisibilityCriteria(
                min_target_altitude_deg=args.min_target_altitude_deg,
                max_sun_altitude_deg=args.max_sun_altitude_deg,
            )
        except ValidationError as exc:
            print_validation_error(exc)
            return 2
        plan = plan_observation(ephemeris, criteria)
        write_visibility_csv(plan, args.output)
        write_observation_plan_json(plan, args.metadata)
        plot_visibility(plan, args.figure)
        print(
            json.dumps(
                {
                    "planned": True,
                    "sample_count": len(plan.samples),
                    "window_count": len(plan.windows),
                    "csv": str(args.output),
                    "metadata": str(args.metadata),
                    "figure": str(args.figure),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "relationship":
        payload = json.loads(args.input_path.read_text(encoding="utf-8"))
        try:
            relationship_task = SolarSystemRelationshipTask.model_validate(payload)
        except ValidationError as exc:
            print_validation_error(exc)
            return 2
        result = calculate_solar_system_relationship(relationship_task)
        write_relationship_csv(result, args.output)
        write_relationship_json(result, args.metadata)
        separations = [sample.angular_separation_deg for sample in result.samples]
        print(
            json.dumps(
                {
                    "calculated": True,
                    "sample_count": len(result.samples),
                    "minimum_separation_deg": min(separations),
                    "maximum_separation_deg": max(separations),
                    "csv": str(args.output),
                    "metadata": str(args.metadata),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "fetch-image":
        payload = json.loads(args.input_path.read_text(encoding="utf-8"))
        try:
            image_request = SDSSImageRequest.model_validate(payload)
        except ValidationError as exc:
            print_validation_error(exc)
            return 2
        try:
            result = fetch_sdss_image(
                image_request,
                cache_dir=args.cache_dir,
                source_path=args.output_dir / "data/m51_sdss.jpg",
                display_path=args.output_dir / "figures/m51_display.png",
                backend=UrlImageBackend(),
            )
        except PublicDataNotFoundError as exc:
            print_public_data_error(exc)
            return 6
        except PublicDataServiceError as exc:
            print_public_data_error(exc)
            return 7
        except PublicDataSizeError as exc:
            print_public_data_error(exc)
            return 8
        except PublicDataValidationError as exc:
            print_public_data_error(exc)
            return 9
        metadata_path = args.output_dir / "image_metadata.json"
        write_public_image_metadata(result, metadata_path)
        print(
            json.dumps(
                {
                    "downloaded": True,
                    "from_cache": result.source.from_cache,
                    "source_image": result.source_path,
                    "display_image": result.display_path,
                    "metadata": str(metadata_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    payload = json.loads(args.input_path.read_text(encoding="utf-8"))
    try:
        task = ObservationTask.model_validate(payload)
    except ValidationError as exc:
        print_validation_error(exc)
        return 2

    if args.command == "ephemeris":
        target = ResolvedTarget.model_validate_json(
            args.target_file.read_text(encoding="utf-8")
        )
        result = calculate_ephemeris(task, target)
        write_ephemeris_csv(result, args.output)
        write_ephemeris_json(result, args.metadata)
        print(
            json.dumps(
                {
                    "calculated": True,
                    "sample_count": len(result.samples),
                    "csv": str(args.output),
                    "metadata": str(args.metadata),
                },
                ensure_ascii=False,
                indent=2,
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
            print_validation_error(exc)
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
            print_resolution_error(exc)
            return 2
        except TargetNotFoundError as exc:
            print_resolution_error(exc)
            return 3
        except TargetServiceError as exc:
            print_resolution_error(exc)
            return 4
        print(
            json.dumps(
                {
                    "status": outcome.status,
                    "run_id": outcome.manifest.run_id,
                    "cache_hit": outcome.manifest.cache_hit,
                    "output_dir": outcome.output_dir,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if outcome.status == "success" else 5

    print(
        json.dumps(
            {"valid": True, "task": task.model_dump(mode="json")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0
