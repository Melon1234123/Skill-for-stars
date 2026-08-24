"""Execution layer for allowlisted, auditable IVOA TAP queries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from astropy.table import Table
from pyvo.dal import TAPService
from pyvo.dal.exceptions import (
    DALFormatError,
    DALQueryError,
    DALServiceError,
)
import requests

from starskill.query.adql import (
    build_catalog_query,
    build_cone_search,
    build_table_description_query,
    enforce_read_only_select,
)
from starskill.query.errors import (
    VOQueryError,
    VOQueryNetworkError,
    VOQueryServiceError,
    VOQueryTimeoutError,
)
from starskill.query.models import (
    BaseQueryRequest,
    CatalogQueryRequest,
    ConeSearchRequest,
    QueryFailure,
    QueryOperation,
    QueryProvenance,
    QueryResult,
    TableDescriptionRequest,
    TapQueryRequest,
    VOService,
)
from starskill.query.provenance import (
    annotate_result_table,
    failure_table,
    query_sha256,
    write_query_artifacts,
)
from starskill.query.registry import VOServiceRegistry, default_registry


class TapBackend(Protocol):
    """Small injectable seam around PyVO for deterministic offline tests."""

    def execute(
        self,
        endpoint: str,
        adql: str,
        *,
        max_rows: int,
        timeout_seconds: int,
    ) -> Table: ...


class _TimeoutSession(requests.Session):
    """Requests session that makes PyVO's otherwise implicit timeout explicit."""

    def __init__(self, timeout_seconds: int) -> None:
        super().__init__()
        self._timeout_seconds = timeout_seconds

    def request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("timeout", self._timeout_seconds)
        return super().request(*args, **kwargs)


class PyvoTapBackend:
    """Run synchronous ADQL requests with PyVO and bounded HTTP transport."""

    def execute(
        self,
        endpoint: str,
        adql: str,
        *,
        max_rows: int,
        timeout_seconds: int,
    ) -> Table:
        session = _TimeoutSession(timeout_seconds)
        service = TAPService(endpoint, session=session)
        result = service.run_sync(adql, language="ADQL", maxrec=max_rows)
        return result.to_table()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VOQueryClient:
    """Execute VO queries only against the packaged service registry."""

    def __init__(
        self,
        *,
        registry: VOServiceRegistry | None = None,
        backend: TapBackend | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.registry = registry or default_registry()
        self.backend = backend or PyvoTapBackend()
        self.clock = clock

    def describe_table(
        self, request: TableDescriptionRequest, *, output_dir: Path
    ) -> QueryResult:
        service = self.registry.get(request.service)
        adql = build_table_description_query(request.table, request.max_rows)
        return self._execute(
            request=request,
            service=service,
            operation="describe_table",
            table_name=request.table,
            final_adql=adql,
            output_dir=output_dir,
        )

    def cone_search(
        self, request: ConeSearchRequest, *, output_dir: Path
    ) -> QueryResult:
        service = self.registry.get(request.service)
        return self._execute(
            request=request,
            service=service,
            operation="cone_search",
            table_name=request.table,
            final_adql=build_cone_search(request),
            output_dir=output_dir,
        )

    def catalog_query(
        self, request: CatalogQueryRequest, *, output_dir: Path
    ) -> QueryResult:
        service = self.registry.get(request.service)
        return self._execute(
            request=request,
            service=service,
            operation="catalog_query",
            table_name=request.table,
            final_adql=build_catalog_query(request),
            output_dir=output_dir,
        )

    def tap_query(self, request: TapQueryRequest, *, output_dir: Path) -> QueryResult:
        service = self.registry.get(request.service)
        return self._execute(
            request=request,
            service=service,
            operation="tap_query",
            table_name=None,
            final_adql=enforce_read_only_select(request.adql, request.max_rows),
            output_dir=output_dir,
        )

    def _execute(
        self,
        *,
        request: BaseQueryRequest,
        service: VOService,
        operation: QueryOperation,
        table_name: str | None,
        final_adql: str,
        output_dir: Path,
    ) -> QueryResult:
        accessed_at = self.clock()
        digest = query_sha256(final_adql)
        try:
            table = self.backend.execute(
                service.tap_endpoint,
                final_adql,
                max_rows=request.max_rows,
                timeout_seconds=request.timeout_seconds,
            )
            if not isinstance(table, Table):
                raise VOQueryServiceError("TAP backend did not return an Astropy Table")
            if len(table) > request.max_rows:
                table = table[: request.max_rows]
            provenance = self._provenance(
                operation=operation,
                service=service,
                table_name=table_name,
                final_adql=final_adql,
                digest=digest,
                request=request,
                accessed_at=accessed_at,
                row_count=len(table),
                status="success",
            )
            artifacts = write_query_artifacts(
                output_dir=output_dir,
                request=request,
                adql=final_adql,
                table=annotate_result_table(table, provenance),
                provenance=provenance,
            )
            return QueryResult(
                ok=True,
                status="success",
                service=service.service_id,
                row_count=len(table),
                provenance=provenance,
                artifacts=artifacts,
            )
        except Exception as exc:
            failure = self._failure_for(exc)
            provenance = self._provenance(
                operation=operation,
                service=service,
                table_name=table_name,
                final_adql=final_adql,
                digest=digest,
                request=request,
                accessed_at=accessed_at,
                row_count=0,
                status="failed",
                failure=failure,
            )
            artifacts = write_query_artifacts(
                output_dir=output_dir,
                request=request,
                adql=final_adql,
                table=failure_table(provenance),
                provenance=provenance,
            )
            return QueryResult(
                ok=False,
                status="failed",
                service=service.service_id,
                row_count=0,
                provenance=provenance,
                artifacts=artifacts,
                failure=failure,
            )

    @staticmethod
    def _failure_for(exc: Exception) -> QueryFailure:
        if isinstance(exc, VOQueryError):
            return QueryFailure(code=exc.code, message=str(exc))
        if isinstance(exc, (TimeoutError, requests.Timeout)):
            return QueryFailure(
                code=VOQueryTimeoutError.code,
                message="TAP query timed out",
            )
        if isinstance(exc, (requests.RequestException, OSError)):
            return QueryFailure(
                code=VOQueryNetworkError.code,
                message="TAP network request failed",
            )
        if isinstance(exc, (DALServiceError, DALQueryError, DALFormatError)):
            return QueryFailure(
                code=VOQueryServiceError.code,
                message="TAP service returned an invalid response",
            )
        return QueryFailure(
            code=VOQueryServiceError.code,
            message="TAP service query failed",
        )

    @staticmethod
    def _provenance(
        *,
        operation: QueryOperation,
        service: VOService,
        table_name: str | None,
        final_adql: str,
        digest: str,
        request: BaseQueryRequest,
        accessed_at: datetime,
        row_count: int,
        status: str,
        failure: QueryFailure | None = None,
    ) -> QueryProvenance:
        return QueryProvenance(
            operation=operation,
            service=service.service_id,
            service_name=service.name,
            endpoint=service.tap_endpoint,
            table=table_name,
            final_adql=final_adql,
            query_sha256=digest,
            accessed_at=accessed_at,
            max_rows=request.max_rows,
            timeout_seconds=request.timeout_seconds,
            row_count=row_count,
            status=status,
            source=service.organization,
            failure=failure,
        )


def describe_table(
    request: TableDescriptionRequest,
    *,
    output_dir: Path,
    registry: VOServiceRegistry | None = None,
    backend: TapBackend | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> QueryResult:
    return VOQueryClient(registry=registry, backend=backend, clock=clock).describe_table(
        request, output_dir=output_dir
    )


def cone_search(
    request: ConeSearchRequest,
    *,
    output_dir: Path,
    registry: VOServiceRegistry | None = None,
    backend: TapBackend | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> QueryResult:
    return VOQueryClient(registry=registry, backend=backend, clock=clock).cone_search(
        request, output_dir=output_dir
    )


def catalog_query(
    request: CatalogQueryRequest,
    *,
    output_dir: Path,
    registry: VOServiceRegistry | None = None,
    backend: TapBackend | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> QueryResult:
    return VOQueryClient(registry=registry, backend=backend, clock=clock).catalog_query(
        request, output_dir=output_dir
    )


def tap_query(
    request: TapQueryRequest,
    *,
    output_dir: Path,
    registry: VOServiceRegistry | None = None,
    backend: TapBackend | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> QueryResult:
    return VOQueryClient(registry=registry, backend=backend, clock=clock).tap_query(
        request, output_dir=output_dir
    )
