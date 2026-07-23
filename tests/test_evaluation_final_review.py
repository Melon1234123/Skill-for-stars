import json
import shutil
import hashlib
import sys
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

import pytest
from PIL import Image

from scripts.evaluate_starskill import main
from starskill.evaluation.cases import load_case
from starskill.evaluation.checks import check_run
from starskill.evaluation.reporting import ReportError, collect_score_reports, validate_bonus_evidence
from starskill.evaluation.runner import execute_case
from tests.fixtures.evaluation.replay_fixtures import write_core_m42_bundle, write_review_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _record(root: Path, relative_path: str) -> dict[str, object]:
    content = (root / relative_path).read_bytes()
    return {"path": relative_path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _write_m51_bundle(run_dir: Path, *, from_cache: bool, legacy_paths: bool = False) -> None:
    (run_dir / "data").mkdir(parents=True)
    (run_dir / "figures").mkdir()
    source = Image.new("RGB", (512, 512))
    display = Image.new("RGB", (512, 576))
    for y in range(source.height):
        for x in range(source.width):
            source.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256))
    for y in range(display.height):
        for x in range(display.width):
            display.putpixel((x, y), ((x * 5) % 256, (y * 3) % 256, ((x + y) * 11) % 256))
    source.save(run_dir / "data/m51_sdss.jpg", format="JPEG")
    display.save(run_dir / "figures/m51_display.png", format="PNG")
    source_path = "runs\\day6_m51\\data\\m51_sdss.jpg" if legacy_paths else "data/m51_sdss.jpg"
    display_path = "runs\\day6_m51\\figures\\m51_display.png" if legacy_paths else "figures/m51_display.png"
    (run_dir / "image_metadata.json").write_text(json.dumps({
        "request": {"target_name": "M51", "ra_deg": 202.4696, "scale_arcsec_per_pixel": 0.396, "width": 512, "height": 512},
        "source": {"database": "SDSS SkyServer", "from_cache": from_cache},
        "source_path": source_path,
        "display_path": display_path,
    }), encoding="utf-8")
    artifacts = [_record(run_dir, path) for path in ("image_metadata.json", "data/m51_sdss.jpg", "figures/m51_display.png")]
    (run_dir / "run.json").write_text(json.dumps({"status": "success", "artifacts": artifacts, "issues": []}), encoding="utf-8")


def test_replay_returns_structured_error_for_malformed_case_manifest(tmp_path: Path) -> None:
    case_path = tmp_path / "malformed-case.json"
    case_path.write_text("{not-json", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(case_path),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "0",
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code == 1
    assert payload["error"] == "invalid_case_manifest"


def test_replay_rejects_missing_worker_execution_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "case_id": "failure-invalid-timezone",
                "reviewer_role": "outreach",
                "role_usability_points": 5,
                "safety_review_points": 6,
                "critical_issues": [],
                "issues": [],
                "confidence": 1,
                "recommendation": "pass",
            }
        ),
        encoding="utf-8",
    )

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                "evaluation/cases/failures/failure-invalid-timezone.json",
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--review-file",
                str(review_path),
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code == 1
    assert payload["error"] == "invalid_execution_evidence"


def test_replay_rejects_json_shaped_fake_worker_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "stderr.json").write_text(
        json.dumps({"valid": False, "error": "validation_error"}), encoding="utf-8"
    )
    (run_dir / "stdout.txt").write_text("", encoding="utf-8")
    (run_dir / "stderr.txt").write_text("", encoding="utf-8")
    (run_dir / "exit_code.txt").write_text("2\n", encoding="utf-8")
    (run_dir / "execution.json").write_text('{"anything": 1}\n', encoding="utf-8")
    review_path = tmp_path / "review.json"
    write_review_report(
        review_path,
        case_id="failure-invalid-timezone",
        reviewer_role="research",
        role_usability_points=5,
        safety_review_points=6,
    )

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main([
            "replay", "--case", str(PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"),
            "--run-dir", str(run_dir), "--return-code", "2", "--review-file", str(review_path),
            "--output-dir", str(tmp_path / "score"),
        ])

    assert exit_code == 1
    assert json.loads(stderr.getvalue())["error"] == "invalid_execution_evidence"


def test_real_shaped_m51_project_relative_metadata_paths_replay_as_run_relative(tmp_path: Path) -> None:
    run_dir = tmp_path / "m51"
    _write_m51_bundle(run_dir, from_cache=False, legacy_paths=True)
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m51-sdss.json")

    report = check_run(case, run_dir, 0, '{"downloaded": true}', "")

    assert report.hard_gate_passed is True
    assert not any(issue.code == "manifest_missing_artifact" for issue in report.issues)


def test_m51_metadata_does_not_rebind_unrelated_basename(tmp_path: Path) -> None:
    run_dir = tmp_path / "m51"
    _write_m51_bundle(run_dir, from_cache=False)
    metadata_path = run_dir / "image_metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["source_path"] = "unrelated/project/m51_sdss.jpg"
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")
    run_manifest = run_dir / "run.json"
    manifest = json.loads(run_manifest.read_text(encoding="utf-8"))
    manifest["artifacts"] = [_record(run_dir, path) for path in ("image_metadata.json", "data/m51_sdss.jpg", "figures/m51_display.png")]
    run_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m51-sdss.json")

    report = check_run(case, run_dir, 0, '{"downloaded": true}', "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "invalid_metadata_artifact_path" for issue in report.issues)


def test_cache_reuse_and_moon_csv_mismatches_are_critical(tmp_path: Path) -> None:
    m51_dir = tmp_path / "m51"
    _write_m51_bundle(m51_dir, from_cache=False)
    cache_case = load_case(PROJECT_ROOT / "evaluation/cases/variants/variant-m51-cache-reuse.json")
    cache_report = check_run(cache_case, m51_dir, 0, '{"downloaded": true}', "")
    assert any(issue.code == "json_assertion_mismatch" for issue in cache_report.issues)

    moon_dir = tmp_path / "moon"
    moon_dir.mkdir()
    (moon_dir / "relationship.csv").write_text(
        "moon_altitude_deg,angular_separation_deg\n5.226,12.0\n", encoding="utf-8"
    )
    (moon_dir / "relationship.json").write_text(json.dumps({
        "task": {"task_type": "solar_system_relationship"},
        "settings": {"solar_system_ephemeris": "builtin"},
    }), encoding="utf-8")
    moon_case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-moon-jupiter-shanghai.json")
    moon_report = check_run(moon_case, moon_dir, 0, '{"calculated": true}', "")
    assert any(issue.code == "csv_assertion_mismatch" for issue in moon_report.issues)


def test_moon_jupiter_variant_manifests_have_deterministic_csv_assertions() -> None:
    for name in ("variant-moon-jupiter-interval.json", "variant-moon-jupiter-location-time.json"):
        case = load_case(PROJECT_ROOT / "evaluation/cases/variants" / name)
        assert case.csv_assertions


def _bonus_claim() -> dict[str, object]:
    return {
        "standardization": {
            "awarded": 3,
            "evidence_paths": ["baseline.json", "comparison.json", "verification.json"],
            "baseline": {"path": "baseline.json", "description": "baseline measurement"},
            "comparison": {"path": "comparison.json", "description": "comparison measurement"},
            "verification": {"path": "verification.json", "description": "focused test result"},
        }
    }


def _write_bonus_evidence(run_dir: Path) -> None:
    (run_dir / "baseline.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_measurement",
                "metric": "runtime_seconds",
                "unit": "seconds",
                "value": 12.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "comparison.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_measurement",
                "metric": "runtime_seconds",
                "unit": "seconds",
                "value": 8.0,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "verification.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_verification",
                "command": "python -m pytest tests/test_example.py -q",
                "exit_code": 0,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )


def test_bonus_evidence_requires_linked_structured_measurements_and_verification(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_bonus_evidence(run_dir)
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")

    validate_bonus_evidence(_bonus_claim(), run_dir, case)

    for path, content in (
        ("baseline.json", ""),
        ("baseline.json", "arbitrary prose only\n"),
        ("comparison.json", "arbitrary prose only\n"),
        ("verification.json", "arbitrary prose only\n"),
    ):
        _write_bonus_evidence(run_dir)
        (run_dir / path).write_text(content, encoding="utf-8")
        with pytest.raises(ReportError, match="bonus standardization"):
            validate_bonus_evidence(_bonus_claim(), run_dir, case)

    _write_bonus_evidence(run_dir)
    missing = _bonus_claim()
    missing["standardization"]["baseline"]["path"] = "missing.json"  # type: ignore[index]
    missing["standardization"]["evidence_paths"][0] = "missing.json"  # type: ignore[index]
    with pytest.raises(ReportError, match="missing evidence"):
        validate_bonus_evidence(missing, run_dir, case)

    escaping = _bonus_claim()
    escaping["standardization"]["comparison"]["path"] = "../comparison.json"  # type: ignore[index]
    escaping["standardization"]["evidence_paths"][1] = "../comparison.json"  # type: ignore[index]
    with pytest.raises(ReportError, match="remain inside run_dir"):
        validate_bonus_evidence(escaping, run_dir, case)

    for field in ("baseline", "comparison", "verification"):
        unlinked = _bonus_claim()
        unlinked["standardization"]["evidence_paths"].remove(  # type: ignore[index]
            unlinked["standardization"][field]["path"]  # type: ignore[index]
        )
        with pytest.raises(ReportError, match="must be listed in evidence_paths"):
            validate_bonus_evidence(unlinked, run_dir, case)


def test_replay_returns_structured_error_for_oversized_bonus_measurement_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    execute_case(
        PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json",
        run_dir,
        python_executable=Path(sys.executable),
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
    )
    (run_dir / "baseline.json").write_text(
        '{"record_type":"starskill_bonus_measurement","metric":"runtime_seconds",'
        '"unit":"seconds","value":' + "9" * 10_000 + "}",
        encoding="utf-8",
    )
    (run_dir / "comparison.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_measurement",
                "metric": "runtime_seconds",
                "unit": "seconds",
                "value": 8,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "verification.json").write_text(
        json.dumps(
            {
                "record_type": "starskill_bonus_verification",
                "command": "python -m pytest tests/test_evaluation_final_review.py -q",
                "exit_code": 0,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    bonus_path = tmp_path / "bonus.json"
    bonus_path.write_text(json.dumps(_bonus_claim()), encoding="utf-8")

    stderr = StringIO()
    with redirect_stderr(stderr):
        exit_code = main(
            [
                "replay",
                "--case",
                str(PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"),
                "--run-dir",
                str(run_dir),
                "--return-code",
                "2",
                "--bonus-file",
                str(bonus_path),
                "--output-dir",
                str(tmp_path / "score"),
            ]
        )

    payload = json.loads(stderr.getvalue())
    assert exit_code != 0
    assert payload["error"] == "invalid_bonus_evidence"


def test_guangzhou_moon_jupiter_variant_matches_its_task_and_rejects_shanghai_values(tmp_path: Path) -> None:
    case = load_case(
        PROJECT_ROOT / "evaluation/cases/variants/variant-moon-jupiter-location-time.json"
    )
    task = json.loads(
        (PROJECT_ROOT / "evaluation/tasks/variant-moon-jupiter-location-time.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {assertion.column: assertion.expected for assertion in case.csv_assertions}
    assert task["observer"]["location_name"] == "Guangzhou"
    assert task["observer"]["longitude"] == 113.2644
    assert task["observer"]["latitude"] == 23.1291
    assert task["time_range"]["start"] == "2026-03-21 18:30:00"
    assert expected == {"moon_altitude_deg": 31.635, "angular_separation_deg": 73.765}

    run_dir = tmp_path / "moon"
    run_dir.mkdir()
    (run_dir / "relationship.json").write_text(
        json.dumps({"task": {"task_type": "solar_system_relationship"}}), encoding="utf-8"
    )
    (run_dir / "relationship.csv").write_text(
        "moon_altitude_deg,angular_separation_deg\n31.635,73.765\n", encoding="utf-8"
    )
    assert check_run(case, run_dir, 0, '{"calculated": true}', "").hard_gate_passed is True

    (run_dir / "relationship.csv").write_text(
        "moon_altitude_deg,angular_separation_deg\n5.226,87.917\n", encoding="utf-8"
    )
    report = check_run(case, run_dir, 0, '{"calculated": true}', "")
    assert report.hard_gate_passed is False
    assert sum(issue.code == "csv_assertion_mismatch" for issue in report.issues) == 2


def test_aggregate_rejects_tampered_score_and_wrong_reviewer_rotation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_core_m42_bundle(run_dir)
    review_path = tmp_path / "review.json"
    write_review_report(
        review_path,
        case_id="core-m42-beijing",
        reviewer_role="research",
        role_usability_points=5,
        safety_review_points=6,
    )
    score_dir = tmp_path / "scores" / "core-m42"
    assert main([
        "replay", "--case", str(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json"),
        "--run-dir", str(run_dir), "--return-code", "0",
        "--stdout-file", str(run_dir / "stdout.txt"), "--stderr-file", str(run_dir / "stderr.txt"),
        "--review-file", str(review_path), "--output-dir", str(score_dir),
    ]) == 0
    score_path = score_dir / "score.json"
    payload = json.loads(score_path.read_text(encoding="utf-8"))
    payload["score"]["base_score"] = 0
    score_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReportError, match="does not match machine"):
        collect_score_reports(tmp_path / "scores", cases_root=PROJECT_ROOT / "evaluation/cases")

    payload["score"]["base_score"] = 100
    payload["review"]["reviewer_role"] = "outreach"
    score_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReportError, match="rotation"):
        collect_score_reports(tmp_path / "scores", cases_root=PROJECT_ROOT / "evaluation/cases")


def test_aggregate_rejects_synchronized_run_ids_for_copied_physical_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_core_m42_bundle(run_dir)
    score_root = tmp_path / "scores"
    original_score_dir = score_root / "original"
    assert main(
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
            "--output-dir",
            str(original_score_dir),
        ]
    ) == 0

    for index in range(3):
        score_dir = score_root / f"copy-{index}"
        shutil.copytree(original_score_dir, score_dir)
        score_path = score_dir / "score.json"
        score_payload = json.loads(score_path.read_text(encoding="utf-8"))
        score_payload["run_id"] = f"copied-run-{index}"
        score_payload["machine_checks_path"] = str(score_dir / "machine_checks.json")
        score_payload["summary_path"] = str(score_dir / "summary.md")
        score_path.write_text(json.dumps(score_payload), encoding="utf-8")

        machine_path = score_dir / "machine_checks.json"
        machine_payload = json.loads(machine_path.read_text(encoding="utf-8"))
        machine_payload["run"]["run_id"] = f"copied-run-{index}"
        machine_path.write_text(json.dumps(machine_payload), encoding="utf-8")

    shutil.rmtree(original_score_dir)

    with pytest.raises(ReportError, match="run_id must match the physical run directory"):
        collect_score_reports(score_root, cases_root=PROJECT_ROOT / "evaluation/cases")


def test_aggregate_rejects_tampered_canonical_worker_roles(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_core_m42_bundle(run_dir)
    score_dir = tmp_path / "scores" / "core-m42"
    assert main(
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
            "--output-dir",
            str(score_dir),
        ]
    ) == 0
    score_path = score_dir / "score.json"
    score_payload = json.loads(score_path.read_text(encoding="utf-8"))
    score_payload["worker_role"] = "research"
    score_path.write_text(json.dumps(score_payload), encoding="utf-8")
    execution_path = run_dir / "execution.json"
    execution_payload = json.loads(execution_path.read_text(encoding="utf-8"))
    execution_payload["role"] = "research"
    execution_path.write_text(json.dumps(execution_payload) + "\n", encoding="utf-8")

    with pytest.raises(ReportError, match="worker role"):
        collect_score_reports(tmp_path / "scores", cases_root=PROJECT_ROOT / "evaluation/cases")
