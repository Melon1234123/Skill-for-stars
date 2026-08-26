"""Uniform CLI response envelope shared by every StarSkill command."""

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, TextIO


ENVELOPE_VERSION = "1.0"


def artifact_record(path: Path) -> dict[str, Any]:
    """Describe one written artifact with its size and content hash."""
    content = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def success_payload(
    workflow: str,
    *,
    status: str = "success",
    summary: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    human_review: list[str] | None = None,
    legacy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the uniform success or degraded envelope with legacy keys preserved."""
    if status not in ("success", "degraded"):
        raise ValueError("success envelope status must be success or degraded")
    payload: dict[str, Any] = {
        "envelope_version": ENVELOPE_VERSION,
        "status": status,
        "workflow": workflow,
        "summary": summary or {},
        "artifacts": artifacts or [],
        "sources": sources or [],
        "human_review": human_review or [],
    }
    payload.update(legacy or {})
    return payload


def failure_payload(
    workflow: str,
    *,
    error: str,
    message: str | None = None,
    details: list[dict[str, Any]] | None = None,
    legacy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the uniform failure envelope with legacy keys preserved."""
    payload: dict[str, Any] = {
        "envelope_version": ENVELOPE_VERSION,
        "status": "failed",
        "workflow": workflow,
        "error": error,
    }
    if message is not None:
        payload["message"] = message
    if details is not None:
        payload["details"] = details
    payload.update(legacy or {})
    return payload


def emit(payload: dict[str, Any], *, stream: TextIO | None = None) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, indent=2),
        file=stream if stream is not None else sys.stdout,
    )
