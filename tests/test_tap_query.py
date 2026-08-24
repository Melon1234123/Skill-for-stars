from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from astropy.table import Table

from starskill.query.models import (
    CatalogQueryRequest,
    ConeSearchRequest,
    TableDescriptionRequest,
    TapQueryRequest,
)
from starskill.query.tap import VOQueryClient


class FakeTapBackend:
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


def assert_artifacts(output_dir: Path, result: object) -> None:
    names = {record.path for record in result.artifacts}
    assert names == {"request.json", "query.adql", "result.ecsv", "provenance.json"}
    for record in result.artifacts:
        path = output_dir / record.path
        assert path.is_file()
        assert record.bytes == len(path.read_bytes())
        assert record.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_catalog_query_uses_allowlisted_endpoint_and_writes_auditable_bundle(
    tmp_path: Path,
) -> None:
    backend = FakeTapBackend(Table({"source_id": [1, 2], "phot_g_mean_mag": [10.1, 11.2]}))
    output_dir = tmp_path / "catalog"
    request = CatalogQueryRequest(
        service="gaia",
        table="gaiadr3.gaia_source",
        columns=["source_id", "phot_g_mean_mag"],
        filters=[{"column": "phot_g_mean_mag", "operator": "<", "value": 12}],
        max_rows=2,
        timeout_seconds=7,
    )

    result = VOQueryClient(backend=backend, clock=fixed_clock).catalog_query(
        request, output_dir=output_dir
    )

    assert result.ok is True
    assert result.status == "success"
    assert result.service == "gaia"
    assert result.row_count == 2
    assert backend.calls == [
        {
            "endpoint": "https://gea.esac.esa.int/tap-server/tap",
            "adql": (
                "SELECT TOP 2 source_id, phot_g_mean_mag FROM gaiadr3.gaia_source "
                "WHERE phot_g_mean_mag < 12"
            ),
            "max_rows": 2,
            "timeout_seconds": 7,
        }
    ]
    assert (output_dir / "query.adql").read_text(encoding="utf-8").startswith(
        "SELECT TOP 2"
    )
    provenance = json.loads((output_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["endpoint"] == "https://gea.esac.esa.int/tap-server/tap"
    assert provenance["row_count"] == 2
    assert_artifacts(output_dir, result)


def test_cone_search_and_table_description_use_the_shared_fake_backend(tmp_path: Path) -> None:
    backend = FakeTapBackend(Table({"column_name": ["source_id"], "datatype": ["long"]}))
    client = VOQueryClient(backend=backend, clock=fixed_clock)

    description = client.describe_table(
        TableDescriptionRequest(service="gaia", table="gaiadr3.gaia_source"),
        output_dir=tmp_path / "description",
    )
    cone = client.cone_search(
        ConeSearchRequest(
            service="gaia",
            table="gaiadr3.gaia_source",
            columns=["source_id"],
            ra_deg=83.82,
            dec_deg=-5.39,
            radius_deg=0.1,
            max_rows=3,
        ),
        output_dir=tmp_path / "cone",
    )

    assert description.ok is True
    assert cone.ok is True
    assert "TAP_SCHEMA.columns" in backend.calls[0]["adql"]
    assert "CIRCLE('ICRS', 83.82, -5.39, 0.1)" in backend.calls[1]["adql"]


def test_advanced_tap_query_forces_top_and_persists_the_final_adql(tmp_path: Path) -> None:
    backend = FakeTapBackend(Table({"source_id": [1]}))
    request = TapQueryRequest(
        service="gaia",
        adql="SELECT source_id FROM gaiadr3.gaia_source",
        max_rows=1,
    )

    result = VOQueryClient(backend=backend, clock=fixed_clock).tap_query(
        request, output_dir=tmp_path / "tap"
    )

    assert result.provenance.final_adql == "SELECT TOP 1 source_id FROM gaiadr3.gaia_source"
    assert result.provenance.query_sha256 == hashlib.sha256(
        result.provenance.final_adql.encode("utf-8")
    ).hexdigest()


def test_network_timeout_is_a_structured_failure_with_four_evidence_files(
    tmp_path: Path,
) -> None:
    backend = FakeTapBackend(TimeoutError("connection timed out"))
    request = CatalogQueryRequest(service="gaia", table="gaiadr3.gaia_source")
    output_dir = tmp_path / "timeout"

    result = VOQueryClient(backend=backend, clock=fixed_clock).catalog_query(
        request, output_dir=output_dir
    )

    assert result.ok is False
    assert result.status == "failed"
    assert result.row_count == 0
    assert result.failure.code == "vo_query_timeout"
    provenance = json.loads((output_dir / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["status"] == "failed"
    assert provenance["failure"]["code"] == "vo_query_timeout"
    assert_artifacts(output_dir, result)
