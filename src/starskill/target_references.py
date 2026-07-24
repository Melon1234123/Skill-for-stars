"""Resolve typed astronomical target references through their appropriate source."""

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from starskill.schemas import (
    AstronomicalTargetSource,
    CoordinateTargetRef,
    ResolvedAstronomicalTarget,
    SimbadTargetRef,
    SolarSystemTargetRef,
    TargetRef,
)
from starskill.target_resolver import (
    TargetBackend,
    TargetResolutionError,
    TargetServiceError,
    resolve_target,
    utc_now,
)


SUPPORTED_SOLAR_SYSTEM_BODIES: Mapping[str, str] = MappingProxyType(
    {
        "sun": "Sun",
        "moon": "Moon",
        "mercury": "Mercury",
        "venus": "Venus",
        "mars": "Mars",
        "jupiter": "Jupiter",
        "saturn": "Saturn",
        "uranus": "Uranus",
        "neptune": "Neptune",
    }
)


class UnsupportedSolarSystemBodyError(TargetResolutionError):
    code = "unsupported_solar_system_body"


def resolve_target_ref(
    target: TargetRef,
    *,
    backend: TargetBackend | None = None,
    cache_dir: Path | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> ResolvedAstronomicalTarget:
    """Resolve one typed target without changing its dynamic or fixed semantics."""
    if isinstance(target, SolarSystemTargetRef):
        label = SUPPORTED_SOLAR_SYSTEM_BODIES.get(target.body)
        if label is None:
            raise UnsupportedSolarSystemBodyError(
                f"builtin ephemeris does not support: {target.body}"
            )
        return ResolvedAstronomicalTarget(
            label=label,
            kind=target.kind,
            motion="dynamic",
            source=AstronomicalTargetSource(
                provider="astropy_builtin_ephemeris",
                from_cache=False,
                accessed_at=clock(),
            ),
        )

    if isinstance(target, CoordinateTargetRef):
        return ResolvedAstronomicalTarget(
            label=target.label,
            kind=target.kind,
            motion="fixed_icrs",
            ra_deg=target.ra_deg,
            dec_deg=target.dec_deg,
            source=AstronomicalTargetSource(
                provider="user_coordinates",
                from_cache=False,
                accessed_at=clock(),
            ),
        )

    assert isinstance(target, SimbadTargetRef)
    if backend is None:
        raise TargetServiceError("SIMBAD target resolution requires a target backend")
    catalog_target = resolve_target(
        target.name,
        backend=backend,
        cache_dir=cache_dir,
        clock=clock,
    )
    return ResolvedAstronomicalTarget(
        label=catalog_target.canonical_name,
        kind=target.kind,
        motion="fixed_icrs",
        ra_deg=catalog_target.ra_deg,
        dec_deg=catalog_target.dec_deg,
        source=AstronomicalTargetSource(
            provider="simbad_cache" if catalog_target.source.from_cache else "simbad",
            from_cache=catalog_target.source.from_cache,
            accessed_at=catalog_target.source.accessed_at,
        ),
        catalog_target=catalog_target,
    )
