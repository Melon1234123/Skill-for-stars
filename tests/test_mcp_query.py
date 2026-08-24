from datetime import datetime, timezone
import json
from pathlib import Path

from astropy.table import Table

from starskill.mcp_server import StarSkillMcpService
from starskill.query.models import CatalogQueryRequest, ConeSearchRequest, TableDescriptionRequest, TapQueryRequest
from starskill.query.tap import VOQueryClient


class StaticTapBackend:
    def __init__(self, result: Table | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def execute(
        self,
        endpoint: str,
        adql: str,
        *,
        max_rows: int,
        timeout_seconds: int,
    ) -> Table:
        self.calls.append(
            {
                "endpoint": endpoint,
                "adql": adql,
                "max_rows": max_rows,
                "timeout_seconds": timeout_seconds,
            }
        )
        if isinstance(self.result, Exception):
            raise self.result
        return self.result.copy(copy_data=True)


def fixed_clock() -> datetime:
    return datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)


def make_query_service(tmp_path: Path, backend: StaticTapBackend) -> StarSkillMcpService:
    return StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        clock=fixed_clock,
        vo_query_client_factory=lambda: VOQueryClient(backend=backend, clock=fixed_clock),
    )


def assert_query_response(result: dict[str, object]) -> None:
    assert {
        "ok",
        "status",
        "service",
        "row_count",
        "resources",
        "provenance",
    } <= result.keys()
    assert set(result["resources"]) == {
        "query-request",
        "query-adql",
        "query-result",
        "query-provenance",
    }


def test_mcp_query_methods_return_only_server_owned_auditable_resources(
    tmp_path: Path,
) -> None:
    backend = StaticTapBackend(Table({"source_id": [1]}))
    service = make_query_service(tmp_path, backend)

    description = service.astronomy_describe_table(
        TableDescriptionRequest(service="gaia", table="gaiadr3.gaia_source")
    )
    cone = service.astronomy_cone_search(
        ConeSearchRequest(
            service="gaia",
            table="gaiadr3.gaia_source",
            columns=["source_id"],
            ra_deg=83.82,
            dec_deg=-5.39,
            radius_deg=0.1,
        )
    )
    catalog = service.astronomy_catalog_query(
        CatalogQueryRequest(
            service="gaia",
            table="gaiadr3.gaia_source",
            columns=["source_id"],
        )
    )
    tap = service.astronomy_tap_query(
        TapQueryRequest(
            service="gaia",
            adql="SELECT source_id FROM gaiadr3.gaia_source",
            max_rows=1,
        )
    )

    for result in (description, cone, catalog, tap):
        assert_query_response(result)
        assert result["ok"] is True
        assert result["status"] == "success"
        assert result["service"] == "gaia"
        assert result["row_count"] == 1
        run_dir = tmp_path / "runs" / result["run_id"]
        provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
        assert provenance == result["provenance"]
        assert (run_dir / "request.json").is_file()
        assert (run_dir / "query.adql").is_file()
        assert (run_dir / "result.ecsv").is_file()

    assert backend.calls[0]["endpoint"] == "https://gea.esac.esa.int/tap-server/tap"
    assert "TAP_SCHEMA.columns" in backend.calls[0]["adql"]
    assert "CIRCLE('ICRS'" in backend.calls[1]["adql"]
    assert backend.calls[3]["adql"] == "SELECT TOP 1 source_id FROM gaiadr3.gaia_source"


def test_mcp_query_returns_structured_failure_and_query_evidence(tmp_path: Path) -> None:
    backend = StaticTapBackend(TimeoutError("offline fake timeout"))
    service = make_query_service(tmp_path, backend)

    result = service.astronomy_catalog_query(
        CatalogQueryRequest(service="gaia", table="gaiadr3.gaia_source")
    )

    assert_query_response(result)
    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["row_count"] == 0
    assert result["provenance"]["failure"]["code"] == "vo_query_timeout"
    assert result["resources"]["query-provenance"].endswith("/query-provenance")
