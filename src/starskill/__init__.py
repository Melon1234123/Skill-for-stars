"""StarSkill astronomy training package."""

from starskill.ephemeris_calculator import (
    build_time_grid,
    calculate_ephemeris,
    write_ephemeris_csv,
    write_ephemeris_json,
)
from starskill.observation_planner import (
    calculate_moon_illumination,
    plan_observation,
    write_observation_plan_json,
    write_visibility_csv,
)
from starskill.pipeline import run_pipeline
from starskill.public_data_fetcher import (
    fetch_sdss_image,
    write_public_image_metadata,
)
from starskill.solar_system_relationship import (
    calculate_solar_system_relationship,
    write_relationship_csv,
    write_relationship_json,
)
from starskill.schemas import ObservationTask
from starskill.target_resolver import normalize_target_name
from starskill.visualizer import plot_visibility

__all__ = [
    "ObservationTask",
    "build_time_grid",
    "calculate_moon_illumination",
    "calculate_solar_system_relationship",
    "fetch_sdss_image",
    "calculate_ephemeris",
    "normalize_target_name",
    "plan_observation",
    "plot_visibility",
    "run_pipeline",
    "write_ephemeris_csv",
    "write_ephemeris_json",
    "write_observation_plan_json",
    "write_public_image_metadata",
    "write_relationship_csv",
    "write_relationship_json",
    "write_visibility_csv",
]
