"""Deterministic ADQL builders for bounded catalog workflows."""

from __future__ import annotations

import math
import re

from starskill.query.errors import InvalidADQLError
from starskill.query.models import CatalogFilter, CatalogQueryRequest, ConeSearchRequest


_SELECT_RE = re.compile(r"^\s*SELECT(?:\s+(?P<modifier>DISTINCT|ALL))?\s+", re.IGNORECASE)
_DANGEROUS_TOKEN_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|REVOKE|TRUNCATE|EXEC|CALL)\b",
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(r"--|/\*|\*/")


def _format_float(value: float) -> str:
    if not math.isfinite(value):
        raise InvalidADQLError("ADQL numeric values must be finite")
    return format(value, ".12g")


def _literal(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _format_float(value)
    return "'" + value.replace("'", "''") + "'"


def _columns(columns: list[str]) -> str:
    return ", ".join(columns)


def _filters(filters: list[CatalogFilter]) -> str:
    if not filters:
        return ""
    clauses = [f"{item.column} {item.operator} {_literal(item.value)}" for item in filters]
    return " WHERE " + " AND ".join(clauses)


def build_catalog_query(request: CatalogQueryRequest) -> str:
    """Build a read-only catalog query only from typed request fields."""
    return (
        f"SELECT TOP {request.max_rows} {_columns(request.columns)} "
        f"FROM {request.table}{_filters(request.filters)}"
    )


def build_cone_search(request: ConeSearchRequest) -> str:
    """Build an ICRS cone query using ADQL geometry functions."""
    cone = (
        "1 = CONTAINS("
        f"POINT('ICRS', {request.ra_column}, {request.dec_column}), "
        f"CIRCLE('ICRS', {_format_float(request.ra_deg)}, "
        f"{_format_float(request.dec_deg)}, {_format_float(request.radius_deg)})"
        ")"
    )
    where = _filters(request.filters)
    suffix = f" WHERE {cone}" if not where else f"{where} AND {cone}"
    return (
        f"SELECT TOP {request.max_rows} {_columns(request.columns)} "
        f"FROM {request.table}{suffix}"
    )


def build_table_description_query(table: str, max_rows: int) -> str:
    """Read a table schema through the standard TAP_SCHEMA.columns metadata table."""
    escaped = table.replace("'", "''")
    return (
        "SELECT TOP "
        f"{max_rows} column_name, datatype, unit, ucd, description "
        "FROM TAP_SCHEMA.columns "
        f"WHERE table_name = '{escaped}' ORDER BY column_name"
    )


def enforce_read_only_select(adql: str, max_rows: int) -> str:
    """Reject multi-statement or write ADQL and inject the authoritative TOP limit."""
    normalized = adql.strip()
    if ";" in normalized or _COMMENT_RE.search(normalized):
        raise InvalidADQLError("ADQL must contain one uncommented statement")
    if _DANGEROUS_TOKEN_RE.search(normalized):
        raise InvalidADQLError("ADQL must be read-only")
    match = _SELECT_RE.match(normalized)
    if match is None or not re.search(r"\bFROM\b", normalized, re.IGNORECASE):
        raise InvalidADQLError("ADQL must be a SELECT query with FROM")
    if re.search(r"\bTOP\b", normalized, re.IGNORECASE):
        raise InvalidADQLError("ADQL TOP is managed by max_rows")
    modifier = match.group("modifier")
    prefix = "SELECT"
    if modifier is not None:
        prefix += f" {modifier.upper()}"
    return f"{prefix} TOP {max_rows} {normalized[match.end():]}"
