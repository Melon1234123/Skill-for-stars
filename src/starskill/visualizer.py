"""Create deterministic, non-interactive observation-planning charts."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)

from matplotlib import dates as mdates  # noqa: E402
from matplotlib import pyplot as plt  # noqa: E402

from starskill.schemas import ObservationPlanResult


def plot_visibility(plan: ObservationPlanResult, output_path: Path) -> None:
    """Plot altitude evidence, thresholds, twilight, and candidate windows."""
    times = [sample.timestamp_local for sample in plan.samples]
    target_altitudes = [sample.target_altitude_deg for sample in plan.samples]
    sun_altitudes = [sample.sun_altitude_deg for sample in plan.samples]
    moon_altitudes = [sample.moon_altitude_deg for sample in plan.samples]
    twilight = [
        sample.sun_altitude_deg > plan.criteria.max_sun_altitude_deg
        for sample in plan.samples
    ]

    figure, axis = plt.subplots(
        figsize=(12, 6),
        constrained_layout=True,
        facecolor="white",
    )
    try:
        axis.fill_between(
            times,
            -90,
            90,
            where=twilight,
            color="#f4a261",
            alpha=0.16,
            label="Sun above twilight limit",
        )
        for index, window in enumerate(plan.windows):
            axis.axvspan(
                window.start_local,
                window.end_local,
                color="#2a9d8f",
                alpha=0.18,
                label="Candidate window" if index == 0 else None,
            )

        axis.plot(
            times,
            target_altitudes,
            color="#1f77b4",
            linewidth=2.2,
            label=plan.target.canonical_name,
        )
        axis.plot(
            times,
            sun_altitudes,
            color="#e76f51",
            linewidth=1.8,
            label="Sun",
        )
        axis.plot(
            times,
            moon_altitudes,
            color="#6c757d",
            linewidth=1.8,
            label="Moon",
        )
        axis.axhline(
            plan.criteria.min_target_altitude_deg,
            color="#1f77b4",
            linestyle="--",
            linewidth=1.2,
            label=f"Target limit ({plan.criteria.min_target_altitude_deg:g} deg)",
        )
        axis.axhline(
            plan.criteria.max_sun_altitude_deg,
            color="#e76f51",
            linestyle="--",
            linewidth=1.2,
            label=f"Twilight limit ({plan.criteria.max_sun_altitude_deg:g} deg)",
        )

        locator = mdates.AutoDateLocator(minticks=5, maxticks=9)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(
                locator,
                tz=plan.samples[0].timestamp_local.tzinfo,
            )
        )
        axis.set_title(f"{plan.target.canonical_name} visibility planning")
        axis.set_xlabel(f"Local time ({plan.observer.timezone})")
        axis.set_ylabel("Altitude (deg)")
        axis.set_ylim(-90, 90)
        axis.grid(True, color="#d9d9d9", linewidth=0.8, alpha=0.7)
        axis.legend(loc="upper right", ncols=2, frameon=True)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, dpi=150, facecolor="white")
    finally:
        plt.close(figure)
