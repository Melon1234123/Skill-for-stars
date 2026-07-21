"""Load and validate evaluation case manifests."""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from starskill.evaluation.models import EvaluationCase


class CaseManifestError(Exception):
    """Structured error raised for an unreadable or invalid case manifest."""

    def __init__(self, message: str, *, path: Path, details: object | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.details = details


def _project_root_from_cases_root(root: Path) -> Path:
    return root.resolve().parent.parent


def _project_root_from_case_path(path: Path) -> Path:
    resolved = path.resolve()
    parts = resolved.parts
    for index in range(len(parts) - 2):
        if parts[index] == "evaluation" and parts[index + 1] == "cases":
            return Path(*parts[:index]).resolve()
    return resolved.parent.resolve()


def _decode_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def read_json_pointer(document: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ValueError("pointer must start with '/'")

    current: Any = document
    for raw_token in pointer.split("/")[1:]:
        token = _decode_pointer_token(raw_token)
        if token == "*" or "[" in token or "]" in token:
            raise ValueError("pointer must not use array wildcard syntax")
        if not isinstance(current, dict):
            raise ValueError("pointer may only traverse nested object keys")
        if token not in current:
            raise KeyError(token)
        current = current[token]
    return current


def _resolve_case_paths(case: EvaluationCase, project_root: Path) -> EvaluationCase:
    data = case.model_dump()
    data["task_path"] = str((project_root / case.task_path).resolve())
    data["prompt_file"] = str((project_root / case.prompt_file).resolve())
    return EvaluationCase.model_validate(data)


def load_case(path: Path) -> EvaluationCase:
    payload = _load_case_payload(path)
    case = _validate_case_payload(payload, path)
    project_root = _project_root_from_case_path(path)
    return _resolve_case_paths(case, project_root)


def load_cases(root: Path) -> list[EvaluationCase]:
    if not root.exists() or not root.is_dir():
        raise CaseManifestError(
            f"canonical cases root is missing or not a directory: {root}", path=root
        )
    project_root = _project_root_from_cases_root(root)
    paths = sorted(root.resolve().rglob("*.json"))
    if not paths:
        raise CaseManifestError(
            f"canonical cases root contains no JSON manifests: {root}", path=root
        )
    cases: list[EvaluationCase] = []
    for path in paths:
        payload = _load_case_payload(path)
        case = _validate_case_payload(payload, path)
        cases.append(_resolve_case_paths(case, project_root))
    return cases


def _load_case_payload(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise CaseManifestError(
            f"failed to parse case manifest: {path}", path=path, details=str(exc)
        ) from exc


def _validate_case_payload(payload: object, path: Path) -> EvaluationCase:
    try:
        return EvaluationCase.model_validate(payload)
    except ValidationError as exc:
        raise CaseManifestError(
            f"case manifest did not match the required schema: {path}",
            path=path,
            details=exc.errors(include_url=False, include_context=False),
        ) from exc
