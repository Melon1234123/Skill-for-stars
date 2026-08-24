from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from starskill.query.models import (
    CatalogQueryRequest,
    ConeSearchRequest,
    QueryFailure,
    QueryProvenance,
    QueryResult,
    TapQueryRequest,
    VOService,
)
from starskill.schemas import ArtifactRecord


def test_vo_service_accepts_only_https_registry_metadata() -> None:
    service = VOService(
        service_id="gaia",
        name="Gaia Archive TAP+",
        organization="European Space Agency",
        tap_endpoint="https://gea.esac.esa.int/tap-server/tap/",
        default_tables=("gaiadr3.gaia_source",),
    )

    assert service.tap_endpoint == "https://gea.esac.esa.int/tap-server/tap"
    with pytest.raises(ValidationError, match="HTTPS"):
        VOService(
            service_id="bad",
            name="Bad",
            organization="Example",
            tap_endpoint="http://example.test/tap",
            default_tables=("catalog",),
        )


def test_structured_catalog_and_cone_requests_enforce_bounds() -> None:
    catalog = CatalogQueryRequest(
        service="GAIA",
        table="gaiadr3.gaia_source",
        columns=["source_id", "phot_g_mean_mag"],
        filters=[{"column": "phot_g_mean_mag", "operator": "<", "value": 12}],
        max_rows=25,
        timeout_seconds=10,
    )
    cone = ConeSearchRequest(
        service="gaia",
        table="gaiadr3.gaia_source",
        columns=["source_id"],
        ra_deg=83.82,
        dec_deg=-5.39,
        radius_deg=0.1,
    )

    assert catalog.service == "gaia"
    assert cone.radius_deg == 0.1
    with pytest.raises(ValidationError, match="max_rows"):
        CatalogQueryRequest(service="gaia", table="gaiadr3.gaia_source", max_rows=0)
    with pytest.raises(ValidationError, match="qualified TAP table"):
        CatalogQueryRequest(service="gaia", table="gaia_source; DROP TABLE x")
    with pytest.raises(ValidationError, match="cannot be combined"):
        CatalogQueryRequest(
            service="gaia", table="gaiadr3.gaia_source", columns=["*", "source_id"]
        )


def test_advanced_tap_request_cannot_carry_an_endpoint() -> None:
    request = TapQueryRequest(
        service="vizier",
        adql="SELECT source_id FROM I/355/gaiadr3",
        max_rows=50,
    )

    assert request.service == "vizier"
    with pytest.raises(ValidationError, match="Extra inputs"):
        TapQueryRequest(
            service="vizier",
            adql="SELECT source_id FROM I/355/gaiadr3",
            endpoint="https://untrusted.example/tap",
        )


def test_query_result_requires_consistent_provenance() -> None:
    provenance = QueryProvenance(
        operation="tap_query",
        service="gaia",
        service_name="Gaia",
        endpoint="https://example.test/tap",
        final_adql="SELECT TOP 1 source_id FROM gaiadr3.gaia_source",
        query_sha256="a" * 64,
        accessed_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        max_rows=1,
        timeout_seconds=10,
        row_count=0,
        status="failed",
        source="ESA",
        failure=QueryFailure(code="vo_query_timeout", message="timeout"),
    )
    artifacts = [
        ArtifactRecord(path=name, bytes=1, sha256="b" * 64)
        for name in ("request.json", "query.adql", "result.ecsv", "provenance.json")
    ]

    result = QueryResult(
        ok=False,
        status="failed",
        service="gaia",
        row_count=0,
        provenance=provenance,
        artifacts=artifacts,
        failure=provenance.failure,
    )

    assert result.failure.code == "vo_query_timeout"
    with pytest.raises(ValidationError, match="ok must match"):
        QueryResult(
            ok=True,
            status="failed",
            service="gaia",
            row_count=0,
            provenance=provenance,
            artifacts=artifacts,
            failure=provenance.failure,
        )
