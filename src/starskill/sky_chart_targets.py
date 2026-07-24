"""Narrow target-resolution adapter for the local sky-chart service."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Literal

from starskill.schemas import (
    CoordinateTargetRef,
    ResolvedAstronomicalTarget,
    ResolvedTarget,
    SkyChartTarget,
    SolarSystemTargetRef,
    TargetRef,
)
from starskill.target_references import (
    SUPPORTED_SOLAR_SYSTEM_BODIES,
    resolve_target_ref,
)


_BUILTIN_COORDINATES = MappingProxyType(
    {
        "m42": ("M42", 83.822083, -5.391111),
        "m 42": ("M42", 83.822083, -5.391111),
    }
)

# Names accepted as solar-system inputs by the chart boundary. The core resolver
# remains the authority for whether an ephemeris is actually supported.
_KNOWN_SOLAR_SYSTEM_BODY_NAMES = frozenset((*SUPPORTED_SOLAR_SYSTEM_BODIES, "pluto"))


@dataclass(frozen=True)
class ResolvedSkyTarget:
    label: str
    ra_deg: float | None
    dec_deg: float | None
    solar_system_body: str | None
    source: Literal["input_coordinates", "bundled", "solar_system", "existing_resolver"]


class SkyChartTargetResolver:
    """Resolve only validated names through an injected existing resolver."""

    def __init__(
        self,
        external_resolver: Callable[[str], ResolvedTarget | None],
        target_ref_resolver: Callable[[TargetRef], ResolvedAstronomicalTarget] = resolve_target_ref,
    ) -> None:
        self._external_resolver = external_resolver
        self._target_ref_resolver = target_ref_resolver

    def resolve(self, target: SkyChartTarget) -> ResolvedSkyTarget | None:
        if target.mode == "coordinates":
            assert target.ra_deg is not None and target.dec_deg is not None
            resolved = self._target_ref_resolver(
                CoordinateTargetRef(
                    kind="coordinates",
                    label="RA/Dec target",
                    ra_deg=target.ra_deg,
                    dec_deg=target.dec_deg,
                )
            )
            return ResolvedSkyTarget(
                resolved.label,
                resolved.ra_deg,
                resolved.dec_deg,
                None,
                "input_coordinates",
            )

        # SkyChartTarget normalizes and safety-checks this field before construction.
        assert target.name is not None
        name = target.name
        key = " ".join(name.split()).casefold()
        if builtin := _BUILTIN_COORDINATES.get(key):
            label, ra_deg, dec_deg = builtin
            return ResolvedSkyTarget(label, ra_deg, dec_deg, None, "bundled")
        if key in _KNOWN_SOLAR_SYSTEM_BODY_NAMES:
            resolved = self._target_ref_resolver(
                SolarSystemTargetRef(kind="solar_system", body=key)
            )
            return ResolvedSkyTarget(
                resolved.label,
                resolved.ra_deg,
                resolved.dec_deg,
                key,
                "solar_system",
            )

        resolved = self._external_resolver(name)
        if resolved is None:
            return None
        return ResolvedSkyTarget(
            resolved.canonical_name,
            resolved.ra_deg,
            resolved.dec_deg,
            None,
            "existing_resolver",
        )
