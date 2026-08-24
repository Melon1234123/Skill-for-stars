"""CLI support shared by the legacy evaluator and installed persona generator."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from starskill.evaluation.personas import (
    PersonaGenerationError,
    generate_tasks,
    parse_personas,
    write_task_dataset,
)
from starskill.evaluation.self_play import SelfPlayError, export_post_training_datasets


def add_generate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--personas",
        default="all",
        help="'all' or a comma-separated subset of supported persona names",
    )
    parser.add_argument("--tasks", type=int, required=True, help="number of tasks to generate")
    parser.add_argument("--seed", type=int, required=True, help="non-negative deterministic seed")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="new output directory; defaults to evaluation-runs/persona-tasks-seed-<seed>",
    )


def run_generate(args: argparse.Namespace) -> int:
    try:
        personas = parse_personas(args.personas)
        tasks = generate_tasks(personas=personas, task_count=args.tasks, seed=args.seed)
        output_dir = args.output_dir or Path("evaluation-runs") / f"persona-tasks-seed-{args.seed}"
        bundle = write_task_dataset(
            tasks=tasks,
            output_dir=output_dir,
            seed=args.seed,
            personas=personas,
        )
    except PersonaGenerationError as exc:
        _print_error(exc.code, str(exc))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "command": "generate",
                "seed": args.seed,
                "personas": list(personas),
                "task_count": bundle["task_count"],
                "task_families": [
                    "observation",
                    "catalog_query",
                    "cone_search",
                    "crossmatch",
                    "ambiguous_input",
                    "service_failure",
                    "scientific_adversarial",
                ],
                "resources": {
                    "tasks": bundle["tasks_file"],
                    "manifest": bundle["manifest_file"],
                },
                "tasks_sha256": bundle["tasks_sha256"],
                "output_dir": bundle["output_dir"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def add_export_datasets_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-root", type=Path, required=True, help="root containing self-play runs")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evaluation/datasets"),
        help="new dataset directory; defaults to evaluation/datasets",
    )


def run_export_datasets(args: argparse.Namespace) -> int:
    try:
        result = export_post_training_datasets(run_root=args.run_root, output_dir=args.output_dir)
    except SelfPlayError as exc:
        _print_error(exc.code, str(exc))
        return 1
    print(json.dumps({"ok": True, "command": "export-datasets", **result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starskill-eval")
    commands = parser.add_subparsers(dest="command", required=True)
    generate_parser = commands.add_parser("generate", help="generate deterministic persona evaluation tasks")
    add_generate_arguments(generate_parser)
    export_parser = commands.add_parser(
        "export-datasets", help="export validated self-play traces as post-training-ready JSONL"
    )
    add_export_datasets_arguments(export_parser)
    args = parser.parse_args(argv)
    if args.command == "generate":
        return run_generate(args)
    return run_export_datasets(args)


def _print_error(code: str, message: str) -> None:
    print(
        json.dumps({"ok": False, "error": code, "message": message}, ensure_ascii=False, sort_keys=True),
        file=sys.stderr,
    )
