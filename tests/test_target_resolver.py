from datetime import datetime, timezone

import pytest
from astropy.table import Table

import starskill
import starskill.schemas as schemas
import starskill.target_resolver as resolver


class StaticSimbadBackend:
    service_url = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

    def __init__(self) -> None:
        self.call_count = 0

    def query_object(self, query_name: str) -> dict:
        self.call_count += 1
        return {
            "canonical_name": "M 42",
            "ra_deg": 83.822083,
            "dec_deg": -5.391111,
            "object_type": "HII",
            "aliases": ["M 42", "NGC 1976", "Orion Nebula"],
        }


class EmptySimbadBackend:
    service_url = StaticSimbadBackend.service_url

    def query_object(self, query_name: str) -> None:
        return None


class FailingSimbadBackend:
    service_url = StaticSimbadBackend.service_url

    def query_object(self, query_name: str) -> dict:
        raise TimeoutError("SIMBAD request timed out")


class TableSimbadClient:
    def add_votable_fields(self, *fields: str) -> None:
        self.fields = fields

    def query_object(self, query_name: str) -> Table:
        return Table(
            rows=[
                (
                    "M  42",
                    83.822083,
                    -5.391111,
                    "HII",
                    "M  42|NGC  1976|Orion Nebula",
                )
            ],
            names=("main_id", "ra", "dec", "otype", "ids"),
        )


class EmptyTableSimbadClient(TableSimbadClient):
    def query_object(self, query_name: str) -> Table:
        return Table(names=("main_id", "ra", "dec", "otype", "ids"))


def test_resolved_target_preserves_coordinates_and_provenance() -> None:
    assert hasattr(schemas, "ResolvedTarget"), "ResolvedTarget schema is missing"

    target = schemas.ResolvedTarget.model_validate(
        {
            "input_name": "M42",
            "query_name": "M 42",
            "canonical_name": "M 42",
            "ra_deg": 83.822083,
            "dec_deg": -5.391111,
            "object_type": "HII",
            "aliases": ["M 42", "NGC 1976"],
            "coordinate_frame": "ICRS",
            "source": {
                "database": "SIMBAD",
                "service_url": "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
                "accessed_at": "2026-07-18T10:00:00Z",
                "from_cache": False,
            },
        }
    )

    assert target.ra_deg == 83.822083
    assert target.dec_deg == -5.391111
    assert target.source.accessed_at == datetime(
        2026, 7, 18, 10, 0, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    ("raw_name", "query_name"),
    [
        ("M42", "M 42"),
        ("  m  42  ", "M 42"),
        ("猎户座大星云", "M 42"),
    ],
)
def test_normalize_target_name_unifies_m42_aliases(
    raw_name: str, query_name: str
) -> None:
    assert hasattr(starskill, "normalize_target_name"), "normalizer is missing"

    assert starskill.normalize_target_name(raw_name) == query_name


@pytest.mark.parametrize(
    "raw_name",
    ["   ", "M42; SELECT *", "M42\nquery id Sirius", "A" * 129],
)
def test_normalize_target_name_rejects_unsafe_queries(raw_name: str) -> None:
    with pytest.raises(ValueError, match="target name"):
        starskill.normalize_target_name(raw_name)


def test_resolve_target_converts_catalog_record_to_stable_output() -> None:
    assert hasattr(resolver, "resolve_target"), "resolver is missing"
    accessed_at = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)

    target = resolver.resolve_target(
        "猎户座大星云",
        backend=StaticSimbadBackend(),
        clock=lambda: accessed_at,
    )

    assert target.input_name == "猎户座大星云"
    assert target.query_name == "M 42"
    assert target.canonical_name == "M 42"
    assert target.ra_deg == 83.822083
    assert target.dec_deg == -5.391111
    assert target.object_type == "HII"
    assert target.aliases == ["M 42", "NGC 1976", "Orion Nebula"]
    assert target.source.database == "SIMBAD"
    assert target.source.service_url == StaticSimbadBackend.service_url
    assert target.source.accessed_at == accessed_at
    assert target.source.from_cache is False


def test_resolve_target_reuses_cache_without_second_remote_query(tmp_path) -> None:
    backend = StaticSimbadBackend()
    accessed_at = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)

    first = resolver.resolve_target(
        "猎户座大星云",
        backend=backend,
        cache_dir=tmp_path,
        clock=lambda: accessed_at,
    )
    second = resolver.resolve_target(
        "M42",
        backend=backend,
        cache_dir=tmp_path,
        clock=lambda: datetime(2026, 7, 18, 11, 0, tzinfo=timezone.utc),
    )

    assert backend.call_count == 1
    assert first.source.from_cache is False
    assert second.source.from_cache is True
    assert second.source.accessed_at == accessed_at
    assert second.input_name == "M42"
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_resolve_target_replaces_corrupt_cache(tmp_path) -> None:
    backend = StaticSimbadBackend()
    cache_path = resolver.target_cache_path(tmp_path, "M 42")
    cache_path.write_text("not-json", encoding="utf-8")

    target = resolver.resolve_target("M42", backend=backend, cache_dir=tmp_path)

    assert backend.call_count == 1
    assert target.source.from_cache is False
    assert schemas.ResolvedTarget.model_validate_json(
        cache_path.read_text(encoding="utf-8")
    ).canonical_name == "M 42"


def test_resolve_target_reports_missing_catalog_object() -> None:
    assert hasattr(resolver, "TargetNotFoundError"), "not-found error is missing"

    with pytest.raises(resolver.TargetNotFoundError) as exc_info:
        resolver.resolve_target("Unknown Object", backend=EmptySimbadBackend())

    assert exc_info.value.code == "target_not_found"
    assert "Unknown Object" in str(exc_info.value)


def test_resolve_target_wraps_remote_service_failure() -> None:
    assert hasattr(resolver, "TargetServiceError"), "service error is missing"

    with pytest.raises(resolver.TargetServiceError) as exc_info:
        resolver.resolve_target("M42", backend=FailingSimbadBackend())

    assert exc_info.value.code == "target_service_error"
    assert isinstance(exc_info.value.__cause__, TimeoutError)


def test_simbad_backend_parses_complete_astroquery_record() -> None:
    assert hasattr(resolver, "SimbadBackend"), "SIMBAD backend is missing"
    client = TableSimbadClient()

    record = resolver.SimbadBackend(client=client).query_object("M 42")

    assert getattr(client, "timeout", None) == 30
    assert record == {
        "canonical_name": "M 42",
        "ra_deg": 83.822083,
        "dec_deg": -5.391111,
        "object_type": "HII",
        "aliases": ["M 42", "NGC 1976", "Orion Nebula"],
    }


def test_simbad_backend_returns_none_for_empty_result() -> None:
    backend = resolver.SimbadBackend(client=EmptyTableSimbadClient())

    assert backend.query_object("Unknown Object") is None
