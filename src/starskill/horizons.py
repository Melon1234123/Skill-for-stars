"""Opt-in bounded JPL Horizons apparent-position provider for small bodies."""

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from astropy.time import Time

from starskill.external_data import (
    ExternalDataError,
    JsonBackend,
    read_cache_record,
    write_cache_record,
)
from starskill.schemas import (
    AstronomicalTargetSource,
    HorizonsQueryRecord,
    HorizonsTargetRef,
    Observer,
    ResolvedAstronomicalTarget,
)
from starskill.target_resolver import (
    TargetNotFoundError,
    TargetResolutionError,
    TargetServiceError,
    utc_now,
)


HORIZONS_ENDPOINT = "https://ssd.jpl.nasa.gov/api/horizons.api"
HORIZONS_TIMEOUT_SECONDS = 30
HORIZONS_MAX_BYTES = 2_000_000
HORIZONS_CACHE_TTL = timedelta(hours=24)


class HorizonsBodyNotFoundError(TargetNotFoundError):
    code = "horizons_body_not_found"


class HorizonsAmbiguousBodyError(TargetResolutionError):
    code = "horizons_ambiguous_body"


class HorizonsServiceError(TargetServiceError):
    code = "horizons_service_error"


class HorizonsResponseError(TargetServiceError):
    code = "horizons_invalid_response"


def resolve_horizons_target(
    target: HorizonsTargetRef,
    *,
    utc_times: Sequence[datetime],
    observer: Observer,
    backend: JsonBackend | None,
    cache_dir: Path | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> tuple[ResolvedAstronomicalTarget, list[tuple[float, float]]]:
    """Sample apparent airless AltAz positions for one small body at each time."""
    if backend is None:
        raise HorizonsServiceError(
            "horizons target resolution requires a horizons backend"
        )
    now = clock()
    query_parameters = _build_query_parameters(target.body, utc_times, observer)
    source_url = f"{HORIZONS_ENDPOINT}?{urlencode(query_parameters)}"
    cache_path = (
        cache_dir / "horizons" / f"{sha256(source_url.encode('utf-8')).hexdigest()}.json"
        if cache_dir is not None
        else None
    )
    payload = (
        read_cache_record(cache_path, now, HORIZONS_CACHE_TTL)
        if cache_path is not None
        else None
    )
    from_cache = payload is not None
    if payload is None:
        try:
            payload = backend.fetch_json(
                source_url,
                timeout_seconds=HORIZONS_TIMEOUT_SECONDS,
                max_bytes=HORIZONS_MAX_BYTES,
            )
        except ExternalDataError as exc:
            raise HorizonsServiceError(
                f"JPL Horizons query failed: {exc.code}"
            ) from exc
    label, positions = _parse_observer_table(payload, target.body, len(utc_times))
    if cache_path is not None and not from_cache:
        write_cache_record(cache_path, payload, now)
    resolved = ResolvedAstronomicalTarget(
        label=label,
        kind="horizons",
        motion="dynamic",
        source=AstronomicalTargetSource(
            provider="jpl_horizons",
            from_cache=from_cache,
            accessed_at=now,
        ),
        horizons_query=HorizonsQueryRecord(
            endpoint=HORIZONS_ENDPOINT,
            query_parameters=query_parameters,
            accessed_at=now,
            from_cache=from_cache,
        ),
    )
    return resolved, positions


def _build_query_parameters(
    body: str,
    utc_times: Sequence[datetime],
    observer: Observer,
) -> dict[str, str]:
    julian_days = Time(list(utc_times), scale="utc").jd
    return {
        "format": "json",
        "COMMAND": f"'{body};'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@399'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{observer.longitude:.6f},{observer.latitude:.6f},0'",
        "TLIST_TYPE": "'JD'",
        "TLIST": "'" + " ".join(f"{value:.9f}" for value in julian_days) + "'",
        "QUANTITIES": "'4'",
        "APPARENT": "'AIRLESS'",
        "CSV_FORMAT": "'YES'",
    }


def _parse_observer_table(
    payload: dict[str, Any],
    body: str,
    expected_count: int,
) -> tuple[str, list[tuple[float, float]]]:
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        raise HorizonsServiceError(
            f"JPL Horizons reported an error: {error.strip()[:200]}"
        )
    result = payload.get("result")
    if not isinstance(result, str):
        raise HorizonsResponseError("JPL Horizons response is missing its result text")
    if "No matches found" in result:
        raise HorizonsBodyNotFoundError(f"JPL Horizons found no body matching: {body}")
    if "Matching small-bodies" in result or "Multiple major-bodies match" in result:
        raise HorizonsAmbiguousBodyError(
            f"JPL Horizons matched multiple bodies for: {body};"
            " use a unique designation or record number"
        )

    label = body
    for line in result.splitlines():
        stripped = line.strip()
        if stripped.startswith("Target body name:"):
            label = stripped.removeprefix("Target body name:").split("{")[0].strip() or body
            break

    table_start = result.find("$$SOE")
    table_end = result.find("$$EOE")
    if table_start == -1 or table_end == -1 or table_end <= table_start:
        raise HorizonsResponseError("JPL Horizons response contains no ephemeris table")

    positions: list[tuple[float, float]] = []
    for line in result[table_start + len("$$SOE"):table_end].splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",")]
        if fields and fields[-1] == "":
            fields.pop()
        try:
            azimuth = float(fields[-2])
            altitude = float(fields[-1])
        except (IndexError, ValueError) as exc:
            raise HorizonsResponseError(
                "JPL Horizons ephemeris row is not a numeric azimuth/elevation pair"
            ) from exc
        azimuth %= 360.0
        if not -90.0 <= altitude <= 90.0:
            raise HorizonsResponseError(
                "JPL Horizons elevation is outside the valid -90..90 degree range"
            )
        positions.append((azimuth, altitude))

    if len(positions) != expected_count:
        raise HorizonsResponseError(
            f"JPL Horizons returned {len(positions)} ephemeris rows"
            f" for {expected_count} sample times"
        )
    return label, positions
