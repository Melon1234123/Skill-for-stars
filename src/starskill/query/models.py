"""Pydantic contracts for the bounded IVOA query layer."""

from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from starskill.schemas import ArtifactRecord


_SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_TABLE_NAME_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:[./][A-Za-z0-9_]+){0,4}$"
)
_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class QueryModel(BaseModel):
    """Strict JSON-compatible model shared by VO request and result contracts."""

    model_config = ConfigDict(extra="forbid")


def _normalize_service_id(value: str) -> str:
    normalized = value.strip().casefold()
    if not _SERVICE_ID_RE.fullmatch(normalized):
        raise ValueError("service must be a stable registry service ID")
    return normalized


def _validate_table_name(value: str) -> str:
    normalized = value.strip()
    if not _TABLE_NAME_RE.fullmatch(normalized):
        raise ValueError("table must be a qualified TAP table identifier")
    return normalized


def _validate_column_name(value: str) -> str:
    normalized = value.strip()
    if normalized != "*" and not _COLUMN_RE.fullmatch(normalized):
        raise ValueError("column must be an ADQL identifier or '*'")
    return normalized


class VOService(QueryModel):
    """One allowlisted public IVOA TAP service."""

    service_id: str
    name: str = Field(min_length=1, max_length=160)
    organization: str = Field(min_length=1, max_length=200)
    tap_endpoint: str
    default_tables: tuple[str, ...] = Field(min_length=1)

    @field_validator("service_id")
    @classmethod
    def service_id_is_stable(cls, value: str) -> str:
        return _normalize_service_id(value)

    @field_validator("tap_endpoint")
    @classmethod
    def endpoint_is_safe_https_origin(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("tap_endpoint must be an HTTPS URL without credentials")
        return normalized.rstrip("/")

    @field_validator("default_tables")
    @classmethod
    def default_tables_are_safe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_table_name(table) for table in value)


class BaseQueryRequest(QueryModel):
    service: str
    max_rows: int = Field(default=1_000, ge=1, le=10_000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)

    @field_validator("service")
    @classmethod
    def service_is_registry_id(cls, value: str) -> str:
        return _normalize_service_id(value)


class TableDescriptionRequest(BaseQueryRequest):
    table: str
    max_rows: int = Field(default=200, ge=1, le=2_000)

    @field_validator("table")
    @classmethod
    def table_is_safe(cls, value: str) -> str:
        return _validate_table_name(value)


class CatalogFilter(QueryModel):
    column: str
    operator: Literal["=", "!=", "<", "<=", ">", ">=", "LIKE"]
    value: str | int | float | bool

    @field_validator("column")
    @classmethod
    def column_is_safe(cls, value: str) -> str:
        return _validate_column_name(value)

    @field_validator("value")
    @classmethod
    def numeric_values_are_finite(cls, value: str | int | float | bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("numeric filter values must be finite")
        return value

    @model_validator(mode="after")
    def like_requires_text(self) -> "CatalogFilter":
        if self.operator == "LIKE" and not isinstance(self.value, str):
            raise ValueError("LIKE filters require a string value")
        return self


class CatalogQueryRequest(BaseQueryRequest):
    table: str
    columns: list[str] = Field(default_factory=lambda: ["*"], min_length=1, max_length=32)
    filters: list[CatalogFilter] = Field(default_factory=list, max_length=16)

    @field_validator("table")
    @classmethod
    def table_is_safe(cls, value: str) -> str:
        return _validate_table_name(value)

    @field_validator("columns")
    @classmethod
    def columns_are_safe(cls, value: list[str]) -> list[str]:
        normalized = [_validate_column_name(column) for column in value]
        if "*" in normalized and len(normalized) != 1:
            raise ValueError("'*' cannot be combined with named columns")
        if len(normalized) != len(set(normalized)):
            raise ValueError("columns must be unique")
        return normalized


class ConeSearchRequest(CatalogQueryRequest):
    ra_deg: float = Field(ge=0, lt=360, allow_inf_nan=False)
    dec_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    radius_deg: float = Field(gt=0, le=5, allow_inf_nan=False)
    ra_column: str = "ra"
    dec_column: str = "dec"

    @field_validator("ra_column", "dec_column")
    @classmethod
    def coordinate_columns_are_safe(cls, value: str) -> str:
        return _validate_column_name(value)


class TapQueryRequest(BaseQueryRequest):
    adql: str = Field(min_length=8, max_length=20_000)

    @field_validator("adql")
    @classmethod
    def adql_is_nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("adql must not be blank")
        return normalized


QueryOperation = Literal[
    "describe_table",
    "cone_search",
    "catalog_query",
    "tap_query",
]
QueryStatus = Literal["success", "failed"]


class QueryFailure(QueryModel):
    code: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9_]+$")
    message: str = Field(min_length=1, max_length=500)


class QueryProvenance(QueryModel):
    operation: QueryOperation
    service: str
    service_name: str
    endpoint: str
    table: str | None = None
    final_adql: str
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accessed_at: datetime
    max_rows: int = Field(ge=1)
    timeout_seconds: int = Field(ge=1)
    row_count: int = Field(ge=0)
    status: QueryStatus
    source: str
    failure: QueryFailure | None = None

    @model_validator(mode="after")
    def failure_matches_status(self) -> "QueryProvenance":
        if self.status == "success" and self.failure is not None:
            raise ValueError("successful provenance cannot include a failure")
        if self.status == "failed" and self.failure is None:
            raise ValueError("failed provenance requires a structured failure")
        return self


class QueryResult(QueryModel):
    ok: bool
    status: QueryStatus
    service: str
    row_count: int = Field(ge=0)
    provenance: QueryProvenance
    artifacts: list[ArtifactRecord] = Field(min_length=4)
    failure: QueryFailure | None = None

    @model_validator(mode="after")
    def result_matches_provenance(self) -> "QueryResult":
        if self.ok != (self.status == "success"):
            raise ValueError("ok must match status")
        if self.status != self.provenance.status:
            raise ValueError("result status must match provenance")
        if self.service != self.provenance.service:
            raise ValueError("result service must match provenance")
        if self.row_count != self.provenance.row_count:
            raise ValueError("result row_count must match provenance")
        if self.failure != self.provenance.failure:
            raise ValueError("result failure must match provenance")
        return self
