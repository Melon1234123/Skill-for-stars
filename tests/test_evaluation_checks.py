import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from starskill.evaluation.cases import load_case
from starskill.evaluation.checks import check_run
from starskill.evaluation.models import EvaluationCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_image(path: Path, *, fmt: str, size: tuple[int, int], solid: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, "#101820")
    if not solid:
        for x in range(size[0]):
            for y in range(size[1]):
                image.putpixel((x, y), ((x * 7) % 256, (y * 11) % 256, ((x + y) * 13) % 256))
    image.save(path, format=fmt)


def _artifact_record(root: Path, relative_path: str) -> dict[str, object]:
    path = root / relative_path
    content = path.read_bytes()
    return {
        "path": relative_path,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_run_manifest(
    root: Path,
    *,
    status: str,
    artifacts: list[dict[str, object]],
    issues: list[dict[str, object]] | None = None,
) -> None:
    _write_json(
        root / "run.json",
        {
            "status": status,
            "artifacts": artifacts,
            "issues": issues or [],
        },
    )


def _numeric_case() -> EvaluationCase:
    return EvaluationCase.model_validate(
        {
            "case_id": "numeric-check",
            "kind": "open",
            "role": "research",
            "task_path": "examples/m51_sdss_image.json",
            "workflow": "fetch-image",
            "expected_exit_code": 0,
            "expected_status": "success",
            "required_files": ["metrics.json"],
            "artifacts": [{"path": "metrics.json", "kind": "json"}],
            "json_assertions": [],
            "numeric_assertions": [
                {
                    "file": "metrics.json",
                    "pointer": "/score",
                    "expected": 1.0,
                    "absolute_tolerance": 0.01,
                }
            ],
            "review_focus": ["verify numeric tolerance checks"],
            "prompt_file": "evaluation/prompts/workers/research.md",
        }
    )


def test_core_m42_check_passes_with_a_complete_audit_bundle(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_json(tmp_path / "result.json", {"target": {"canonical_name": "M 42"}})
    _write_text(tmp_path / "report.md", "# Observation Report\n")
    _write_text(tmp_path / "review_checklist.md", "- [ ] Review\n")
    _make_image(tmp_path / "figures/visibility_curve.png", fmt="PNG", size=(640, 480))
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[
            _artifact_record(tmp_path, "result.json"),
            _artifact_record(tmp_path, "report.md"),
            _artifact_record(tmp_path, "review_checklist.md"),
            _artifact_record(tmp_path, "figures/visibility_curve.png"),
        ],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.case_kind == "core"
    assert report.hard_gate_passed is True
    assert report.exit_code == 0
    assert report.issues == []


def test_core_m42_check_requires_a_complete_audit_bundle(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    (tmp_path / "run.json").write_text(
        json.dumps({"status": "success", "artifacts": []}), encoding="utf-8"
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "missing_artifact" for issue in report.issues)


def test_expected_validation_failure_is_not_a_hard_gate_failure(tmp_path) -> None:
    case = load_case(
        PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json"
    )
    (tmp_path / "stderr.json").write_text(
        json.dumps({"valid": False, "error": "validation_error"}), encoding="utf-8"
    )

    report = check_run(case, tmp_path, 2, "", (tmp_path / "stderr.json").read_text())

    assert report.case_kind == "failure"
    assert report.hard_gate_passed is True
    assert report.exit_code == 2


def test_hash_mismatch_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    (tmp_path / "run.json").write_text(
        json.dumps(
            {
                "status": "success",
                "artifacts": [{"path": "run.json", "bytes": 1, "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "artifact_hash_mismatch" for issue in report.issues)


def test_manifest_missing_expected_output_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_json(tmp_path / "result.json", {"target": {"canonical_name": "M 42"}})
    _write_text(tmp_path / "report.md", "# Observation Report\n")
    _write_text(tmp_path / "review_checklist.md", "- [ ] Review\n")
    _make_image(tmp_path / "figures/visibility_curve.png", fmt="PNG", size=(640, 480))
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[
            _artifact_record(tmp_path, "result.json"),
            _artifact_record(tmp_path, "report.md"),
            _artifact_record(tmp_path, "review_checklist.md"),
        ],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(
        issue.code == "manifest_missing_artifact"
        and issue.evidence_path == "figures/visibility_curve.png"
        for issue in report.issues
    )


def test_success_run_manifest_missing_artifacts_key_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_json(tmp_path / "result.json", {"target": {"canonical_name": "M 42"}})
    _write_text(tmp_path / "report.md", "# Observation Report\n")
    _write_text(tmp_path / "review_checklist.md", "- [ ] Review\n")
    _make_image(tmp_path / "figures/visibility_curve.png", fmt="PNG", size=(640, 480))
    _write_json(tmp_path / "run.json", {"status": "success", "issues": []})

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(
        issue.severity == "critical"
        and issue.code in {"manifest_missing_artifact", "invalid_artifact_manifest"}
        for issue in report.issues
    )


def test_missing_run_json_is_a_hard_gate_failure(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "missing_artifact" and issue.evidence_path == "run.json" for issue in report.issues)


def test_empty_required_file_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_text(tmp_path / "result.json", "")
    _write_text(tmp_path / "report.md", "# report\n")
    _write_text(tmp_path / "review_checklist.md", "- [ ] review\n")
    _make_image(tmp_path / "figures/visibility_curve.png", fmt="PNG", size=(640, 480))
    _write_run_manifest(tmp_path, status="success", artifacts=[])

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "empty_artifact" and issue.evidence_path == "result.json" for issue in report.issues)


def test_unexpected_exit_code_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_run_manifest(tmp_path, status="success", artifacts=[])

    report = check_run(case, tmp_path, 7, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "unexpected_exit_code" for issue in report.issues)


def test_json_assertion_mismatch_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_json(tmp_path / "result.json", {"target": {"canonical_name": "M 51"}})
    _write_text(tmp_path / "report.md", "# Observation Report\n")
    _write_text(tmp_path / "review_checklist.md", "- [ ] Review\n")
    _make_image(tmp_path / "figures/visibility_curve.png", fmt="PNG", size=(640, 480))
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[_artifact_record(tmp_path, "result.json"), _artifact_record(tmp_path, "report.md")],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "json_assertion_mismatch" for issue in report.issues)


def test_numeric_value_outside_tolerance_is_critical(tmp_path) -> None:
    case = _numeric_case()
    _write_json(tmp_path / "metrics.json", {"score": 1.5})

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "numeric_assertion_mismatch" for issue in report.issues)


def test_numeric_assertion_rejects_boolean_value(tmp_path) -> None:
    case = _numeric_case()
    _write_json(tmp_path / "metrics.json", {"score": True})

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "numeric_assertion_not_numeric" for issue in report.issues)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_numeric_assertion_rejects_non_finite_json_values(tmp_path: Path, value: str) -> None:
    case = _numeric_case()
    _write_text(tmp_path / "metrics.json", '{"score": ' + value + "}")

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "numeric_assertion_not_finite" for issue in report.issues)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_csv_assertion_rejects_non_finite_values(tmp_path: Path, value: str) -> None:
    payload = _numeric_case().model_dump()
    payload["required_files"] = ["metrics.csv"]
    payload["artifacts"] = [{"path": "metrics.csv", "kind": "csv"}]
    payload["numeric_assertions"] = []
    payload["csv_assertions"] = [
        {
            "file": "metrics.csv",
            "column": "score",
            "expected": 1.0,
            "absolute_tolerance": 0.01,
        }
    ]
    case = EvaluationCase.model_validate(payload)
    _write_text(tmp_path / "metrics.csv", f"score\n{value}\n")

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "csv_assertion_not_finite" for issue in report.issues)


def test_manifest_path_traversal_is_rejected(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_text(tmp_path / "report.md", "# Observation Report\n")
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[{"path": "../escape.txt", "bytes": 1, "sha256": "0" * 64}],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "unsafe_artifact_path" for issue in report.issues)


def test_manifest_directory_artifact_is_reported_as_critical_issue(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    (tmp_path / "data").mkdir()
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[{"path": "data", "bytes": 0, "sha256": "0" * 64}],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "artifact_is_directory" and issue.evidence_path == "data" for issue in report.issues)


def test_corrupt_sha256_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m42-beijing.json")
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[{"path": "report.md", "bytes": 1, "sha256": "not-a-sha256"}],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "artifact_hash_invalid" for issue in report.issues)


def test_corrupt_jpeg_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m51-sdss.json")
    _write_json(
        tmp_path / "image_metadata.json",
        {
            "request": {"target_name": "M51", "width": 512, "height": 512},
            "source": {"database": "SDSS SkyServer"},
            "source_path": str(tmp_path / "data/m51_sdss.jpg"),
            "display_path": str(tmp_path / "figures/m51_display.png"),
        },
    )
    _write_text(tmp_path / "data/m51_sdss.jpg", "not-a-real-jpeg")
    _make_image(tmp_path / "figures/m51_display.png", fmt="PNG", size=(512, 576))
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[
            _artifact_record(tmp_path, "image_metadata.json"),
            _artifact_record(tmp_path, "data/m51_sdss.jpg"),
            _artifact_record(tmp_path, "figures/m51_display.png"),
        ],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "invalid_image" and issue.evidence_path == "data/m51_sdss.jpg" for issue in report.issues)


def test_invalid_sdss_size_is_critical(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m51-sdss.json")
    _write_json(
        tmp_path / "image_metadata.json",
        {
            "request": {"target_name": "M51", "width": 2048, "height": 512},
            "source": {"database": "SDSS SkyServer"},
            "source_path": str(tmp_path / "data/m51_sdss.jpg"),
            "display_path": str(tmp_path / "figures/m51_display.png"),
        },
    )
    _make_image(tmp_path / "data/m51_sdss.jpg", fmt="JPEG", size=(2048, 512))
    _make_image(tmp_path / "figures/m51_display.png", fmt="PNG", size=(512, 576))
    _write_run_manifest(
        tmp_path,
        status="success",
        artifacts=[
            _artifact_record(tmp_path, "image_metadata.json"),
            _artifact_record(tmp_path, "data/m51_sdss.jpg"),
            _artifact_record(tmp_path, "figures/m51_display.png"),
        ],
    )

    report = check_run(case, tmp_path, 0, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "invalid_image_dimensions" for issue in report.issues)


@pytest.mark.parametrize(
    "stdout",
    ['{}', '{"downloaded": false}'],
)
def test_fetch_image_success_requires_downloaded_true_stdout(tmp_path, stdout: str) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/core/core-m51-sdss.json")
    _write_json(
        tmp_path / "image_metadata.json",
        {
            "request": {"target_name": "M51", "width": 512, "height": 512},
            "source": {"database": "SDSS SkyServer"},
            "source_path": str(tmp_path / "data/m51_sdss.jpg"),
            "display_path": str(tmp_path / "figures/m51_display.png"),
        },
    )
    _make_image(tmp_path / "data/m51_sdss.jpg", fmt="JPEG", size=(512, 512))
    _make_image(tmp_path / "figures/m51_display.png", fmt="PNG", size=(512, 576))

    report = check_run(case, tmp_path, 0, stdout, "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "missing_success_evidence" for issue in report.issues)


def test_valid_degraded_run_with_exit_code_5_passes(tmp_path) -> None:
    case = load_case(
        PROJECT_ROOT / "evaluation/cases/variants/variant-m42-no-window.json"
    ).model_copy(update={"expected_status": "degraded", "json_assertions": []})
    _write_json(tmp_path / "result.json", {"target": {"canonical_name": "M 42"}})
    _write_run_manifest(
        tmp_path,
        status="degraded",
        artifacts=[_artifact_record(tmp_path, "result.json")],
        issues=[{"stage": "planning", "code": "no_observation_window", "message": "No valid window"}],
    )

    report = check_run(case, tmp_path, 5, "{}", "")

    assert report.hard_gate_passed is True
    assert report.exit_code == 5


def test_degraded_run_requires_non_empty_issue_evidence(tmp_path) -> None:
    case = load_case(
        PROJECT_ROOT / "evaluation/cases/variants/variant-m42-no-window.json"
    ).model_copy(update={"expected_status": "degraded", "json_assertions": []})
    _write_json(tmp_path / "result.json", {"target": {"canonical_name": "M 42"}})
    _write_run_manifest(
        tmp_path,
        status="degraded",
        artifacts=[_artifact_record(tmp_path, "result.json")],
        issues=[],
    )

    report = check_run(case, tmp_path, 5, "{}", "")

    assert report.hard_gate_passed is False
    assert any(issue.code == "missing_failure_evidence" for issue in report.issues)


def test_expected_target_service_failure_with_exit_code_4_passes(tmp_path) -> None:
    case = load_case(PROJECT_ROOT / "evaluation/cases/failures/failure-target-service.json")
    _write_run_manifest(
        tmp_path,
        status="failed",
        artifacts=[],
        issues=[{"stage": "target_resolution", "code": "target_service_error", "message": "SIMBAD query failed"}],
    )
    stderr = json.dumps(
        {"resolved": False, "error": "target_service_error", "message": "SIMBAD query failed"}
    )

    report = check_run(case, tmp_path, 4, "", stderr)

    assert report.hard_gate_passed is True
    assert report.exit_code == 4
