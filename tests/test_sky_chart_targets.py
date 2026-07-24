import pytest

from pydantic import ValidationError

from starskill.schemas import (
    AstronomicalTargetSource,
    ResolvedAstronomicalTarget,
    ResolvedTarget,
    SkyChartTarget,
    TargetSource,
)
from starskill.sky_chart_targets import SkyChartTargetResolver
from starskill.target_references import UnsupportedSolarSystemBodyError
from starskill.target_resolver import TargetNotFoundError, TargetServiceError


def test_coordinate_target_delegates_to_target_ref_resolver() -> None:
    resolved_refs = []

    def resolve_ref(target):
        resolved_refs.append(target)
        return ResolvedAstronomicalTarget(
            label=target.label,
            kind=target.kind,
            motion="fixed_icrs",
            ra_deg=target.ra_deg,
            dec_deg=target.dec_deg,
            source=AstronomicalTargetSource(
                provider="user_coordinates",
                from_cache=False,
                accessed_at="2026-01-01T00:00:00Z",
            ),
        )

    resolver = SkyChartTargetResolver(
        external_resolver=lambda _name: None,
        target_ref_resolver=resolve_ref,
    )

    result = resolver.resolve(
        SkyChartTarget(mode="coordinates", ra_deg=83.822083, dec_deg=-5.391111)
    )

    assert result is not None and result.source == "input_coordinates"
    assert resolved_refs[0].kind == "coordinates"


def test_coordinate_target_never_calls_network_resolver() -> None:
    called: list[str] = []
    resolver = SkyChartTargetResolver(external_resolver=lambda name: called.append(name))

    result = resolver.resolve(
        SkyChartTarget(mode="coordinates", ra_deg=83.822083, dec_deg=-5.391111)
    )

    assert result is not None and result.source == "input_coordinates"
    assert called == []


def test_builtin_m42_is_resolved_without_network() -> None:
    result = SkyChartTargetResolver(external_resolver=lambda name: None).resolve(
        SkyChartTarget(mode="name", name="M42")
    )

    assert result is not None
    assert result.label == "M42"
    assert result.ra_deg == 83.822083
    assert result.dec_deg == -5.391111
    assert result.source == "bundled"


def test_solar_system_name_is_resolved_without_network() -> None:
    called: list[str] = []
    result = SkyChartTargetResolver(external_resolver=called.append).resolve(
        SkyChartTarget(mode="name", name="Jupiter")
    )

    assert result is not None
    assert result.solar_system_body == "jupiter"
    assert result.source == "solar_system"
    assert called == []


def test_pluto_name_raises_explicit_unsupported_error_without_external_resolution() -> None:
    def fail_if_called(_name: str) -> ResolvedTarget | None:
        raise AssertionError("legacy external resolver must not receive Pluto")

    resolver = SkyChartTargetResolver(external_resolver=fail_if_called)

    with pytest.raises(UnsupportedSolarSystemBodyError) as exc_info:
        resolver.resolve(SkyChartTarget(mode="name", name="Pluto"))

    assert exc_info.value.code == "unsupported_solar_system_body"


def test_external_resolver_receives_only_validated_stripped_text() -> None:
    called: list[str] = []

    def resolve_external(name: str) -> ResolvedTarget | None:
        called.append(name)
        return ResolvedTarget(
            input_name=name,
            query_name=name,
            canonical_name="Example",
            ra_deg=1,
            dec_deg=2,
            object_type="Star",
            aliases=[],
            source=TargetSource(
                database="SIMBAD",
                service_url="https://example.test",
                accessed_at="2026-01-01T00:00:00Z",
                from_cache=True,
            ),
        )

    result = SkyChartTargetResolver(external_resolver=resolve_external).resolve(
        SkyChartTarget(mode="name", name="  Example target  ")
    )

    assert called == ["Example target"]
    assert result is not None
    assert result.label == "Example"
    assert result.source == "existing_resolver"


@pytest.mark.parametrize("unsafe_name", ["M42\u0085", "M42\u200e"])
def test_unicode_control_or_format_target_name_cannot_reach_resolver(
    unsafe_name: str,
) -> None:
    called: list[str] = []
    resolver = SkyChartTargetResolver(external_resolver=called.append)

    with pytest.raises(ValidationError, match="safe visible"):
        resolver.resolve(SkyChartTarget(mode="name", name=unsafe_name))

    assert called == []


@pytest.mark.parametrize("error", [TargetNotFoundError("missing"), TargetServiceError("down")])
def test_existing_resolution_errors_remain_explicit_for_service_mapping(
    error: Exception,
) -> None:
    resolver = SkyChartTargetResolver(
        external_resolver=lambda name: (_ for _ in ()).throw(error)
    )

    with pytest.raises(type(error)):
        resolver.resolve(SkyChartTarget(mode="name", name="Example"))
