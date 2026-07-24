import json
import sys
from pathlib import Path

import pytest

from scripts.evaluate_starskill import main
from starskill.evaluation.runner import execute_case
from tests.fixtures.evaluation.replay_fixtures import (
    read_script_owned_relationship_bundle,
    write_core_m42_bundle,
    write_review_report,
    write_variant_m42_no_window_bundle,
)
from tests.fixtures.evaluation import replay_fixtures


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_replay_command_accepts_a_complete_core_m42_bundle(tmp_path) -> None:
    run_dir = tmp_path / "core-m42-run"
    output_dir = tmp_path / "core-m42-score"
    review_file = tmp_path / "reviews" / "core-m42-teacher.json"

    write_core_m42_bundle(run_dir)
    write_review_report(
        review_file,
        case_id="core-m42-beijing",
        reviewer_role="research",
        role_usability_points=5,
        safety_review_points=6,
    )

    exit_code = main(
        [
            "replay",
            "--case",
            str(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json"),
            "--run-dir",
            str(run_dir),
            "--return-code",
            "0",
            "--stdout-file",
            str(run_dir / "stdout.txt"),
            "--stderr-file",
            str(run_dir / "stderr.txt"),
            "--review-file",
            str(review_file),
            "--output-dir",
            str(output_dir),
        ]
    )

    machine_payload = json.loads(
        (output_dir / "machine_checks.json").read_text(encoding="utf-8")
    )
    score_payload = json.loads((output_dir / "score.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert machine_payload["machine_check"]["hard_gate_passed"] is True
    assert machine_payload["machine_check"]["issues"] == []
    assert {
        "input.json",
        "intermediate/target_resolved.json",
        "intermediate/ephemeris.json",
        "intermediate/ephemeris.csv",
        "intermediate/visibility.csv",
        "figures/visibility_curve.png",
    }.issubset(set(machine_payload["machine_check"]["checked_files"]))
    assert score_payload["score"]["hard_gate_passed"] is True
    assert score_payload["score"]["base_score"] == 100


def test_replay_command_accepts_a_successful_no_window_bundle_with_exit_code_0(
    tmp_path,
) -> None:
    run_dir = tmp_path / "variant-m42-run"
    output_dir = tmp_path / "variant-m42-score"
    review_file = tmp_path / "reviews" / "variant-m42-teacher.json"

    write_variant_m42_no_window_bundle(run_dir)
    write_review_report(
        review_file,
        case_id="variant-m42-no-window",
        reviewer_role="research",
        role_usability_points=5,
        safety_review_points=6,
        issues=["Explains the empty observation-window result clearly."],
    )

    exit_code = main(
        [
            "replay",
            "--case",
            str(PROJECT_ROOT / "evaluation/cases/variants/variant-m42-no-window.json"),
            "--run-dir",
            str(run_dir),
            "--return-code",
            "0",
            "--stdout-file",
            str(run_dir / "stdout.txt"),
            "--stderr-file",
            str(run_dir / "stderr.txt"),
            "--review-file",
            str(review_file),
            "--output-dir",
            str(output_dir),
        ]
    )

    machine_payload = json.loads(
        (output_dir / "machine_checks.json").read_text(encoding="utf-8")
    )
    score_payload = json.loads((output_dir / "score.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert machine_payload["machine_check"]["hard_gate_passed"] is True
    assert machine_payload["machine_check"]["issues"] == []
    assert score_payload["score"]["hard_gate_passed"] is True


@pytest.mark.parametrize(
    ("case_id", "m31_slot"),
    [
        ("generic-mars-m31", "secondary"),
        ("generic-m31-coordinate", "primary"),
    ],
)
def test_generic_relationship_case_records_and_replays_v2_artifacts(
    tmp_path: Path, case_id: str, m31_slot: str
) -> None:
    case_path = PROJECT_ROOT / f"evaluation/cases/generic/{case_id}.json"
    run_dir = tmp_path / case_id
    target_cache_dir = tmp_path / "target-cache"
    replay_fixtures.write_fixed_m31_cache(target_cache_dir)

    execution = execute_case(
        case_path,
        run_dir,
        python_executable=Path(sys.executable),
        target_cache_dir=target_cache_dir,
        image_cache_dir=tmp_path / "image-cache",
    )
    metadata, csv_text = read_script_owned_relationship_bundle(run_dir)
    csv_header = csv_text.splitlines()[0]

    assert execution.return_code == 0
    assert execution.command_argv[:4] == [
        str(Path(sys.executable)),
        "-m",
        "starskill",
        "relationship",
    ]
    assert execution.command_argv[-2:] == ["--cache-dir", str(target_cache_dir.resolve())]
    assert metadata["settings"]["schema_version"] == "2.0"
    assert metadata[m31_slot]["kind"] == "simbad"
    assert metadata[m31_slot]["motion"] == "fixed_icrs"
    assert metadata[m31_slot]["source"]["provider"] == "simbad_cache"
    assert metadata[m31_slot]["source"]["from_cache"] is True
    assert metadata[m31_slot]["catalog_target"]["source"]["from_cache"] is True
    assert "primary_altitude_deg" in csv_header
    assert (run_dir / "stdout.txt").is_file()
    assert (run_dir / "stderr.txt").read_text(encoding="utf-8") == ""
    assert (run_dir / "exit_code.txt").read_text(encoding="utf-8") == "0\n"
    assert execution.artifact_sha256["relationship.csv"]
    assert execution.artifact_sha256["relationship.json"]
    assert execution.artifact_sha256["stdout.txt"]
    assert execution.artifact_sha256["stderr.txt"]

    score_dir = tmp_path / "score"
    replay_exit = main(
        [
            "replay",
            "--case",
            str(case_path),
            "--run-dir",
            str(run_dir),
            "--output-dir",
            str(score_dir),
        ]
    )
    score = json.loads((score_dir / "score.json").read_text(encoding="utf-8"))

    assert replay_exit == 0
    assert score["score"]["hard_gate_passed"] is True
