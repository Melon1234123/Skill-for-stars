"""Structured input models for observation tasks."""

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observer(InputModel):
    location_name: str
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    timezone: str

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana_name(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class TimeRange(InputModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError("end must be later than start")
        return self


class OutputOptions(InputModel):
    language: str = "zh-CN"
    level: str = "classroom"
    formats: list[str] = Field(default_factory=lambda: ["json", "csv", "png", "md"])


class ObservationTask(InputModel):
    task_type: Literal["observation_plan"] = "observation_plan"
    target: str
    observer: Observer
    time_range: TimeRange
    interval_minutes: int = Field(default=10, ge=1, le=120)
    output: OutputOptions = Field(default_factory=OutputOptions)

    @field_validator("target")
    @classmethod
    def target_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target must not be blank")
        return value


class TargetSource(InputModel):
    database: Literal["SIMBAD"]
    service_url: str
    accessed_at: datetime
    from_cache: bool


class ResolvedTarget(InputModel):
    input_name: str
    query_name: str
    canonical_name: str
    ra_deg: float = Field(ge=0, lt=360)
    dec_deg: float = Field(ge=-90, le=90)
    object_type: str
    aliases: list[str]
    coordinate_frame: Literal["ICRS"] = "ICRS"
    source: TargetSource


class EphemerisSample(InputModel):
    timestamp_local: datetime
    timestamp_utc: datetime
    target_altitude_deg: float = Field(ge=-90, le=90)
    target_azimuth_deg: float = Field(ge=0, lt=360)
    sun_altitude_deg: float = Field(ge=-90, le=90)
    moon_altitude_deg: float = Field(ge=-90, le=90)
    moon_separation_deg: float = Field(ge=0, le=180)

    @field_validator("timestamp_local", "timestamp_utc")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone offset")
        return value

    @field_validator("timestamp_utc")
    @classmethod
    def utc_timestamp_must_use_zero_offset(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("timestamp_utc must use UTC offset +00:00")
        return value


class EphemerisSettings(InputModel):
    calculated_at: datetime
    astropy_version: str
    time_scale: Literal["UTC"] = "UTC"
    horizontal_frame: Literal["AltAz"] = "AltAz"
    atmospheric_refraction: bool = False
    iers_auto_download: bool = False


class EphemerisResult(InputModel):
    target: ResolvedTarget
    observer: Observer
    interval_minutes: int = Field(ge=1)
    settings: EphemerisSettings
    samples: list[EphemerisSample] = Field(min_length=1)


VisibilityRejectionReason = Literal[
    "target_below_minimum_altitude",
    "sun_above_maximum_altitude",
]


class VisibilityCriteria(InputModel):
    min_target_altitude_deg: float = Field(default=30.0, ge=-90, le=90)
    max_sun_altitude_deg: float = Field(default=-12.0, ge=-90, le=90)


class VisibilitySample(EphemerisSample):
    moon_illumination_fraction: float = Field(ge=0, le=1)
    is_observable: bool
    rejection_reasons: list[VisibilityRejectionReason]


class ObservationWindow(InputModel):
    start_local: datetime
    end_local: datetime
    start_utc: datetime
    end_utc: datetime
    sample_count: int = Field(ge=1)
    peak_target_altitude_deg: float = Field(ge=-90, le=90)


class ObservationPlanResult(InputModel):
    target: ResolvedTarget
    observer: Observer
    interval_minutes: int = Field(ge=1)
    source_ephemeris_settings: EphemerisSettings
    criteria: VisibilityCriteria
    samples: list[VisibilitySample] = Field(min_length=1)
    windows: list[ObservationWindow]


class PipelineIssue(InputModel):
    stage: str
    code: str
    message: str


class ArtifactRecord(InputModel):
    path: str
    bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PipelineManifest(InputModel):
    run_id: str
    status: Literal["success", "degraded", "failed"]
    started_at: datetime
    completed_at: datetime
    input_task: ObservationTask
    cache_hit: bool
    target_source: TargetSource | None
    dependencies: dict[str, str]
    artifacts: list[ArtifactRecord]
    issues: list[PipelineIssue]


class PipelineOutcome(InputModel):
    status: Literal["success", "degraded", "failed"]
    output_dir: str
    manifest: PipelineManifest


class SolarSystemRelationshipTask(InputModel):
    task_type: Literal["solar_system_relationship"] = "solar_system_relationship"
    targets: list[Literal["moon", "jupiter"]]
    observer: Observer
    time_range: TimeRange
    interval_minutes: int = Field(default=20, ge=1, le=120)

    @model_validator(mode="after")
    def require_moon_and_jupiter(self) -> "SolarSystemRelationshipTask":
        if self.targets != ["moon", "jupiter"]:
            raise ValueError("targets must be exactly ['moon', 'jupiter']")
        return self


class SolarSystemRelationshipSettings(InputModel):
    calculated_at: datetime
    astropy_version: str
    time_scale: Literal["UTC"] = "UTC"
    horizontal_frame: Literal["AltAz"] = "AltAz"
    solar_system_ephemeris: Literal["builtin"] = "builtin"
    atmospheric_refraction: bool = False
    iers_auto_download: bool = False


class SolarSystemRelationshipSample(InputModel):
    timestamp_local: datetime
    timestamp_utc: datetime
    moon_altitude_deg: float = Field(ge=-90, le=90)
    moon_azimuth_deg: float = Field(ge=0, lt=360)
    jupiter_altitude_deg: float = Field(ge=-90, le=90)
    jupiter_azimuth_deg: float = Field(ge=0, lt=360)
    angular_separation_deg: float = Field(ge=0, le=180)


class SolarSystemRelationshipResult(InputModel):
    task: SolarSystemRelationshipTask
    settings: SolarSystemRelationshipSettings
    samples: list[SolarSystemRelationshipSample] = Field(min_length=1)


class SDSSImageRequest(InputModel):
    target_name: Literal["M51"] = "M51"
    data_release: Literal["DR18"] = "DR18"
    ra_deg: float = Field(default=202.4696, ge=0, lt=360)
    dec_deg: float = Field(default=47.1952, ge=-90, le=90)
    scale_arcsec_per_pixel: float = Field(default=0.396, gt=0, le=10)
    width: int = Field(default=512, ge=64, le=1024)
    height: int = Field(default=512, ge=64, le=1024)
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_bytes: int = Field(default=5_000_000, ge=1, le=20_000_000)


class SDSSImageSource(InputModel):
    database: Literal["SDSS SkyServer"] = "SDSS SkyServer"
    data_release: Literal["DR18"] = "DR18"
    endpoint: str
    source_url: str
    accessed_at: datetime
    from_cache: bool
    authentication: Literal["none"] = "none"
    query_parameters: dict[str, str | int | float]
    expected_count: int = 1
    retrieved_count: int = 1
    local_filters: list[str] = Field(default_factory=list)
    content_type: str
    bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pixel_scale_arcsec: float = Field(gt=0)
    wavebands: list[str]
    license_notice: str


class PublicImageResult(InputModel):
    request: SDSSImageRequest
    source: SDSSImageSource
    source_path: str
    display_path: str
    processing_steps: list[str]


ExternalAvailability = Literal["fresh", "cached", "unavailable", "stale"]


class ExternalSource(InputModel):
    provider: str
    source_url: str | None = None
    accessed_at: datetime
    from_cache: bool
    availability: ExternalAvailability
    issue_code: str | None = None


class ObservingConditionsRequest(InputModel):
    observer: Observer
    time_range: TimeRange


class WeatherSample(InputModel):
    timestamp_local: datetime
    cloud_cover_percent: float | None = Field(default=None, ge=0, le=100)
    precipitation_mm: float | None = Field(default=None, ge=0)
    wind_speed_kmh: float | None = Field(default=None, ge=0)
    visibility_m: float | None = Field(default=None, ge=0)


class WeatherForecast(InputModel):
    samples: list[WeatherSample]
    source: ExternalSource


class LightPollutionResult(InputModel):
    radiance: float | None = Field(default=None, ge=0)
    unit: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    sample_period: str | None = None
    spatial_resolution: str | None = None
    interpolation: str | None = None
    source: ExternalSource


class NasaFeature(InputModel):
    date: str | None = None
    title: str | None = None
    media_type: str | None = None
    media_url: str | None = None
    explanation: str | None = None
    copyright: str | None = None
    source: ExternalSource


class TonightRecommendationRequest(InputModel):
    task: ObservationTask
    min_target_altitude_deg: float = Field(default=30.0, ge=-90, le=90)
    max_sun_altitude_deg: float = Field(default=-12.0, ge=-90, le=90)


class RecommendationWindow(InputModel):
    start_local: datetime
    end_local: datetime
    grade: Literal["recommended", "caution", "not_recommended"]
    reasons: list[str] = Field(min_length=1)


class TonightRecommendationResult(InputModel):
    geometry: ObservationPlanResult
    weather_forecast: WeatherForecast
    light_pollution: LightPollutionResult
    recommendations: list[RecommendationWindow]
    human_review: list[str] = Field(min_length=1)
    provenance: list[ExternalSource]


class StellariumSyncRequest(InputModel):
    observer: Observer
    timestamp: datetime
    target: str
