"""Cross-check Day 3 Astropy ephemerides against Skyfield and DE421."""

import argparse
import csv
from pathlib import Path

import skyfield_data
from skyfield.api import Loader, Star, wgs84

from starskill.ephemeris_calculator import calculate_ephemeris
from starskill.schemas import ObservationTask, ResolvedTarget


QUANTITIES = (
    "target_altitude_deg",
    "target_azimuth_deg",
    "sun_altitude_deg",
    "moon_altitude_deg",
    "moon_separation_deg",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tolerance-deg", type=float, default=0.001)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task = ObservationTask.model_validate_json(args.task.read_text(encoding="utf-8"))
    target = ResolvedTarget.model_validate_json(
        args.target.read_text(encoding="utf-8")
    )
    astropy_result = calculate_ephemeris(task, target)
    sample_indexes = (0, len(astropy_result.samples) // 2, len(astropy_result.samples) - 1)
    samples = [astropy_result.samples[index] for index in sample_indexes]

    data_dir = Path(skyfield_data.__file__).parent / "data"
    loader = Loader(str(data_dir))
    timescale = loader.timescale(builtin=True)
    ephemeris = loader("de421.bsp")
    times = timescale.from_datetimes([sample.timestamp_utc for sample in samples])
    observer = ephemeris["earth"] + wgs84.latlon(
        task.observer.latitude,
        task.observer.longitude,
        elevation_m=0.0,
    )
    skyfield_target = Star(
        ra_hours=target.ra_deg / 15.0,
        dec_degrees=target.dec_deg,
    )
    apparent = observer.at(times)
    target_apparent = apparent.observe(skyfield_target).apparent()
    sun_apparent = apparent.observe(ephemeris["sun"]).apparent()
    moon_apparent = apparent.observe(ephemeris["moon"]).apparent()
    target_altitude, target_azimuth, _ = target_apparent.altaz()
    sun_altitude, _, _ = sun_apparent.altaz()
    moon_altitude, _, _ = moon_apparent.altaz()
    moon_separation = target_apparent.separation_from(moon_apparent)

    rows = []
    for offset, sample in enumerate(samples):
        skyfield_values = {
            "target_altitude_deg": target_altitude.degrees[offset],
            "target_azimuth_deg": target_azimuth.degrees[offset],
            "sun_altitude_deg": sun_altitude.degrees[offset],
            "moon_altitude_deg": moon_altitude.degrees[offset],
            "moon_separation_deg": moon_separation.degrees[offset],
        }
        for quantity in QUANTITIES:
            astropy_value = getattr(sample, quantity)
            skyfield_value = skyfield_values[quantity]
            difference = abs(astropy_value - skyfield_value)
            rows.append(
                {
                    "timestamp_utc": sample.timestamp_utc.isoformat(),
                    "quantity": quantity,
                    "astropy_deg": f"{astropy_value:.9f}",
                    "skyfield_deg": f"{skyfield_value:.9f}",
                    "absolute_difference_deg": f"{difference:.9f}",
                    "tolerance_deg": f"{args.tolerance_deg:.6f}",
                    "passed": str(difference <= args.tolerance_deg).lower(),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    max_difference = max(float(row["absolute_difference_deg"]) for row in rows)
    passed = all(row["passed"] == "true" for row in rows)
    print(
        f"checked={len(rows)} max_difference_deg={max_difference:.9f} "
        f"tolerance_deg={args.tolerance_deg:.6f} passed={str(passed).lower()}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
