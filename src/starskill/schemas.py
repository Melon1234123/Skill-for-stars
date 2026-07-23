"""Structured input models for observation tasks."""

from datetime import datetime, timedelta, timezone
import re
from typing import Literal
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


_SKY_CHART_COORDINATE_JSON_PATTERN = re.compile(
    r'("(?:longitude|latitude|ra_deg|dec_deg|altitude_deg|azimuth_deg)"\s*:\s*)'
    r'(-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)(?=\s*[,}])'
)


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


class SkyChartObserver(InputModel):
    """Observer input dedicated to the local, deterministic sky chart."""

    location_name: str = Field(default="北京", min_length=1, max_length=80)
    longitude: float = Field(default=116.4074, ge=-180, le=180, allow_inf_nan=False)
    latitude: float = Field(default=39.9042, ge=-90, le=90, allow_inf_nan=False)
    timezone: str = "Asia/Shanghai"

    @field_validator("location_name")
    @classmethod
    def normalize_location_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(character) < 32 for character in value):
            raise ValueError("location_name must contain 1..80 visible characters")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return Observer(location_name="x", longitude=0, latitude=0, timezone=value).timezone

    @field_serializer("longitude", "latitude", when_used="json")
    def serialize_six_decimal_coordinate(self, value: float) -> float:
        return round(value, 6)


class SkyChartTarget(InputModel):
    """Mutually exclusive target-name or ICRS-coordinate input."""

    mode: Literal["name", "coordinates"] = "name"
    name: str | None = "M42"
    ra_deg: float | None = Field(default=None, allow_inf_nan=False)
    dec_deg: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def remove_name_default_for_coordinate_input(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("mode") == "coordinates" and "name" not in value:
            return {**value, "name": None}
        return value

    @model_validator(mode="after")
    def enforce_target_mode(self) -> "SkyChartTarget":
        if self.mode == "name":
            if self.ra_deg is not None or self.dec_deg is not None or not self.name:
                raise ValueError("name target requires only a visible 1..120 character name")
            if any(
                unicodedata.category(character) in {"Cc", "Cf"}
                for character in self.name
            ):
                raise ValueError("name target requires only a safe visible 1..120 character name")
            name = self.name.strip()
            if (
                not name
                or len(name) > 120
                or any(
                    character in name
                    for character in ":/?#&%\\\"';|<>`$(){}[]*!~"
                )
            ):
                raise ValueError("name target requires only a safe visible 1..120 character name")
            self.name = name
        elif (
            self.name is not None
            or self.ra_deg is None
            or self.dec_deg is None
            or not 0 <= self.ra_deg < 360
            or not -90 <= self.dec_deg <= 90
        ):
            raise ValueError("coordinates target requires only ra_deg and dec_deg")
        return self


class SkyChartRequest(InputModel):
    """All and only client-controlled sky-chart inputs."""

    observer: SkyChartObserver = Field(default_factory=SkyChartObserver)
    timestamp_local: datetime
    target: SkyChartTarget = Field(default_factory=SkyChartTarget)
    catalog_mode: Literal["auto", "bundled", "full"] = "auto"

    @field_validator("timestamp_local")
    @classmethod
    def require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_local must include a timezone offset")
        return value

    @model_validator(mode="after")
    def require_matching_zone_offset(self) -> "SkyChartRequest":
        zone_offset = self.timestamp_local.astimezone(
            ZoneInfo(self.observer.timezone)
        ).utcoffset()
        if self.timestamp_local.utcoffset() != zone_offset:
            raise ValueError("timestamp_local offset must match observer timezone")
        return self


_SKY_CHART_RENDER_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_SKY_CHART_LAYER_ORDER = [
    "background",
    "horizon_grid",
    "constellations",
    "stars",
    "moon",
    "planets",
    "target",
    "footer",
]


class SkyChartRenderResponse(InputModel):
    render_id: str = Field(pattern=_SKY_CHART_RENDER_ID_PATTERN)
    png_url: str
    json_url: str
    catalog_mode_used: Literal["bundled", "full"]
    catalog_status: Literal["available", "degraded"]
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_same_origin_render_urls(self) -> "SkyChartRenderResponse":
        base = f"/v1/sky-chart/renders/{self.render_id}"
        if self.png_url != f"{base}.png" or self.json_url != f"{base}.json":
            raise ValueError("render URLs must be same-origin URLs for render_id")
        return self


class SkyChartIcrsCoordinates(InputModel):
    ra_deg: float = Field(ge=0, lt=360, allow_inf_nan=False)
    dec_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)

    @field_serializer("ra_deg", "dec_deg", when_used="json")
    def serialize_six_decimal_coordinate(self, value: float) -> float:
        return round(value, 6)


class SkyChartAltAzCoordinates(InputModel):
    altitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    azimuth_deg: float = Field(ge=0, lt=360, allow_inf_nan=False)

    @field_serializer("altitude_deg", "azimuth_deg", when_used="json")
    def serialize_six_decimal_coordinate(self, value: float) -> float:
        return round(value, 6)


class SkyChartObject(InputModel):
    label: str = Field(min_length=1, max_length=120)
    icrs: SkyChartIcrsCoordinates | None
    altaz: SkyChartAltAzCoordinates
    visible: bool
    drawn: bool
    illumination_fraction: float | None = Field(default=None, ge=0, le=1)


class SkyChartExportTarget(InputModel):
    mode: Literal["name", "coordinates"]
    input: str = Field(min_length=1, max_length=120)
    resolved: SkyChartObject | None


class SkyChartExportRequest(InputModel):
    observer: SkyChartObserver
    timestamp_local: datetime
    timestamp_utc: datetime
    target: SkyChartExportTarget
    catalog_mode_requested: Literal["auto", "bundled", "full"]
    catalog_mode_used: Literal["bundled", "full"]

    @field_validator("timestamp_local")
    @classmethod
    def timestamp_local_must_include_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp_local must include a timezone offset")
        return value

    @field_validator("timestamp_utc")
    @classmethod
    def timestamp_utc_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timestamp_utc must use UTC offset")
        return value

    @field_serializer("timestamp_utc", when_used="json")
    def serialize_timestamp_utc(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @model_validator(mode="after")
    def timestamps_must_describe_one_instant(self) -> "SkyChartExportRequest":
        if self.timestamp_local.astimezone(timezone.utc) != self.timestamp_utc:
            raise ValueError("local and UTC timestamps must describe the same instant")
        zone_offset = self.timestamp_local.astimezone(
            ZoneInfo(self.observer.timezone)
        ).utcoffset()
        if self.timestamp_local.utcoffset() != zone_offset:
            raise ValueError("timestamp_local offset must match observer timezone")
        return self


class SkyChartRenderMetadata(InputModel):
    projection: Literal["azimuthal_equidistant_zenith"]
    width_px: Literal[1200]
    height_px: Literal[900]
    layer_order: list[
        Literal[
            "background",
            "horizon_grid",
            "constellations",
            "stars",
            "moon",
            "planets",
            "target",
            "footer",
        ]
    ]
    png_sha256: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def require_canonical_layer_order(self) -> "SkyChartRenderMetadata":
        if self.layer_order != _SKY_CHART_LAYER_ORDER:
            raise ValueError("layer_order must use the canonical sky-chart order")
        return self


class SkyChartObjectsMetadata(InputModel):
    moon: SkyChartObject
    planets: list[SkyChartObject]
    target: SkyChartObject | None
    stars_drawn: int = Field(ge=0)
    constellation_segments_drawn: int = Field(ge=0)


class SkyChartCatalogMetadata(InputModel):
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    license: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    status: Literal["available", "degraded"]


class SkyChartCalculationMetadata(InputModel):
    time_scale: Literal["UTC"] = "UTC"
    horizontal_frame: Literal["AltAz"] = "AltAz"
    atmospheric_refraction: Literal[False] = False
    solar_system_ephemeris: Literal["builtin"] = "builtin"
    iers_auto_download: Literal[False] = False


class SkyChartDependenciesMetadata(InputModel):
    python: str = Field(min_length=1)
    astropy: str = Field(min_length=1)
    matplotlib: str = Field(min_length=1)
    tzdata: str = Field(min_length=1)


class SkyChartExportMetadata(InputModel):
    """The complete, non-sensitive JSON export for one rendered PNG."""

    schema_version: Literal["1.0"] = "1.0"
    render_id: str = Field(pattern=_SKY_CHART_RENDER_ID_PATTERN)
    created_at_utc: datetime
    request: SkyChartExportRequest
    render: SkyChartRenderMetadata
    objects: SkyChartObjectsMetadata
    catalog: SkyChartCatalogMetadata
    calculation: SkyChartCalculationMetadata
    dependencies: SkyChartDependenciesMetadata
    warnings: list[str] = Field(default_factory=list)

    @field_validator("created_at_utc")
    @classmethod
    def created_at_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("created_at_utc must use UTC offset")
        return value

    @field_serializer("created_at_utc", when_used="json")
    def serialize_created_at_utc(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def model_dump_json(self, **kwargs: object) -> str:
        """Serialize export coordinates as six-place JSON numbers, never strings."""
        serialized = super().model_dump_json(**kwargs)
        return _SKY_CHART_COORDINATE_JSON_PATTERN.sub(
            lambda match: f"{match.group(1)}{float(match.group(2)):.6f}",
            serialized,
        )


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
