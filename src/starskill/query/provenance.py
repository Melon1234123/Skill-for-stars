"""Artifact writing and integrity records for VO query executions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from astropy.table import Table

from starskill.query.errors import VOQueryArtifactError
from starskill.query.models import BaseQueryRequest, QueryProvenance
from starskill.schemas import ArtifactRecord


def query_sha256(adql: str) -> str:
    return hashlib.sha256(adql.encode("utf-8")).hexdigest()


def artifact_record(output_dir: Path, path: Path) -> ArtifactRecord:
    content = path.read_bytes()
    return ArtifactRecord(
        path=path.relative_to(output_dir).as_posix(),
        bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def write_query_artifacts(
    *,
    output_dir: Path,
    request: BaseQueryRequest,
    adql: str,
    table: Table,
    provenance: QueryProvenance,
) -> list[ArtifactRecord]:
    """Write the four portable query artifacts and return their content hashes."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        request_path = output_dir / "request.json"
        adql_path = output_dir / "query.adql"
        result_path = output_dir / "result.ecsv"
        provenance_path = output_dir / "provenance.json"

        request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
        adql_path.write_text(adql + "\n", encoding="utf-8")
        table.write(result_path, format="ascii.ecsv", overwrite=True)
        provenance_path.write_text(
            provenance.model_dump_json(indent=2), encoding="utf-8"
        )
        return [
            artifact_record(output_dir, path)
            for path in (request_path, adql_path, result_path, provenance_path)
        ]
    except (OSError, ValueError, TypeError) as exc:
        raise VOQueryArtifactError("could not write VO query artifacts") from exc


def failure_table(provenance: QueryProvenance) -> Table:
    """Represent a failed query as explicitly empty ECSV evidence, never data."""
    table = Table()
    table.meta.update(
        {
            "starskill_status": "failed",
            "starskill_service": provenance.service,
            "starskill_query_sha256": provenance.query_sha256,
            "starskill_failure_code": provenance.failure.code if provenance.failure else "unknown",
        }
    )
    return table


def annotate_result_table(table: Table, provenance: QueryProvenance) -> Table:
    """Copy a TAP result before attaching portable StarSkill provenance metadata."""
    result = table.copy(copy_data=True)
    result.meta.update(
        {
            "starskill_status": provenance.status,
            "starskill_service": provenance.service,
            "starskill_endpoint": provenance.endpoint,
            "starskill_query_sha256": provenance.query_sha256,
            "starskill_row_count": provenance.row_count,
        }
    )
    return result
