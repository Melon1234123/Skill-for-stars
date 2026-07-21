"""Calculate a reproducible Moon-Jupiter position relationship."""

import csv
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import astropy
from astropy import units as u
from astropy.config.paths import set_temp_cache
from astropy.coordinates import (
    AltAz,
    EarthLocation,
    get_body,
    solar_system_ephemeris,
)
from astropy.time import Time
from astropy.utils import iers

from starskill.ephemeris_calculator import build_time_grid
from starskill.schemas import (
    SolarSystemRelationshipResult,
    SolarSystemRelationshipSample,
    SolarSystemRelationshipSettings,
    SolarSystemRelationshipTask,
)


RELATIONSHIP_CSV_COLUMNS = (
    "timestamp_local",
    "timestamp_utc",
    "moon_altitude_deg",
    "moon_azimuth_deg",
    "jupiter_altitude_deg",
    "jupiter_azimuth_deg",
    "angular_separation_deg",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def calculate_solar_system_relationship(
    task: SolarSystemRelationshipTask,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> SolarSystemRelationshipResult:
    """Calculate geometric Moon/Jupiter AltAz positions and separation."""
    points = build_time_grid(
        start=task.time_range.start,
        end=task.time_range.end,
        timezone_name=task.observer.timezone,
        interval_minutes=task.interval_minutes,
    )
    with TemporaryDirectory(prefix="starskill-astropy-") as cache_dir:
        with (
            set_temp_cache(cache_dir),
            iers.conf.set_temp("auto_download", False),
            solar_system_ephemeris.set("builtin"),
        ):
            times = Time([point.utc for point in points], scale="utc")
            location = EarthLocation(
                lon=task.observer.longitude * u.deg,
                lat=task.observer.latitude * u.deg,
                height=0 * u.m,
            )
            frame = AltAz(
                obstime=times,
                location=location,
                pressure=0 * u.hPa,
            )
            moon = get_body("moon", times, location=location).transform_to(frame)
            jupiter = get_body("jupiter", times, location=location).transform_to(frame)
            separation = moon.separation(jupiter)

    samples = [
        SolarSystemRelationshipSample(
            timestamp_local=point.local,
            timestamp_utc=point.utc,
            moon_altitude_deg=float(moon.alt[index].to_value(u.deg)),
            moon_azimuth_deg=float(moon.az[index].to_value(u.deg)),
            jupiter_altitude_deg=float(jupiter.alt[index].to_value(u.deg)),
            jupiter_azimuth_deg=float(jupiter.az[index].to_value(u.deg)),
            angular_separation_deg=float(separation[index].to_value(u.deg)),
        )
        for index, point in enumerate(points)
    ]
    return SolarSystemRelationshipResult(
        task=task,
        settings=SolarSystemRelationshipSettings(
            calculated_at=clock(),
            astropy_version=astropy.__version__,
        ),
        samples=samples,
    )


def write_relationship_csv(
    result: SolarSystemRelationshipResult,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RELATIONSHIP_CSV_COLUMNS)
        writer.writeheader()
        for sample in result.samples:
            writer.writerow(
                {
                    "timestamp_local": sample.timestamp_local.isoformat(),
                    "timestamp_utc": sample.timestamp_utc.isoformat(),
                    "moon_altitude_deg": f"{sample.moon_altitude_deg:.3f}",
                    "moon_azimuth_deg": f"{sample.moon_azimuth_deg:.3f}",
                    "jupiter_altitude_deg": f"{sample.jupiter_altitude_deg:.3f}",
                    "jupiter_azimuth_deg": f"{sample.jupiter_azimuth_deg:.3f}",
                    "angular_separation_deg": f"{sample.angular_separation_deg:.3f}",
                }
            )


def write_relationship_json(
    result: SolarSystemRelationshipResult,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
