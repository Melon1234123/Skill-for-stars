import pytest

from starskill.query.errors import UnknownVOServiceError
from starskill.query.registry import VOServiceRegistry, default_registry


def test_packaged_registry_has_the_required_allowlisted_services() -> None:
    registry = default_registry()

    assert set(registry.services) == {"simbad", "vizier", "gaia"}
    assert registry.get("GAIA").tap_endpoint == "https://gea.esac.esa.int/tap-server/tap"


def test_registry_rejects_unknown_service_ids_without_an_endpoint_fallback() -> None:
    with pytest.raises(UnknownVOServiceError, match="not allowlisted"):
        default_registry().get("https://untrusted.example/tap")


def test_registry_rejects_duplicate_ids_and_bad_schema() -> None:
    duplicate = """
schema_version: "1.0"
services:
  - service_id: gaia
    name: Gaia
    organization: ESA
    tap_endpoint: https://example.test/tap
    default_tables: [gaiadr3.gaia_source]
  - service_id: gaia
    name: Gaia duplicate
    organization: ESA
    tap_endpoint: https://example.test/other
    default_tables: [gaiadr3.gaia_source]
"""

    with pytest.raises(ValueError, match="unique"):
        VOServiceRegistry.from_yaml(duplicate)
    with pytest.raises(ValueError, match="schema version"):
        VOServiceRegistry.from_yaml("services: []")
