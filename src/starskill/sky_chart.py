"""Deterministic, local sky-chart rendering and bounded in-memory exports."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata as importlib_metadata
import math
import platform
import re
import secrets
import struct
import threading
import warnings
import zlib
from typing import Callable, Iterator, Protocol, Sequence

from astropy import units as u
from astropy.coordinates import (
    AltAz,
    EarthLocation,
    SkyCoord,
    get_body,
    solar_system_ephemeris,
)
from astropy.time import Time
from astropy.utils import iers
import astropy
import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Wedge
import numpy as np

from starskill.schemas import (
    SkyChartAltAzCoordinates,
    SkyChartCalculationMetadata,
    SkyChartCatalogMetadata,
    SkyChartDependenciesMetadata,
    SkyChartExportMetadata,
    SkyChartExportRequest,
    SkyChartExportTarget,
    SkyChartIcrsCoordinates,
    SkyChartObject,
    SkyChartObjectsMetadata,
    SkyChartRenderMetadata,
    SkyChartRequest,
)
from starskill.sky_chart_catalog import (
    BundledCatalog,
    CatalogSelection,
    CatalogStar,
    ConstellationSegment,
    FullCatalog,
    load_bundled_catalog,
    select_catalog,
)
from starskill.sky_chart_targets import ResolvedSkyTarget, SkyChartTargetResolver
from starskill.target_resolver import (
    InvalidTargetNameError,
    TargetNotFoundError,
    TargetServiceError,
)


CANVAS_WIDTH_PX = 1200
CANVAS_HEIGHT_PX = 900
CANVAS_DPI = 100
LAYER_ORDER = [
    "background",
    "horizon_grid",
    "constellations",
    "stars",
    "moon",
    "planets",
    "target",
    "footer",
]
PLANETS = (
    ("mercury", "Mercury / 水星", "#b8aaa0"),
    ("venus", "Venus / 金星", "#f2d28b"),
    ("mars", "Mars / 火星", "#d96c4b"),
    ("jupiter", "Jupiter / 木星", "#d7bd9a"),
    ("saturn", "Saturn / 土星", "#d8c486"),
    ("uranus", "Uranus / 天王星", "#86d4d8"),
    ("neptune", "Neptune / 海王星", "#6688d8"),
)
_RENDER_ID_RE = re.compile(r"[A-Za-z0-9_-]{32}\Z")


class _FullCatalogCache(Protocol):
    def load_valid(self) -> FullCatalog | None: ...


class _EmptyFullCatalogCache:
    def load_valid(self) -> None:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def project_altaz(altitude_deg: float, azimuth_deg: float) -> tuple[float, float]:
    radius = (90.0 - altitude_deg) / 90.0
    azimuth_rad = np.deg2rad(azimuth_deg)
    return (
        float(radius * np.sin(azimuth_rad)),
        float(radius * np.cos(azimuth_rad)),
    )


def sort_stars_dim_to_bright(stars: Sequence[CatalogStar]) -> tuple[CatalogStar, ...]:
    """Return a stable painter's order with bright stars drawn last."""
    return tuple(sorted(stars, key=lambda star: (-star.magnitude, star.star_id)))


@contextmanager
def deterministic_astropy_matplotlib() -> Iterator[None]:
    old_iers = iers.conf.auto_download
    old_rc = matplotlib.rcParams.copy()
    old_random_state = np.random.get_state()
    iers.conf.auto_download = False
    matplotlib.rcParams.update(
        {
            "figure.dpi": CANVAS_DPI,
            "savefig.dpi": CANVAS_DPI,
            "font.family": "DejaVu Sans",
            "figure.facecolor": "#000000",
            "savefig.facecolor": "#000000",
            "savefig.transparent": False,
        }
    )
    np.random.seed(0)
    try:
        with solar_system_ephemeris.set("builtin"):
            yield
    finally:
        np.random.set_state(old_random_state)
        iers.conf.auto_download = old_iers
        matplotlib.rcParams.update(old_rc)


@dataclass(frozen=True)
class RenderedSkyChart:
    png_bytes: bytes
    metadata: SkyChartExportMetadata
    catalog_mode_used: str
    catalog_status: str
    metadata_json_bytes: bytes


@dataclass(frozen=True)
class _RenderContext:
    time_utc: Time
    timestamp_utc: datetime
    location: EarthLocation
    frame: AltAz
    dependencies: SkyChartDependenciesMetadata


@dataclass(frozen=True)
class _StoreRecord:
    expires_at: float
    insertion_order: int
    png_bytes: bytes
    metadata_json_bytes: bytes

    @property
    def byte_size(self) -> int:
        return len(self.png_bytes) + len(self.metadata_json_bytes)


class SkyChartRenderer:
    """Render a request using one frozen coordinate and dependency context."""

    def __init__(self, *, utc_clock: Callable[[], datetime] = utc_now) -> None:
        self._utc_clock = utc_clock

    def render(
        self,
        request: SkyChartRequest,
        selection: CatalogSelection,
        resolved_target: ResolvedSkyTarget | None,
    ) -> RenderedSkyChart:
        created_at = self._utc_clock().astimezone(timezone.utc)
        with deterministic_astropy_matplotlib():
            context = self._make_context(request)
            star_horizontal = self._star_horizontal(selection.catalog.stars, context)
            star_altaz = {
                star.star_id: (float(horizontal.alt.deg), float(horizontal.az.deg))
                for star, horizontal in zip(selection.catalog.stars, star_horizontal, strict=True)
            }
            if selection.constellation_stars == selection.catalog.stars:
                constellation_altaz = star_altaz
            else:
                constellation_horizontal = self._star_horizontal(
                    selection.constellation_stars, context
                )
                constellation_altaz = {
                    star.star_id: (float(horizontal.alt.deg), float(horizontal.az.deg))
                    for star, horizontal in zip(
                        selection.constellation_stars,
                        constellation_horizontal,
                        strict=True,
                    )
                }
            moon_coord = get_body("moon", context.time_utc, context.location)
            sun_coord = get_body("sun", context.time_utc, context.location)
            moon = self._body_metadata(
                "Moon / 月球",
                moon_coord,
                context,
                illumination_fraction=self._moon_illumination(moon_coord, sun_coord),
            )
            planet_records = [
                (
                    body_name,
                    label,
                    color,
                    get_body(body_name, context.time_utc, context.location),
                )
                for body_name, label, color in PLANETS
            ]
            planets = [
                self._body_metadata(label, coordinate, context)
                for _body_name, label, _color, coordinate in planet_records
            ]
            target = self._target_metadata(resolved_target, context)

            figure = Figure(
                figsize=(CANVAS_WIDTH_PX / CANVAS_DPI, CANVAS_HEIGHT_PX / CANVAS_DPI),
                dpi=CANVAS_DPI,
                facecolor="#000000",
            )
            try:
                FigureCanvasAgg(figure)
                axes = figure.add_axes((0.12, 0.11, 0.76, 0.84), facecolor="#000000")
                axes.set_xlim(-1.05, 1.05)
                axes.set_ylim(-1.05, 1.05)
                axes.set_aspect("equal")
                axes.axis("off")

                self._draw_background(axes)
                self._draw_horizon_grid(axes)
                segments_drawn = self._draw_constellations(
                    axes, selection.constellation_segments, constellation_altaz
                )
                stars_drawn = self._draw_stars(axes, selection.catalog.stars, star_altaz)
                self._draw_moon(axes, moon)
                self._draw_planets(axes, planets, planet_records)
                self._draw_target(axes, target)
                self._draw_footer(figure, request, context, selection)

                png_bytes = self._save_rgb_png(figure)
            finally:
                figure.clear()
            png_digest = sha256(png_bytes).hexdigest()

        metadata = SkyChartExportMetadata(
            render_id="pending",
            created_at_utc=created_at,
            request=SkyChartExportRequest(
                observer=request.observer,
                timestamp_local=request.timestamp_local,
                timestamp_utc=context.timestamp_utc,
                target=SkyChartExportTarget(
                    mode=request.target.mode,
                    input=self._target_input(request),
                    resolved=target,
                ),
                catalog_mode_requested=request.catalog_mode,
                catalog_mode_used=selection.mode_used,
            ),
            render=SkyChartRenderMetadata(
                projection="azimuthal_equidistant_zenith",
                width_px=CANVAS_WIDTH_PX,
                height_px=CANVAS_HEIGHT_PX,
                layer_order=LAYER_ORDER,
                png_sha256=png_digest,
            ),
            objects=SkyChartObjectsMetadata(
                moon=moon,
                planets=planets,
                target=target,
                stars_drawn=stars_drawn,
                constellation_segments_drawn=segments_drawn,
            ),
            catalog=SkyChartCatalogMetadata(
                dataset_id=selection.catalog.metadata.dataset_id,
                version=selection.catalog.metadata.version,
                source_url=selection.catalog.metadata.source_url,
                license=selection.catalog.metadata.license,
                sha256=selection.catalog.metadata.sha256,
                status=selection.status,
            ),
            calculation=SkyChartCalculationMetadata(),
            dependencies=context.dependencies,
            warnings=["catalog_degraded"] if selection.status == "degraded" else [],
        )
        return RenderedSkyChart(
            png_bytes=png_bytes,
            metadata=metadata,
            catalog_mode_used=selection.mode_used,
            catalog_status=selection.status,
            metadata_json_bytes=_serialize_metadata(metadata),
        )

    @staticmethod
    def _make_context(request: SkyChartRequest) -> _RenderContext:
        time_utc = Time(request.timestamp_local).utc
        timestamp_utc = time_utc.to_datetime(timezone=timezone.utc)
        location = EarthLocation.from_geodetic(
            lon=request.observer.longitude * u.deg,
            lat=request.observer.latitude * u.deg,
        )
        frame = AltAz(
            obstime=time_utc,
            location=location,
            pressure=0 * u.hPa,
        )
        return _RenderContext(
            time_utc=time_utc,
            timestamp_utc=timestamp_utc,
            location=location,
            frame=frame,
            dependencies=SkyChartDependenciesMetadata(
                python=platform.python_version(),
                astropy=astropy.__version__,
                matplotlib=matplotlib.__version__,
                tzdata=_dependency_version("tzdata"),
            ),
        )

    @staticmethod
    def _star_horizontal(stars: Sequence[CatalogStar], context: _RenderContext):
        coordinates = SkyCoord(
            ra=[star.ra_deg for star in stars] * u.deg,
            dec=[star.dec_deg for star in stars] * u.deg,
            frame="icrs",
        )
        return coordinates.transform_to(context.frame)

    @staticmethod
    def _body_metadata(
        label: str,
        coordinate: SkyCoord,
        context: _RenderContext,
        *,
        illumination_fraction: float | None = None,
    ) -> SkyChartObject:
        horizontal = coordinate.transform_to(context.frame)
        icrs = coordinate.icrs
        altitude = float(horizontal.alt.deg)
        return SkyChartObject(
            label=label,
            icrs=SkyChartIcrsCoordinates(
                ra_deg=float(icrs.ra.deg) % 360,
                dec_deg=float(icrs.dec.deg),
            ),
            altaz=SkyChartAltAzCoordinates(
                altitude_deg=altitude,
                azimuth_deg=float(horizontal.az.deg) % 360,
            ),
            visible=altitude >= 0,
            drawn=altitude >= 0,
            illumination_fraction=illumination_fraction,
        )

    def _target_metadata(
        self,
        resolved: ResolvedSkyTarget | None,
        context: _RenderContext,
    ) -> SkyChartObject | None:
        if resolved is None:
            return None
        if resolved.solar_system_body is not None:
            return self._body_metadata(
                resolved.label,
                get_body(resolved.solar_system_body, context.time_utc, context.location),
                context,
            )
        assert resolved.ra_deg is not None and resolved.dec_deg is not None
        coordinate = SkyCoord(
            ra=resolved.ra_deg * u.deg,
            dec=resolved.dec_deg * u.deg,
            frame="icrs",
        )
        horizontal = coordinate.transform_to(context.frame)
        altitude = float(horizontal.alt.deg)
        return SkyChartObject(
            label=resolved.label,
            icrs=SkyChartIcrsCoordinates(
                ra_deg=resolved.ra_deg,
                dec_deg=resolved.dec_deg,
            ),
            altaz=SkyChartAltAzCoordinates(
                altitude_deg=altitude,
                azimuth_deg=float(horizontal.az.deg) % 360,
            ),
            visible=altitude >= 0,
            drawn=altitude >= 0,
        )

    @staticmethod
    def _moon_illumination(moon: SkyCoord, sun: SkyCoord) -> float:
        elongation = moon.separation(sun).rad
        return float((1.0 - math.cos(elongation)) / 2.0)

    @staticmethod
    def _draw_background(axes) -> None:
        axes.add_patch(Circle((0, 0), 1.0, facecolor="#05070c", edgecolor="none", zorder=0))

    @staticmethod
    def _draw_horizon_grid(axes) -> None:
        for altitude, radius in ((0, 1.0), (30, 2 / 3), (60, 1 / 3)):
            axes.add_patch(
                Circle(
                    (0, 0),
                    radius,
                    fill=False,
                    edgecolor="#33414d",
                    linewidth=0.7 if altitude else 1.2,
                    zorder=1,
                )
            )
        for azimuth in (0, 90, 180, 270):
            x, y = project_altaz(0, azimuth)
            axes.plot([0, x], [0, y], color="#202d36", linewidth=0.5, zorder=1)
        axes.scatter([0], [0], s=3, c="#33414d", edgecolors="none", zorder=1)
        for label, x, y in (("N", 0, 1.025), ("E", 1.025, 0), ("S", 0, -1.025), ("W", -1.025, 0)):
            axes.text(x, y, label, color="#8ea0aa", fontsize=9, ha="center", va="center", zorder=1)

    @staticmethod
    def _draw_constellations(
        axes,
        segments: Sequence[ConstellationSegment],
        star_altaz: dict[str, tuple[float, float]],
    ) -> int:
        drawn = 0
        for segment in segments:
            start = star_altaz.get(segment.start_star_id)
            end = star_altaz.get(segment.end_star_id)
            if start is None or end is None or start[0] < 0 or end[0] < 0:
                continue
            start_xy = project_altaz(*start)
            end_xy = project_altaz(*end)
            axes.plot(
                [start_xy[0], end_xy[0]],
                [start_xy[1], end_xy[1]],
                color="#40576d",
                linewidth=0.8,
                alpha=0.8,
                zorder=2,
            )
            drawn += 1
        return drawn

    @staticmethod
    def _draw_stars(
        axes,
        stars: Sequence[CatalogStar],
        star_altaz: dict[str, tuple[float, float]],
    ) -> int:
        x_values: list[float] = []
        y_values: list[float] = []
        sizes: list[float] = []
        for star in sort_stars_dim_to_bright(stars):
            altitude, azimuth = star_altaz[star.star_id]
            if altitude < 0:
                continue
            x, y = project_altaz(altitude, azimuth)
            x_values.append(x)
            y_values.append(y)
            sizes.append(max(3.0, 34.0 - 5.0 * star.magnitude))
        if x_values:
            axes.scatter(
                x_values,
                y_values,
                s=sizes,
                c="#f5f1df",
                edgecolors="none",
                zorder=3,
            )
        return len(x_values)

    @staticmethod
    def _draw_moon(axes, moon: SkyChartObject) -> None:
        if not moon.drawn or moon.altaz.altitude_deg < 0:
            return
        x, y = project_altaz(moon.altaz.altitude_deg, moon.altaz.azimuth_deg)
        illumination = moon.illumination_fraction or 0.0
        radius = 0.022
        axes.add_patch(
            Circle((x, y), radius, facecolor="#252830", edgecolor="none", zorder=4)
        )
        axes.add_patch(
            Wedge(
                (x, y),
                radius,
                theta1=90,
                theta2=90 + 360 * illumination,
                facecolor="#f2ead2",
                edgecolor="none",
                zorder=4.1,
            )
        )
        axes.add_patch(
            Circle(
                (x, y),
                radius,
                fill=False,
                edgecolor="#f1ead4",
                linewidth=0.8,
                zorder=4.2,
            )
        )
        axes.text(x + 0.025, y + 0.025, moon.label, color="#e8e1ca", fontsize=7, zorder=4)

    @staticmethod
    def _draw_planets(axes, planets: Sequence[SkyChartObject], planet_records) -> None:
        for planet, (_body_name, _label, color, _coordinate) in zip(planets, planet_records, strict=True):
            if not planet.drawn:
                continue
            x, y = project_altaz(planet.altaz.altitude_deg, planet.altaz.azimuth_deg)
            axes.scatter([x], [y], s=46, c=color, edgecolors="#ffffff", linewidths=0.4, zorder=5)
            axes.text(x + 0.02, y + 0.02, planet.label, color=color, fontsize=6.5, zorder=5)

    @staticmethod
    def _draw_target(axes, target: SkyChartObject | None) -> None:
        if target is None or not target.drawn:
            return
        x, y = project_altaz(target.altaz.altitude_deg, target.altaz.azimuth_deg)
        axes.scatter([x], [y], s=170, facecolors="none", edgecolors="#ffd43b", linewidths=1.1, zorder=6)
        axes.scatter([x], [y], s=52, marker="+", c="#ffd43b", linewidths=1.3, zorder=6)
        axes.text(x + 0.035, y + 0.035, target.label, color="#ffd43b", fontsize=8, zorder=6)

    @staticmethod
    def _draw_footer(figure: Figure, request: SkyChartRequest, context: _RenderContext, selection: CatalogSelection) -> None:
        local = request.timestamp_local.isoformat()
        utc = context.timestamp_utc.isoformat().replace("+00:00", "Z")
        footer = (
            f"{request.observer.location_name} | {request.observer.timezone} | {local} | UTC {utc} | "
            f"catalog {selection.mode_used}/{selection.status} | AltAz pressure=0 hPa | builtin ephemeris"
        )
        figure.text(0.5, 0.035, footer, color="#93a2aa", fontsize=7.5, ha="center", va="center")

    @staticmethod
    def _save_rgb_png(figure: Figure) -> bytes:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Glyph .* missing from font\(s\) DejaVu Sans\.",
                category=UserWarning,
            )
            canvas = figure.canvas
            canvas.draw()
        rgba = np.asarray(canvas.buffer_rgba(), dtype=np.uint8)
        height, width, channels = rgba.shape
        if channels != 4:
            raise ValueError("Agg canvas did not provide RGBA pixels")
        rgb_bytes = np.ascontiguousarray(rgba[:, :, :3]).tobytes()
        return _encode_rgb_png(rgb_bytes, width=width, height=height)

    @staticmethod
    def _target_input(request: SkyChartRequest) -> str:
        if request.target.mode == "name":
            assert request.target.name is not None
            return request.target.name
        assert request.target.ra_deg is not None and request.target.dec_deg is not None
        return f"{request.target.ra_deg:.6f}, {request.target.dec_deg:.6f}"


class SkyChartService:
    """Select local data, contain resolver failures, and render one chart."""

    def __init__(
        self,
        *,
        full_catalog_cache: _FullCatalogCache | None = None,
        target_resolver: SkyChartTargetResolver | None = None,
        bundled_catalog: BundledCatalog | None = None,
        utc_clock: Callable[[], datetime] = utc_now,
        renderer: SkyChartRenderer | None = None,
    ) -> None:
        self._bundled_catalog = bundled_catalog or load_bundled_catalog()
        self._full_catalog_cache = full_catalog_cache or _EmptyFullCatalogCache()
        self._target_resolver = target_resolver or SkyChartTargetResolver(lambda _name: None)
        self._renderer = renderer or SkyChartRenderer(utc_clock=utc_clock)

    def render(self, request: SkyChartRequest) -> RenderedSkyChart:
        selection = select_catalog(
            request.catalog_mode,
            self._bundled_catalog,
            self._full_catalog_cache,
        )
        warning: str | None = None
        try:
            resolved = self._target_resolver.resolve(request.target)
        except (InvalidTargetNameError, TargetNotFoundError):
            resolved = None
            warning = "target_unresolved"
        except TargetServiceError:
            resolved = None
            warning = "target_resolution_unavailable"
        else:
            if resolved is None:
                warning = "target_unresolved"

        chart = self._renderer.render(request, selection, resolved)
        if warning is None:
            return chart
        metadata = chart.metadata.model_copy(
            update={"warnings": [*chart.metadata.warnings, warning]}
        )
        return RenderedSkyChart(
            png_bytes=chart.png_bytes,
            metadata=metadata,
            catalog_mode_used=chart.catalog_mode_used,
            catalog_status=chart.catalog_status,
            metadata_json_bytes=_serialize_metadata(metadata),
        )


class RenderStore:
    """Thread-safe TTL store containing only the two export byte payloads."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 15 * 60,
        max_records: int = 20,
        max_bytes: int = 50 * 1024 * 1024,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_seconds <= 0 or max_records <= 0 or max_bytes <= 0:
            raise ValueError("render store limits must be positive")
        self.ttl_seconds = float(ttl_seconds)
        self.max_records = int(max_records)
        self.max_bytes = int(max_bytes)
        self._monotonic_clock = monotonic_clock or __import__("time").monotonic
        self._records: dict[str, _StoreRecord] = {}
        self._total_bytes = 0
        self._insertion_order = 0
        self._lock = threading.Lock()

    def put(self, chart: RenderedSkyChart) -> str:
        with self._lock:
            now = self._monotonic_clock()
            self._purge_expired(now)
            if chart.metadata.render.png_sha256 != sha256(chart.png_bytes).hexdigest():
                raise ValueError("render metadata does not match PNG bytes")
            render_id = self._new_render_id()
            metadata = chart.metadata.model_copy(update={"render_id": render_id})
            metadata_json = _serialize_metadata(metadata)
            self._put_record(render_id, now, chart.png_bytes, metadata_json)
            return render_id

    def get(self, render_id: str) -> RenderedSkyChart | None:
        with self._lock:
            now = self._monotonic_clock()
            self._purge_expired(now)
            if not isinstance(render_id, str) or not _RENDER_ID_RE.fullmatch(render_id):
                return None
            record = self._records.get(render_id)
            if record is None:
                return None
            metadata = SkyChartExportMetadata.model_validate_json(
                record.metadata_json_bytes
            )
            return RenderedSkyChart(
                png_bytes=record.png_bytes,
                metadata=metadata,
                catalog_mode_used=metadata.request.catalog_mode_used,
                catalog_status=metadata.catalog.status,
                metadata_json_bytes=record.metadata_json_bytes,
            )

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._total_bytes = 0

    def _put_record(
        self,
        render_id: str,
        now: float,
        png_bytes: bytes,
        metadata_json_bytes: bytes,
    ) -> None:
        byte_size = len(png_bytes) + len(metadata_json_bytes)
        if byte_size > self.max_bytes:
            raise ValueError("render exceeds the store byte capacity")
        while self._records and (
            len(self._records) >= self.max_records
            or self._total_bytes + byte_size > self.max_bytes
        ):
            eviction_id = min(
                self._records,
                key=lambda candidate: (
                    self._records[candidate].expires_at,
                    self._records[candidate].insertion_order,
                ),
            )
            self._remove(eviction_id)
        record = _StoreRecord(
            expires_at=now + self.ttl_seconds,
            insertion_order=self._insertion_order,
            png_bytes=png_bytes,
            metadata_json_bytes=metadata_json_bytes,
        )
        self._insertion_order += 1
        self._records[render_id] = record
        self._total_bytes += record.byte_size

    def _purge_expired(self, now: float) -> None:
        for render_id in [
            candidate
            for candidate, record in self._records.items()
            if record.expires_at <= now
        ]:
            self._remove(render_id)

    def _remove(self, render_id: str) -> None:
        record = self._records.pop(render_id)
        self._total_bytes -= record.byte_size

    def _new_render_id(self) -> str:
        while True:
            render_id = secrets.token_urlsafe(24)
            if _RENDER_ID_RE.fullmatch(render_id) and render_id not in self._records:
                return render_id


def _dependency_version(distribution: str) -> str:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return "system"


def _serialize_metadata(metadata: SkyChartExportMetadata) -> bytes:
    return metadata.model_dump_json(
        exclude_none=False,
        by_alias=True,
    ).encode("utf-8")


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def _encode_rgb_png(rgb_bytes: bytes, *, width: int, height: int) -> bytes:
    row_size = width * 3
    if len(rgb_bytes) != row_size * height:
        raise ValueError("RGB pixel buffer has an unexpected size")

    scanlines = bytearray((row_size + 1) * height)
    for row in range(height):
        source_start = row * row_size
        target_start = row * (row_size + 1)
        scanlines[target_start + 1 : target_start + row_size + 1] = rgb_bytes[
            source_start : source_start + row_size
        ]

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", header),
            _png_chunk(b"IDAT", zlib.compress(scanlines, level=6)),
            _png_chunk(b"IEND", b""),
        )
    )
