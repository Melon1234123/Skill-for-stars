"""Resolve user-facing target names into canonical astronomy identifiers."""

import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from astroquery.simbad import Simbad

from starskill.schemas import ResolvedTarget, TargetSource


TARGET_ALIASES = {
    "orion nebula": "M 42",
    "猎户大星云": "M 42",
    "猎户座大星云": "M 42",
}

UNSAFE_TARGET_CHARACTERS = re.compile(r"[\x00-\x1f\x7f\"';\\<>|`]")


class TargetBackend(Protocol):
    service_url: str

    def query_object(self, query_name: str) -> Mapping[str, Any] | None: ...


class TargetResolutionError(RuntimeError):
    code = "target_resolution_error"


class TargetNotFoundError(TargetResolutionError):
    code = "target_not_found"


class TargetServiceError(TargetResolutionError):
    code = "target_service_error"


class InvalidTargetNameError(ValueError):
    code = "invalid_target_name"


class SimbadBackend:
    service_url = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

    def __init__(self, client: Any | None = None, timeout_seconds: int = 30) -> None:
        self.client = client or Simbad()
        self.timeout_seconds = timeout_seconds
        self._client_configured = False

    def query_object(self, query_name: str) -> Mapping[str, Any] | None:
        if not self._client_configured:
            self.client.timeout = self.timeout_seconds
            self.client.ROW_LIMIT = 1
            self.client.add_votable_fields("otype", "ids")
            self._client_configured = True
        table = self.client.query_object(query_name)
        if table is None or len(table) == 0:
            return None

        row = table[0]
        aliases = [
            collapse_catalog_identifier(alias)
            for alias in str(row["ids"]).split("|")
            if alias.strip()
        ]
        return {
            "canonical_name": collapse_catalog_identifier(row["main_id"]),
            "ra_deg": float(row["ra"]),
            "dec_deg": float(row["dec"]),
            "object_type": str(row["otype"]).strip(),
            "aliases": aliases,
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def target_cache_path(cache_dir: Path, query_name: str) -> Path:
    cache_key = sha256(query_name.casefold().encode("utf-8")).hexdigest()
    return cache_dir / f"{cache_key}.json"


def collapse_catalog_identifier(value: Any) -> str:
    return " ".join(str(value).split())


def normalize_target_name(raw_name: str) -> str:
    """Return a stable name for cache keys and remote catalog queries."""
    if UNSAFE_TARGET_CHARACTERS.search(raw_name):
        raise InvalidTargetNameError("target name contains unsafe characters")

    collapsed = " ".join(raw_name.split())
    if not collapsed:
        raise InvalidTargetNameError("target name must not be blank")
    if len(collapsed) > 128:
        raise InvalidTargetNameError("target name must not exceed 128 characters")

    alias = TARGET_ALIASES.get(collapsed.casefold())
    if alias:
        return alias

    messier_match = re.fullmatch(r"m\s*(\d{1,3})", collapsed, re.IGNORECASE)
    if messier_match:
        return f"M {int(messier_match.group(1))}"

    return collapsed


def resolve_target(
    input_name: str,
    *,
    backend: TargetBackend,
    cache_dir: Path | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> ResolvedTarget:
    """Resolve one validated target through an astronomy catalog backend."""
    query_name = normalize_target_name(input_name)
    cache_path = target_cache_path(cache_dir, query_name) if cache_dir else None
    if cache_path and cache_path.exists():
        try:
            cached = ResolvedTarget.model_validate_json(
                cache_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            pass
        else:
            return cached.model_copy(
                update={
                    "input_name": input_name.strip(),
                    "source": cached.source.model_copy(update={"from_cache": True}),
                }
            )

    try:
        record = backend.query_object(query_name)
    except TargetResolutionError:
        raise
    except Exception as exc:
        raise TargetServiceError(f"SIMBAD query failed for: {query_name}") from exc
    if record is None:
        raise TargetNotFoundError(f"target not found in SIMBAD: {query_name}")

    resolved = ResolvedTarget(
        input_name=input_name.strip(),
        query_name=query_name,
        canonical_name=record["canonical_name"],
        ra_deg=record["ra_deg"],
        dec_deg=record["dec_deg"],
        object_type=record["object_type"],
        aliases=list(record["aliases"]),
        source=TargetSource(
            database="SIMBAD",
            service_url=backend.service_url,
            accessed_at=clock(),
            from_cache=False,
        ),
    )
    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(resolved.model_dump_json(indent=2), encoding="utf-8")
        except OSError as exc:
            raise TargetServiceError("target cache update failed") from exc
    return resolved
