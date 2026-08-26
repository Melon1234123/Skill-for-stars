from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from starskill import schemas
from starskill.external_data import ExternalDataNetworkError
from starskill.horizons import (
    HORIZONS_ENDPOINT,
    HORIZONS_MAX_BYTES,
    HORIZONS_TIMEOUT_SECONDS,
    HorizonsAmbiguousBodyError,
    HorizonsBodyNotFoundError,
    HorizonsResponseError,
    HorizonsServiceError,
)
from starskill.solar_system_relationship import calculate_astronomical_relationship
from starskill.target_references import UnsupportedSolarSystemBodyError


FIXED_NOW = datetime(2026, 1, 10, 10, 0, tzinfo=timezone.utc)


def fixed_clock() -> datetime:
    return FIXED_NOW


def horizons_payload(rows: list[tuple[str, float, float]]) -> dict[str, Any]:
    lines = "\n".join(
        f" {date}, , , {azimuth:.4f}, {altitude:.4f}," for date, azimuth, altitude in rows
    )
    text = (
        "*******************************************************************************\n"
        "Target body name: 1 Ceres (A801 AA)               {source: JPL#48}\n"
        "*******************************************************************************\n"
        " Date__(UT)__HR:MN, , , Azi_(a-app), Elev_(a-app),\n"
        "$$SOE\n"
        f"{lines}\n"
        "$$EOE\n"
    )
    return {
        "result": text,
        "signature": {"source": "NASA/JPL Horizons API", "version": "1.2"},
    }


class StaticHorizonsBackend:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, int, int]] = []

    def fetch_json(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, Any]:
        self.calls.append((url, timeout_seconds, max_bytes))
        return self.payload


class FailingHorizonsBackend:
    def fetch_json(
        self,
        url: str,
        *,
        timeout_seconds: int,
        max_bytes: int,
    ) -> dict[str, Any]:
        raise ExternalDataNetworkError("external data request failed")


def make_task(
    primary: dict[str, Any],
    secondary: dict[str, Any] | None = None,
) -> schemas.AstronomicalRelationshipTask:
    return schemas.AstronomicalRelationshipTask.model_validate(
        {
            "task_type": "astronomical_relationship",
            "primary": primary,
            "secondary": secondary
            or {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20},
            "observer": {
                "location_name": "Shanghai",
                "longitude": 121.4737,
                "latitude": 31.2304,
                "timezone": "Asia/Shanghai",
            },
            "time_range": {
                "start": "2026-01-10T18:00:00+08:00",
                "end": "2026-01-10T18:20:00+08:00",
            },
            "interval_minutes": 20,
        }
    )


TWO_ROWS = [
    ("2026-Jan-10 10:00", 123.4567, 45.6789),
    ("2026-Jan-10 10:20", 124.9876, 44.3210),
]


def test_horizons_target_ref_normalizes_and_rejects_unsafe_bodies() -> None:
    adapter = TypeAdapter(schemas.RelationshipTargetRef)

    reference = adapter.validate_python({"kind": "horizons", "body": "  1P/Halley "})
    assert reference.body == "1p/halley"

    with pytest.raises(ValidationError, match="horizons body"):
        adapter.validate_python({"kind": "horizons", "body": "Ceres;DES=1"})


def test_relationship_samples_horizons_positions_at_each_time_step(tmp_path) -> None:
    backend = StaticHorizonsBackend(horizons_payload(TWO_ROWS))

    result = calculate_astronomical_relationship(
        make_task({"kind": "horizons", "body": "Ceres"}),
        horizons_backend=backend,
        cache_dir=tmp_path,
        clock=fixed_clock,
    )

    assert len(result.samples) == 2
    assert result.primary.kind == "horizons"
    assert result.primary.motion == "dynamic"
    assert result.primary.label == "1 Ceres (A801 AA)"
    assert result.primary.source.provider == "jpl_horizons"
    assert result.primary.source.from_cache is False
    for sample, (_, azimuth, altitude) in zip(result.samples, TWO_ROWS, strict=True):
        assert sample.primary_azimuth_deg == pytest.approx(azimuth, abs=1e-4)
        assert sample.primary_altitude_deg == pytest.approx(altitude, abs=1e-4)
        assert 0 <= sample.angular_separation_deg <= 180

    query = result.primary.horizons_query
    assert query is not None
    assert query.endpoint == HORIZONS_ENDPOINT
    assert query.from_cache is False
    assert query.accessed_at == FIXED_NOW
    assert query.query_parameters["COMMAND"] == "'ceres;'"
    assert query.query_parameters["EPHEM_TYPE"] == "'OBSERVER'"
    assert query.query_parameters["QUANTITIES"] == "'4'"
    assert query.query_parameters["APPARENT"] == "'AIRLESS'"
    assert query.query_parameters["SITE_COORD"] == "'121.473700,31.230400,0'"
    assert len(query.query_parameters["TLIST"].split()) == 2

    (url, timeout_seconds, max_bytes) = backend.calls[0]
    assert url.startswith(f"{HORIZONS_ENDPOINT}?")
    assert (timeout_seconds, max_bytes) == (
        HORIZONS_TIMEOUT_SECONDS,
        HORIZONS_MAX_BYTES,
    )


def test_second_run_reuses_the_validated_cache_offline(tmp_path) -> None:
    task = make_task({"kind": "horizons", "body": "Ceres"})
    fresh = calculate_astronomical_relationship(
        task,
        horizons_backend=StaticHorizonsBackend(horizons_payload(TWO_ROWS)),
        cache_dir=tmp_path,
        clock=fixed_clock,
    )

    cached = calculate_astronomical_relationship(
        task,
        horizons_backend=FailingHorizonsBackend(),
        cache_dir=tmp_path,
        clock=fixed_clock,
    )

    assert fresh.primary.source.from_cache is False
    assert cached.primary.source.from_cache is True
    assert cached.primary.horizons_query.from_cache is True
    for fresh_sample, cached_sample in zip(
        fresh.samples, cached.samples, strict=True
    ):
        assert cached_sample.primary_azimuth_deg == fresh_sample.primary_azimuth_deg
        assert cached_sample.primary_altitude_deg == fresh_sample.primary_altitude_deg


def test_missing_backend_is_a_structured_service_failure() -> None:
    with pytest.raises(HorizonsServiceError) as exc_info:
        calculate_astronomical_relationship(
            make_task({"kind": "horizons", "body": "Ceres"}),
            clock=fixed_clock,
        )

    assert exc_info.value.code == "horizons_service_error"


def test_network_failure_stays_structured_without_fabricated_positions(tmp_path) -> None:
    with pytest.raises(HorizonsServiceError) as exc_info:
        calculate_astronomical_relationship(
            make_task({"kind": "horizons", "body": "Ceres"}),
            horizons_backend=FailingHorizonsBackend(),
            cache_dir=tmp_path,
            clock=fixed_clock,
        )

    assert exc_info.value.code == "horizons_service_error"
    assert not any((tmp_path / "horizons").glob("*")) or not list(
        (tmp_path / "horizons").glob("*.json")
    )


def test_unknown_body_is_a_structured_not_found_failure() -> None:
    backend = StaticHorizonsBackend(
        {"result": "No matches found.", "signature": {"version": "1.2"}}
    )

    with pytest.raises(HorizonsBodyNotFoundError) as exc_info:
        calculate_astronomical_relationship(
            make_task({"kind": "horizons", "body": "definitely not a body"}),
            horizons_backend=backend,
            clock=fixed_clock,
        )

    assert exc_info.value.code == "horizons_body_not_found"


def test_ambiguous_designation_is_a_structured_input_failure() -> None:
    backend = StaticHorizonsBackend(
        {
            "result": "Matching small-bodies:\n  90000033  1P Halley\n  90000034 ...",
            "signature": {"version": "1.2"},
        }
    )

    with pytest.raises(HorizonsAmbiguousBodyError) as exc_info:
        calculate_astronomical_relationship(
            make_task({"kind": "horizons", "body": "halley"}),
            horizons_backend=backend,
            clock=fixed_clock,
        )

    assert exc_info.value.code == "horizons_ambiguous_body"


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "unknown units specification", "result": "x"},
        {"signature": {"version": "1.2"}},
        {"result": "no ephemeris table here", "signature": {"version": "1.2"}},
        horizons_payload(TWO_ROWS[:1]),
        horizons_payload([*TWO_ROWS, ("2026-Jan-10 10:40", 1.0, 2.0)]),
        horizons_payload([("2026-Jan-10 10:00", 10.0, 95.0), TWO_ROWS[1]]),
    ],
)
def test_malformed_responses_are_structured_service_failures(
    payload: dict[str, Any],
) -> None:
    with pytest.raises((HorizonsResponseError, HorizonsServiceError)):
        calculate_astronomical_relationship(
            make_task({"kind": "horizons", "body": "Ceres"}),
            horizons_backend=StaticHorizonsBackend(payload),
            clock=fixed_clock,
        )


def test_offline_solar_system_default_never_falls_back_to_horizons() -> None:
    backend = StaticHorizonsBackend(horizons_payload(TWO_ROWS))

    with pytest.raises(UnsupportedSolarSystemBodyError) as exc_info:
        calculate_astronomical_relationship(
            make_task({"kind": "solar_system", "body": "ceres"}),
            horizons_backend=backend,
            clock=fixed_clock,
        )

    assert exc_info.value.code == "unsupported_solar_system_body"
    assert backend.calls == []


def test_resolved_horizons_target_requires_query_provenance() -> None:
    with pytest.raises(ValidationError, match="horizons_query"):
        schemas.ResolvedAstronomicalTarget.model_validate(
            {
                "label": "1 Ceres (A801 AA)",
                "kind": "horizons",
                "motion": "dynamic",
                "source": {
                    "provider": "jpl_horizons",
                    "from_cache": False,
                    "accessed_at": "2026-01-10T10:00:00+00:00",
                },
            }
        )
