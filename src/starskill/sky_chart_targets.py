"""Narrow target-resolution adapter for the local sky-chart service."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Literal

from starskill.schemas import ResolvedTarget, SkyChartTarget


_BUILTIN_COORDINATES = MappingProxyType(
    {
        "m42": ("M42", 83.822083, -5.391111),
        "m 42": ("M42", 83.822083, -5.391111),
    }
)
_SOLAR_SYSTEM_BODIES = MappingProxyType(
    {
        "sun": ("Sun", "sun"),
        "moon": ("Moon", "moon"),
        "mercury": ("Mercury", "mercury"),
        "venus": ("Venus", "venus"),
        "mars": ("Mars", "mars"),
        "jupiter": ("Jupiter", "jupiter"),
        "saturn": ("Saturn", "saturn"),
        "uranus": ("Uranus", "uranus"),
        "neptune": ("Neptune", "neptune"),
    }
)


@dataclass(frozen=True)
class ResolvedSkyTarget:
    label: str
    ra_deg: float | None
    dec_deg: float | None
    solar_system_body: str | None
    source: Literal["input_coordinates", "bundled", "solar_system", "existing_resolver"]


class SkyChartTargetResolver:
    """Resolve only validated names through an injected existing resolver."""

    def __init__(self, external_resolver: Callable[[str], ResolvedTarget | None]) -> None:
        self._external_resolver = external_resolver

    def resolve(self, target: SkyChartTarget) -> ResolvedSkyTarget | None:
        if target.mode == "coordinates":
            return ResolvedSkyTarget(
                "RA/Dec target",
                target.ra_deg,
                target.dec_deg,
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
        if body := _SOLAR_SYSTEM_BODIES.get(key):
            label, solar_system_body = body
            return ResolvedSkyTarget(label, None, None, solar_system_body, "solar_system")

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
