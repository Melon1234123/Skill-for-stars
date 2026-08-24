import pytest

from starskill.query.adql import (
    build_catalog_query,
    build_cone_search,
    build_table_description_query,
    enforce_read_only_select,
)
from starskill.query.errors import InvalidADQLError
from starskill.query.models import CatalogQueryRequest, ConeSearchRequest


def test_catalog_builder_uses_typed_parameters_and_escapes_strings() -> None:
    request = CatalogQueryRequest(
        service="gaia",
        table="gaiadr3.gaia_source",
        columns=["source_id", "phot_g_mean_mag"],
        filters=[
            {"column": "phot_g_mean_mag", "operator": "<", "value": 12.5},
            {"column": "designation", "operator": "LIKE", "value": "O'Brien%"},
        ],
        max_rows=25,
    )

    assert build_catalog_query(request) == (
        "SELECT TOP 25 source_id, phot_g_mean_mag FROM gaiadr3.gaia_source "
        "WHERE phot_g_mean_mag < 12.5 AND designation LIKE 'O''Brien%'"
    )


def test_cone_builder_adds_icrs_geometry_and_keeps_filters() -> None:
    request = ConeSearchRequest(
        service="gaia",
        table="gaiadr3.gaia_source",
        columns=["source_id"],
        filters=[{"column": "phot_g_mean_mag", "operator": "<", "value": 15}],
        max_rows=5,
        ra_deg=83.82,
        dec_deg=-5.39,
        radius_deg=0.2,
    )

    assert build_cone_search(request) == (
        "SELECT TOP 5 source_id FROM gaiadr3.gaia_source "
        "WHERE phot_g_mean_mag < 15 AND 1 = CONTAINS("
        "POINT('ICRS', ra, dec), CIRCLE('ICRS', 83.82, -5.39, 0.2))"
    )


def test_table_description_uses_tap_schema_metadata() -> None:
    assert build_table_description_query("gaiadr3.gaia_source", 20) == (
        "SELECT TOP 20 column_name, datatype, unit, ucd, description "
        "FROM TAP_SCHEMA.columns WHERE table_name = 'gaiadr3.gaia_source' "
        "ORDER BY column_name"
    )


@pytest.mark.parametrize(
    "adql",
    [
        "DELETE FROM gaiadr3.gaia_source",
        "SELECT TOP 5 source_id FROM gaiadr3.gaia_source",
        "SELECT source_id FROM gaiadr3.gaia_source; DROP TABLE x",
        "SELECT source_id -- comment\nFROM gaiadr3.gaia_source",
    ],
)
def test_advanced_adql_rejects_non_read_only_or_unmanaged_limits(adql: str) -> None:
    with pytest.raises(InvalidADQLError):
        enforce_read_only_select(adql, 10)


def test_advanced_adql_injects_the_authoritative_max_rows() -> None:
    assert enforce_read_only_select(
        "select distinct source_id from gaiadr3.gaia_source", 10
    ) == "SELECT DISTINCT TOP 10 source_id from gaiadr3.gaia_source"
