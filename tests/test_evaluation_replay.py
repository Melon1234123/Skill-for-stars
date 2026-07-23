import json
from pathlib import Path

from scripts.evaluate_starskill import main
from tests.fixtures.evaluation.replay_fixtures import (
    write_core_m42_bundle,
    write_review_report,
    write_variant_m42_no_window_bundle,
)


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


def test_replay_command_accepts_a_valid_empty_window_bundle(
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
        issues=["Explains the empty geometric result clearly."],
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
