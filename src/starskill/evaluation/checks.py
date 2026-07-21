"""Deterministic artifact and process checks for evaluation runs."""

from __future__ import annotations

import hashlib
import csv
import math
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from starskill.evaluation.cases import read_json_pointer
from starskill.evaluation.models import CheckIssue, EvaluationCase, MachineCheckReport


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POINT_MAX = {
    "closed_loop": 40.0,
    "scientific_correctness": 25.0,
    "reproducibility": 20.0,
    "machine_safety": 4.0,
}


def check_run(
    case: EvaluationCase,
    run_dir: Path,
    return_code: int,
    stdout: str,
    stderr: str,
) -> MachineCheckReport:
    issues: list[CheckIssue] = []
    checked_files: list[str] = []
    points = {
        "closed_loop": 0.0,
        "scientific_correctness": 0.0,
        "reproducibility": 0.0,
        "machine_safety": 0.0,
    }
    run_dir = run_dir.resolve()
    _check_exit_code(case, return_code, issues)
    _check_required_artifacts(case, run_dir, checked_files, issues, points)
    _check_json_assertions(case, run_dir, checked_files, issues, points)
    _check_numeric_assertions(case, run_dir, checked_files, issues, points)
    _check_csv_assertions(case, run_dir, checked_files, issues, points)
    _check_manifest_hashes(case, run_dir, checked_files, issues, points)
    _check_fetch_image_metadata_paths(case, run_dir, checked_files, issues)
    _check_failure_artifacts(case, run_dir, stdout, stderr, issues, points)
    _check_image_properties(case, run_dir, checked_files, issues, points)
    hard_gate_passed = not any(issue.severity == "critical" for issue in issues)
    return MachineCheckReport(
        case_id=case.case_id,
        case_kind=case.kind,
        hard_gate_passed=hard_gate_passed,
        exit_code=return_code,
        dimension_points=points,
        issues=issues,
        checked_files=checked_files,
    )


def _check_exit_code(
    case: EvaluationCase,
    return_code: int,
    issues: list[CheckIssue],
) -> None:
    allowed_codes = {case.expected_exit_code}
    if case.workflow == "run" and case.expected_status == "degraded":
        allowed_codes.add(5)
    if return_code in allowed_codes:
        return
    _add_issue(
        issues,
        code="unexpected_exit_code",
        severity="critical",
        message=(
            f"expected exit code {sorted(allowed_codes)} for {case.case_id}, "
            f"observed {return_code}"
        ),
    )


def _check_required_artifacts(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    expectations = {
        artifact.path: artifact for artifact in case.artifacts
    }
    all_paths = list(dict.fromkeys([*case.required_files, *expectations.keys()]))
    if not all_paths:
        return

    passed = 0
    for relative_path in all_paths:
        resolved = _safe_case_path(run_dir, relative_path, issues)
        if resolved is None:
            continue
        if not resolved.exists():
            _add_issue(
                issues,
                code="missing_artifact",
                severity="critical",
                message=f"required artifact is missing: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        _remember_checked_file(checked_files, relative_path)
        if resolved.is_dir():
            _add_issue(
                issues,
                code="artifact_is_directory",
                severity="critical",
                message=f"artifact path must resolve to a file: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        expectation = expectations.get(relative_path)
        requires_content = expectation.non_empty if expectation else True
        if requires_content and resolved.stat().st_size == 0:
            _add_issue(
                issues,
                code="empty_artifact",
                severity="critical",
                message=f"artifact must not be empty: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        passed += 1

    points["closed_loop"] += _POINT_MAX["closed_loop"] * passed / len(all_paths)


def _check_json_assertions(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    total = len(case.json_assertions) + len(case.numeric_assertions) + len(case.csv_assertions)
    if not case.json_assertions or total == 0:
        return

    passed = 0
    cache: dict[str, dict[str, Any] | None] = {}
    for assertion in case.json_assertions:
        document = _load_json_file(assertion.file, run_dir, checked_files, issues, cache)
        if document is None:
            continue
        try:
            value = read_json_pointer(document, assertion.pointer)
            exists = True
        except KeyError:
            value = None
            exists = False
        except ValueError as exc:
            _add_issue(
                issues,
                code="invalid_json_pointer",
                severity="critical",
                message=str(exc),
                evidence_path=assertion.file,
            )
            continue

        if assertion.exists and not exists:
            _add_issue(
                issues,
                code="json_pointer_missing",
                severity="critical",
                message=f"JSON pointer {assertion.pointer} missing in {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        if not assertion.exists and exists:
            _add_issue(
                issues,
                code="json_pointer_unexpected",
                severity="critical",
                message=f"JSON pointer {assertion.pointer} unexpectedly present in {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        if assertion.equals is not None and value != assertion.equals:
            _add_issue(
                issues,
                code="json_assertion_mismatch",
                severity="critical",
                message=(
                    f"expected {assertion.file}{assertion.pointer} == {assertion.equals!r}, "
                    f"observed {value!r}"
                ),
                evidence_path=assertion.file,
            )
            continue
        passed += 1

    points["scientific_correctness"] += _POINT_MAX["scientific_correctness"] * passed / total


def _check_numeric_assertions(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    total = len(case.json_assertions) + len(case.numeric_assertions) + len(case.csv_assertions)
    if not case.numeric_assertions or total == 0:
        return

    passed = 0
    cache: dict[str, dict[str, Any] | None] = {}
    for assertion in case.numeric_assertions:
        document = _load_json_file(assertion.file, run_dir, checked_files, issues, cache)
        if document is None:
            continue
        try:
            value = read_json_pointer(document, assertion.pointer)
        except KeyError:
            _add_issue(
                issues,
                code="json_pointer_missing",
                severity="critical",
                message=f"JSON pointer {assertion.pointer} missing in {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        except ValueError as exc:
            _add_issue(
                issues,
                code="invalid_json_pointer",
                severity="critical",
                message=str(exc),
                evidence_path=assertion.file,
            )
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            _add_issue(
                issues,
                code="numeric_assertion_not_numeric",
                severity="critical",
                message=f"value at {assertion.file}{assertion.pointer} is not numeric",
                evidence_path=assertion.file,
            )
            continue
        observed = float(value)
        if not math.isfinite(observed):
            _add_issue(
                issues,
                code="numeric_assertion_not_finite",
                severity="critical",
                message=f"value at {assertion.file}{assertion.pointer} must be finite",
                evidence_path=assertion.file,
            )
            continue
        if abs(observed - assertion.expected) > assertion.absolute_tolerance:
            _add_issue(
                issues,
                code="numeric_assertion_mismatch",
                severity="critical",
                message=(
                    f"expected {assertion.file}{assertion.pointer} within "
                    f"{assertion.absolute_tolerance} of {assertion.expected}, observed {value}"
                ),
                evidence_path=assertion.file,
            )
            continue
        passed += 1

    points["scientific_correctness"] += _POINT_MAX["scientific_correctness"] * passed / total


def _check_csv_assertions(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    total = len(case.json_assertions) + len(case.numeric_assertions) + len(case.csv_assertions)
    if not case.csv_assertions or total == 0:
        return

    passed = 0
    for assertion in case.csv_assertions:
        resolved = _safe_case_path(run_dir, assertion.file, issues)
        if resolved is None or not resolved.exists():
            _add_issue(
                issues,
                code="missing_artifact",
                severity="critical",
                message=f"required CSV artifact is missing: {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        _remember_checked_file(checked_files, assertion.file)
        try:
            with resolved.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            _add_issue(
                issues,
                code="invalid_csv",
                severity="critical",
                message=f"failed to parse CSV from {assertion.file}: {exc}",
                evidence_path=assertion.file,
            )
            continue
        if not rows or assertion.column not in (rows[0] if rows else {}):
            _add_issue(
                issues,
                code="invalid_csv_structure",
                severity="critical",
                message=f"CSV column {assertion.column!r} is missing in {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        if assertion.row >= len(rows):
            _add_issue(
                issues,
                code="csv_row_missing",
                severity="critical",
                message=f"CSV row {assertion.row} is missing in {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        try:
            value = float(rows[assertion.row][assertion.column])
        except (TypeError, ValueError):
            _add_issue(
                issues,
                code="csv_assertion_not_numeric",
                severity="critical",
                message=f"CSV value {assertion.column!r} is not numeric in {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        if not math.isfinite(value):
            _add_issue(
                issues,
                code="csv_assertion_not_finite",
                severity="critical",
                message=f"CSV value {assertion.column!r} must be finite in {assertion.file}",
                evidence_path=assertion.file,
            )
            continue
        if abs(value - assertion.expected) > assertion.absolute_tolerance:
            _add_issue(
                issues,
                code="csv_assertion_mismatch",
                severity="critical",
                message=(
                    f"expected {assertion.file}[{assertion.row}].{assertion.column} within "
                    f"{assertion.absolute_tolerance} of {assertion.expected}, observed {value}"
                ),
                evidence_path=assertion.file,
            )
            continue
        passed += 1
    points["scientific_correctness"] += _POINT_MAX["scientific_correctness"] * passed / total


def _check_manifest_hashes(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    expected_paths = _expected_output_paths(case)
    coverage_required = case.expected_status in {"success", "degraded"}
    run_path = _safe_case_path(run_dir, "run.json", issues)
    if run_path is None or not run_path.exists():
        if coverage_required:
            covered_paths = _metadata_coverage_paths(
                case, run_dir, checked_files, issues, expected_paths
            )
            _record_missing_coverage(
                expected_paths, covered_paths, issues, points
            )
        return
    _remember_checked_file(checked_files, "run.json")
    run_manifest = _load_optional_json(run_path)
    if not run_manifest:
        return
    artifacts = run_manifest.get("artifacts")
    if artifacts is None:
        if coverage_required:
            _add_issue(
                issues,
                code="invalid_artifact_manifest",
                severity="critical",
                message="run.json must include an artifacts list for success or degraded cases",
                evidence_path="run.json",
            )
        else:
            return
        return
    if not isinstance(artifacts, list):
        _add_issue(
            issues,
            code="invalid_artifact_manifest",
            severity="critical",
            message="run.json artifacts must be a list",
            evidence_path="run.json",
        )
        return
    if not artifacts:
        if coverage_required and expected_paths:
            for relative_path in sorted(expected_paths):
                _add_issue(
                    issues,
                    code="manifest_missing_artifact",
                    severity="critical",
                    message=f"run.json artifacts are missing expected output: {relative_path}",
                    evidence_path=relative_path,
                )
        return

    manifest_records: dict[str, dict[str, Any]] = {}
    for record in artifacts:
        if isinstance(record, dict) and isinstance(record.get("path"), str):
            manifest_records.setdefault(record["path"], record)

    missing_paths: set[str] = set()
    if coverage_required and expected_paths:
        missing_paths = expected_paths.difference(manifest_records)
        for relative_path in sorted(missing_paths):
            _add_issue(
                issues,
                code="manifest_missing_artifact",
                severity="critical",
                message=f"run.json artifacts are missing expected output: {relative_path}",
                evidence_path=relative_path,
            )

    passed = 0
    passed_expected_paths: set[str] = set()
    for record in artifacts:
        if not isinstance(record, dict):
            _add_issue(
                issues,
                code="invalid_artifact_manifest",
                severity="critical",
                message="artifact manifest entries must be objects",
                evidence_path="run.json",
            )
            continue
        relative_path = record.get("path")
        expected_size = record.get("bytes")
        expected_hash = record.get("sha256")
        if not isinstance(relative_path, str):
            _add_issue(
                issues,
                code="invalid_artifact_manifest",
                severity="critical",
                message="artifact path must be a string",
                evidence_path="run.json",
            )
            continue
        if not isinstance(expected_size, int) or expected_size < 0:
            _add_issue(
                issues,
                code="artifact_size_invalid",
                severity="critical",
                message=f"artifact size must be a non-negative integer: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
            _add_issue(
                issues,
                code="artifact_hash_invalid",
                severity="critical",
                message=f"artifact sha256 must be 64 lowercase hex characters: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        resolved = _safe_manifest_artifact_path(run_dir, relative_path, issues)
        if resolved is None:
            continue
        if not resolved.exists():
            _add_issue(
                issues,
                code="missing_artifact",
                severity="critical",
                message=f"manifest artifact is missing: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        _remember_checked_file(checked_files, relative_path)
        if resolved.is_dir():
            _add_issue(
                issues,
                code="artifact_is_directory",
                severity="critical",
                message=f"artifact path must resolve to a file: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        if not resolved.is_file():
            _add_issue(
                issues,
                code="artifact_not_file",
                severity="critical",
                message=f"artifact path must resolve to a regular file: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        try:
            content = resolved.read_bytes()
        except OSError as exc:
            _add_issue(
                issues,
                code="artifact_read_error",
                severity="critical",
                message=f"failed to read artifact {relative_path}: {exc}",
                evidence_path=relative_path,
            )
            continue
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            _add_issue(
                issues,
                code="artifact_hash_mismatch",
                severity="critical",
                message=f"artifact sha256 mismatch for {relative_path}",
                evidence_path=relative_path,
            )
            continue
        if len(content) != expected_size:
            _add_issue(
                issues,
                code="artifact_size_mismatch",
                severity="critical",
                message=(
                    f"expected {relative_path} to be {expected_size} bytes, "
                    f"observed {len(content)}"
                ),
                evidence_path=relative_path,
            )
            continue
        passed += 1
        if relative_path in expected_paths:
            passed_expected_paths.add(relative_path)

    if coverage_required and expected_paths:
        if missing_paths:
            return
        denominator = len(expected_paths)
        passed = len(passed_expected_paths)
    else:
        denominator = len(artifacts)

    if denominator > 0:
        points["reproducibility"] += _POINT_MAX["reproducibility"] * passed / denominator


def _check_failure_artifacts(
    case: EvaluationCase,
    run_dir: Path,
    stdout: str,
    stderr: str,
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    stdout_payload = _parse_json_text(stdout)
    stderr_payload = _parse_json_text(stderr)
    run_manifest = _parse_json_text(_read_text_if_exists(run_dir / "run.json"))
    run_status = run_manifest.get("status") if isinstance(run_manifest, dict) else None
    run_issue_codes = set()
    run_issue_records = run_manifest.get("issues") if isinstance(run_manifest, dict) else None
    if isinstance(run_issue_records, list):
        for issue in run_issue_records:
            if isinstance(issue, dict) and isinstance(issue.get("code"), str):
                run_issue_codes.add(issue["code"])

    if case.expected_status == "success":
        if _has_success_evidence(case, stdout_payload, run_status):
            points["machine_safety"] += 2.0
            return
        _add_issue(
            issues,
            code="missing_success_evidence",
            severity="critical",
            message=f"expected success evidence for workflow '{case.workflow}' was not observed",
            evidence_path="run.json" if case.workflow == "run" else None,
        )
        return

    if case.expected_status == "degraded":
        if run_status != "degraded" or not _has_degraded_issue_evidence(run_issue_records):
            _add_issue(
                issues,
                code="missing_failure_evidence",
                severity="critical",
                message="expected degraded execution evidence was not observed",
                evidence_path="run.json",
            )
            return
        points["machine_safety"] += 2.0
        return

    expected_error = _expected_error_code(case)
    payloads = [payload for payload in (stderr_payload, stdout_payload) if payload]
    observed_errors = {
        payload["error"]
        for payload in payloads
        if isinstance(payload, dict) and isinstance(payload.get("error"), str)
    }
    observed_invalid = any(
        isinstance(payload, dict) and payload.get("valid") is False for payload in payloads
    )
    if run_status == "failed":
        observed_errors.update(run_issue_codes)

    if expected_error == "validation_error":
        if observed_invalid or expected_error in observed_errors:
            points["machine_safety"] += 2.0
            return
    elif expected_error and expected_error in observed_errors:
        points["machine_safety"] += 2.0
        return
    elif expected_error is None and run_status == "failed":
        points["machine_safety"] += 2.0
        return

    _add_issue(
        issues,
        code="missing_failure_evidence",
        severity="critical",
        message="expected failure path evidence was not observed",
    )


def _check_image_properties(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    image_paths = [artifact.path for artifact in case.artifacts if artifact.kind == "image"]
    if not image_paths:
        points["machine_safety"] += 2.0
        return

    passed = 0
    metadata = _load_optional_json(run_dir / "image_metadata.json")
    request = metadata.get("request") if isinstance(metadata.get("request"), dict) else {}
    for relative_path in image_paths:
        resolved = _safe_case_path(run_dir, relative_path, issues)
        if resolved is None or not resolved.exists():
            continue
        _remember_checked_file(checked_files, relative_path)
        try:
            with Image.open(resolved) as image:
                image.verify()
            with Image.open(resolved) as image:
                image.load()
                fmt = image.format
                width, height = image.size
                extrema = image.convert("RGB").getextrema()
        except (UnidentifiedImageError, OSError, ValueError):
            _add_issue(
                issues,
                code="invalid_image",
                severity="critical",
                message=f"image artifact is unreadable or corrupt: {relative_path}",
                evidence_path=relative_path,
            )
            continue

        if all(low == high for low, high in extrema):
            _add_issue(
                issues,
                code="uniform_image",
                severity="critical",
                message=f"image artifact must contain non-uniform pixel data: {relative_path}",
                evidence_path=relative_path,
            )
            continue

        if relative_path.endswith(".jpg"):
            if fmt != "JPEG":
                _add_issue(
                    issues,
                    code="invalid_image",
                    severity="critical",
                    message=f"expected JPEG image: {relative_path}",
                    evidence_path=relative_path,
                )
                continue
            if not _valid_sdss_request_size(request):
                _add_issue(
                    issues,
                    code="invalid_image_dimensions",
                    severity="critical",
                    message="SDSS request dimensions must stay within 64..1024 pixels",
                    evidence_path="image_metadata.json",
                )
                continue
            expected_size = (int(request["width"]), int(request["height"])) if request else None
            if expected_size and (width, height) != expected_size:
                _add_issue(
                    issues,
                    code="invalid_image_dimensions",
                    severity="critical",
                    message=f"source image dimensions do not match metadata request for {relative_path}",
                    evidence_path=relative_path,
                )
                continue
        elif relative_path.endswith(".png"):
            if fmt != "PNG":
                _add_issue(
                    issues,
                    code="invalid_image",
                    severity="critical",
                    message=f"expected PNG image: {relative_path}",
                    evidence_path=relative_path,
                )
                continue
            if relative_path.endswith("m51_display.png") and _valid_sdss_request_size(request):
                side = min(int(request["width"]), int(request["height"]))
                if (width, height) != (side, side + 64):
                    _add_issue(
                        issues,
                        code="invalid_image_dimensions",
                        severity="critical",
                        message=f"display image dimensions do not match derived SDSS display size for {relative_path}",
                        evidence_path=relative_path,
                    )
                    continue
        if width <= 1 or height <= 1:
            _add_issue(
                issues,
                code="invalid_image_dimensions",
                severity="critical",
                message=f"image dimensions must be larger than 1x1: {relative_path}",
                evidence_path=relative_path,
            )
            continue
        passed += 1

    points["machine_safety"] += 2.0 * passed / len(image_paths)


def _load_json_file(
    relative_path: str,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    if relative_path in cache:
        return cache[relative_path]
    resolved = _safe_case_path(run_dir, relative_path, issues)
    if resolved is None:
        cache[relative_path] = None
        return None
    if not resolved.exists():
        _add_issue(
            issues,
            code="missing_artifact",
            severity="critical",
            message=f"required JSON artifact is missing: {relative_path}",
            evidence_path=relative_path,
        )
        cache[relative_path] = None
        return None
    _remember_checked_file(checked_files, relative_path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        _add_issue(
            issues,
            code="invalid_json",
            severity="critical",
            message=f"failed to parse JSON from {relative_path}: {exc}",
            evidence_path=relative_path,
        )
        cache[relative_path] = None
        return None
    if not isinstance(payload, dict):
        _add_issue(
            issues,
            code="invalid_json",
            severity="critical",
            message=f"JSON artifact must be an object: {relative_path}",
            evidence_path=relative_path,
        )
        cache[relative_path] = None
        return None
    cache[relative_path] = payload
    return payload


def _safe_case_path(run_dir: Path, relative_path: str, issues: list[CheckIssue]) -> Path | None:
    if Path(relative_path).is_absolute():
        _add_issue(
            issues,
            code="unsafe_artifact_path",
            severity="critical",
            message=f"absolute artifact paths are not allowed: {relative_path}",
            evidence_path=relative_path,
        )
        return None
    resolved = (run_dir / relative_path).resolve()
    try:
        resolved.relative_to(run_dir)
    except ValueError:
        _add_issue(
            issues,
            code="unsafe_artifact_path",
            severity="critical",
            message=f"artifact path escapes run_dir: {relative_path}",
            evidence_path=relative_path,
        )
        return None
    return resolved


def _safe_manifest_artifact_path(
    run_dir: Path, relative_path: str, issues: list[CheckIssue]
) -> Path | None:
    return _safe_case_path(run_dir, relative_path, issues)


def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_optional_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _has_success_evidence(
    case: EvaluationCase,
    stdout_payload: dict[str, Any],
    run_status: Any,
) -> bool:
    if case.workflow == "run":
        return run_status == "success"
    if case.workflow == "relationship":
        return stdout_payload.get("calculated") is True
    if case.workflow == "fetch-image":
        return stdout_payload.get("downloaded") is True
    if case.workflow == "validate":
        return stdout_payload.get("valid") is True
    if case.workflow == "resolve":
        return stdout_payload.get("resolved") is True
    if case.workflow == "plan":
        return stdout_payload.get("planned") is True
    if case.workflow == "ephemeris":
        return stdout_payload.get("calculated") is True
    return False


def _has_degraded_issue_evidence(run_issue_records: Any) -> bool:
    if not isinstance(run_issue_records, list) or not run_issue_records:
        return False
    for issue in run_issue_records:
        if not isinstance(issue, dict):
            return False
        code = issue.get("code")
        message = issue.get("message")
        if not isinstance(code, str) or not code.strip():
            return False
        if not isinstance(message, str) or not message.strip():
            return False
    return True


def _parse_json_text(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    try:
        payload = json.loads(text)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _expected_output_paths(case: EvaluationCase) -> set[str]:
    return {
        path
        for path in [*case.required_files, *(artifact.path for artifact in case.artifacts)]
        if path != "run.json"
    }


def _metadata_coverage_paths(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
    expected_paths: set[str],
) -> set[str]:
    if not expected_paths:
        return set()

    if case.workflow == "fetch-image":
        metadata = _load_json_file(
            "image_metadata.json", run_dir, checked_files, issues, {}
        )
        if metadata is None:
            return set()
        covered = {"image_metadata.json"} if "image_metadata.json" in expected_paths else set()
        for field in ("source_path", "display_path"):
            value = metadata.get(field)
            relative_path = _metadata_path_to_relative(value, run_dir)
            if relative_path is None or relative_path not in expected_paths:
                _add_issue(
                    issues,
                    code="invalid_metadata_artifact_path",
                    severity="critical",
                    message=f"{field} must name an expected run-relative image artifact",
                    evidence_path="image_metadata.json",
                )
                continue
            covered.add(relative_path)
        return covered

    metadata_file = _workflow_metadata_file(case)
    if metadata_file is None:
        return set()
    metadata = _load_json_file(metadata_file, run_dir, checked_files, issues, {})
    if metadata is None:
        return set()
    return {
        path
        for path in expected_paths
        if _path_exists_under_run_dir(run_dir, path, issues)
    }


def _check_fetch_image_metadata_paths(
    case: EvaluationCase,
    run_dir: Path,
    checked_files: list[str],
    issues: list[CheckIssue],
) -> None:
    if case.workflow != "fetch-image":
        return
    metadata = _load_json_file("image_metadata.json", run_dir, checked_files, issues, {})
    if metadata is None:
        return
    expected_paths = _expected_output_paths(case)
    for field in ("source_path", "display_path"):
        relative_path = _metadata_path_to_relative(metadata.get(field), run_dir)
        if relative_path is None or relative_path not in expected_paths:
            _add_issue(
                issues,
                code="invalid_metadata_artifact_path",
                severity="critical",
                message=f"{field} must name an expected run-relative image artifact",
                evidence_path="image_metadata.json",
            )


def _workflow_metadata_file(case: EvaluationCase) -> str | None:
    if case.workflow == "relationship":
        return "relationship.json"
    if case.workflow == "ephemeris":
        return "intermediate/ephemeris.json"
    if case.workflow == "plan":
        return "result.json"
    if case.workflow == "resolve":
        return "target_resolved.json"
    return None


def _metadata_path_to_relative(value: Any, run_dir: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        parts = candidate.parts
        legacy_prefix = ("runs", "day6_m51")
        if parts[:2] == legacy_prefix:
            candidate = Path(*parts[2:])
        if candidate.parts and candidate.parts[0] not in {"data", "figures"}:
            return None
        resolved = (run_dir / candidate).resolve()
    try:
        return resolved.relative_to(run_dir).as_posix()
    except ValueError:
        return None


def _path_exists_under_run_dir(
    run_dir: Path, relative_path: str, issues: list[CheckIssue]
) -> bool:
    resolved = _safe_case_path(run_dir, relative_path, issues)
    return resolved is not None and resolved.exists()


def _record_missing_coverage(
    expected_paths: set[str],
    covered_paths: set[str],
    issues: list[CheckIssue],
    points: dict[str, float],
) -> None:
    missing_paths = expected_paths.difference(covered_paths)
    if not missing_paths:
        if expected_paths:
            points["reproducibility"] += _POINT_MAX["reproducibility"]
        return
    for relative_path in sorted(missing_paths):
        _add_issue(
            issues,
            code="manifest_missing_artifact",
            severity="critical",
            message=f"expected output is not covered by reproducibility evidence: {relative_path}",
            evidence_path=relative_path,
        )


def _remember_checked_file(checked_files: list[str], relative_path: str) -> None:
    if relative_path not in checked_files:
        checked_files.append(relative_path)


def _valid_sdss_request_size(request: dict[str, Any]) -> bool:
    width = request.get("width")
    height = request.get("height")
    return (
        isinstance(width, int)
        and isinstance(height, int)
        and 64 <= width <= 1024
        and 64 <= height <= 1024
    )


def _expected_error_code(case: EvaluationCase) -> str | None:
    if case.workflow == "validate" or case.expected_exit_code == 2:
        return "validation_error"
    if case.expected_exit_code == 4:
        return "target_service_error"
    if case.expected_exit_code == 7:
        return "public_data_service_error"
    if case.expected_exit_code == 8:
        return "public_data_size_limit"
    if case.expected_exit_code == 9:
        return "public_data_invalid_image"
    return None


def _add_issue(
    issues: list[CheckIssue],
    *,
    code: str,
    message: str,
    severity: str,
    evidence_path: str | None = None,
) -> None:
    issues.append(
        CheckIssue(
            code=code,
            message=message,
            evidence_path=evidence_path,
            severity=severity,
        )
    )
