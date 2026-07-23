from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import re

from PIL import Image, ImageChops
import pytest

import starskill.sky_chart as sky_chart_module
from starskill.schemas import SkyChartExportMetadata, SkyChartRequest
from starskill.sky_chart import (
    RenderStore,
    SkyChartRenderer,
    SkyChartService,
    sort_stars_dim_to_bright,
)
from starskill.sky_chart_catalog import (
    BundledCatalog,
    CatalogMetadata,
    CatalogSelection,
    CatalogStar,
    ConstellationSegment,
    FullCatalog,
)
from starskill.sky_chart_targets import SkyChartTargetResolver
from starskill.target_resolver import (
    InvalidTargetNameError,
    TargetNotFoundError,
    TargetServiceError,
)


FIXED_REQUEST = SkyChartRequest.model_validate(
    {
        "observer": {
            "location_name": "Beijing",
            "longitude": 116.4074,
            "latitude": 39.9042,
            "timezone": "Asia/Shanghai",
        },
        "timestamp_local": "2026-01-10T20:00:00+08:00",
        "target": {
            "mode": "coordinates",
            "ra_deg": 83.822083,
            "dec_deg": -5.391111,
        },
        "catalog_mode": "bundled",
    }
)
FIXED_CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


class EmptyFullCache:
    def load_valid(self) -> None:
        return None


class FixedFullCache:
    def __init__(self, catalog: FullCatalog) -> None:
        self.catalog = catalog
        self.calls = 0

    def load_valid(self) -> FullCatalog:
        self.calls += 1
        return self.catalog


@pytest.fixture(scope="module")
def service() -> SkyChartService:
    return SkyChartService(
        full_catalog_cache=EmptyFullCache(),
        target_resolver=SkyChartTargetResolver(lambda _name: None),
        utc_clock=lambda: FIXED_CREATED_AT,
    )


@pytest.fixture(scope="module")
def fixed_chart(service: SkyChartService):
    return service.render(FIXED_REQUEST)


def test_render_has_expected_layer_order_and_linked_png_digest(fixed_chart) -> None:
    assert fixed_chart.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert fixed_chart.metadata.render.layer_order == [
        "background",
        "horizon_grid",
        "constellations",
        "stars",
        "moon",
        "planets",
        "target",
        "footer",
    ]
    assert fixed_chart.metadata.render.png_sha256 == sha256(
        fixed_chart.png_bytes
    ).hexdigest()
    assert fixed_chart.metadata.calculation.horizontal_frame == "AltAz"
    assert fixed_chart.metadata.calculation.atmospheric_refraction is False


def test_png_is_exact_rgb_canvas_and_nonblank(fixed_chart) -> None:
    image = Image.open(BytesIO(fixed_chart.png_bytes))
    assert image.size == (1200, 900)
    assert image.mode == "RGB"
    assert image.getpixel((0, 0)) == (0, 0, 0)
    assert ImageChops.difference(image, Image.new("RGB", image.size)).getbbox()


def test_invisible_object_is_recorded_but_not_drawn(fixed_chart) -> None:
    objects = [fixed_chart.metadata.objects.moon, *fixed_chart.metadata.objects.planets]
    assert all(item.drawn is item.visible for item in objects)
    assert any(not item.visible for item in objects)


def test_moon_and_seven_planets_have_complete_metadata(fixed_chart) -> None:
    moon = fixed_chart.metadata.objects.moon
    assert moon.icrs is not None
    assert moon.illumination_fraction is not None
    assert 0 <= moon.illumination_fraction <= 1
    assert [planet.label for planet in fixed_chart.metadata.objects.planets] == [
        "Mercury / 水星",
        "Venus / 金星",
        "Mars / 火星",
        "Jupiter / 木星",
        "Saturn / 土星",
        "Uranus / 天王星",
        "Neptune / 海王星",
    ]
    assert all(planet.icrs is not None for planet in fixed_chart.metadata.objects.planets)
    assert all("sun" not in planet.label.casefold() for planet in fixed_chart.metadata.objects.planets)


def test_star_magnitude_order_is_dim_to_bright() -> None:
    stars = (
        CatalogStar("bright", "Bright", 0, 0, -1),
        CatalogStar("dim", "Dim", 0, 0, 5),
        CatalogStar("middle", "Middle", 0, 0, 2),
    )
    assert [star.star_id for star in sort_stars_dim_to_bright(stars)] == [
        "dim",
        "middle",
        "bright",
    ]


def test_constellation_segment_requires_both_endpoints_above_horizon() -> None:
    catalog = BundledCatalog(
        stars=(
            CatalogStar("north", "North", 0, 90, 1),
            CatalogStar("south", "South", 0, -90, 1),
        ),
        segments=(ConstellationSegment("Test", "north", "south"),),
        metadata=CatalogMetadata("test", "1", "https://example.test", "CC0", "a" * 64),
    )
    request = FIXED_REQUEST.model_copy(
        update={
            "observer": FIXED_REQUEST.observer.model_copy(
                update={"longitude": 0.0, "latitude": 90.0, "timezone": "UTC"}
            ),
            "timestamp_local": datetime(2026, 1, 10, 12, tzinfo=timezone.utc),
        }
    )
    chart = SkyChartRenderer(utc_clock=lambda: FIXED_CREATED_AT).render(
        request,
        CatalogSelection("bundled", "available", catalog, catalog.segments),
        None,
    )
    assert chart.metadata.objects.stars_drawn == 1
    assert chart.metadata.objects.constellation_segments_drawn == 0


@pytest.mark.parametrize(
    ("error", "warning"),
    [
        (InvalidTargetNameError("private detail"), "target_unresolved"),
        (TargetNotFoundError("private detail"), "target_unresolved"),
        (TargetServiceError("private detail"), "target_resolution_unavailable"),
    ],
)
def test_target_resolution_failures_become_stable_warning_only(
    error: Exception, warning: str
) -> None:
    request = FIXED_REQUEST.model_copy(
        update={
            "target": FIXED_REQUEST.target.model_copy(
                update={"mode": "name", "name": "Example", "ra_deg": None, "dec_deg": None}
            )
        }
    )
    resolver = SkyChartTargetResolver(
        lambda _name: (_ for _ in ()).throw(error)
    )
    chart = SkyChartService(
        full_catalog_cache=EmptyFullCache(),
        target_resolver=resolver,
        utc_clock=lambda: FIXED_CREATED_AT,
    ).render(request)
    serialized = chart.metadata.model_dump_json(exclude_none=False, by_alias=True)

    assert chart.metadata.objects.target is None
    assert chart.metadata.warnings == [warning]
    assert "private detail" not in serialized


def test_none_target_resolution_becomes_target_unresolved() -> None:
    request = FIXED_REQUEST.model_copy(
        update={
            "target": FIXED_REQUEST.target.model_copy(
                update={"mode": "name", "name": "Example", "ra_deg": None, "dec_deg": None}
            )
        }
    )
    chart = SkyChartService(
        full_catalog_cache=EmptyFullCache(),
        target_resolver=SkyChartTargetResolver(lambda _name: None),
        utc_clock=lambda: FIXED_CREATED_AT,
    ).render(request)
    assert chart.metadata.objects.target is None
    assert chart.metadata.warnings == ["target_unresolved"]


def test_auto_catalog_degradation_is_in_status_warning_and_footer() -> None:
    chart = SkyChartService(
        full_catalog_cache=EmptyFullCache(),
        target_resolver=SkyChartTargetResolver(lambda _name: None),
        utc_clock=lambda: FIXED_CREATED_AT,
    ).render(FIXED_REQUEST.model_copy(update={"catalog_mode": "auto"}))
    assert chart.catalog_mode_used == "bundled"
    assert chart.catalog_status == "degraded"
    assert chart.metadata.catalog.status == "degraded"
    assert chart.metadata.warnings == ["catalog_degraded"]


def test_full_catalog_selection_is_cache_only_and_uses_bundled_segments() -> None:
    full = FullCatalog(
        stars=(CatalogStar("full-1", "Full", 0, 90, 1),),
        metadata=CatalogMetadata("full", "1", "https://example.test/full", "CC0", "b" * 64),
        row_count=100_001,
    )
    cache = FixedFullCache(full)
    chart = SkyChartService(
        full_catalog_cache=cache,
        target_resolver=SkyChartTargetResolver(lambda _name: None),
        utc_clock=lambda: FIXED_CREATED_AT,
    ).render(FIXED_REQUEST.model_copy(update={"catalog_mode": "full"}))
    assert cache.calls == 1
    assert chart.catalog_mode_used == "full"
    assert chart.catalog_status == "available"
    assert chart.metadata.catalog.dataset_id == "full"


def test_full_catalog_draws_segments_from_bundled_endpoint_stars() -> None:
    bundled = BundledCatalog(
        stars=(
            CatalogStar("a", "A", 0, 90, 1),
            CatalogStar("b", "B", 90, 90, 1),
        ),
        segments=(ConstellationSegment("Test", "a", "b"),),
        metadata=CatalogMetadata("bundled", "1", "https://example.test/b", "CC0", "a" * 64),
    )
    full = FullCatalog(
        stars=(CatalogStar("hyg-1", "Full", 180, 90, 1),),
        metadata=CatalogMetadata("full", "1", "https://example.test/f", "CC0", "b" * 64),
        row_count=100_001,
    )
    request = FIXED_REQUEST.model_copy(
        update={
            "catalog_mode": "full",
            "observer": FIXED_REQUEST.observer.model_copy(
                update={"longitude": 0.0, "latitude": 90.0, "timezone": "UTC"}
            ),
            "timestamp_local": datetime(2026, 1, 10, 12, tzinfo=timezone.utc),
        }
    )
    chart = SkyChartService(
        bundled_catalog=bundled,
        full_catalog_cache=FixedFullCache(full),
        target_resolver=SkyChartTargetResolver(lambda _name: None),
        utc_clock=lambda: FIXED_CREATED_AT,
    ).render(request)
    assert chart.metadata.objects.stars_drawn == 1
    assert chart.metadata.objects.constellation_segments_drawn == 1


def test_serialized_coordinates_have_exactly_six_decimal_places(fixed_chart) -> None:
    serialized = fixed_chart.metadata.model_dump_json(exclude_none=False, by_alias=True)
    coordinate_tokens = re.findall(
        r'"(?:longitude|latitude|ra_deg|dec_deg|altitude_deg|azimuth_deg)":(-?\d+\.\d+)',
        serialized,
    )
    assert coordinate_tokens
    assert all(len(token.rsplit(".", 1)[1]) == 6 for token in coordinate_tokens)


def test_store_serializes_once_and_returns_exact_export_bytes(fixed_chart, monkeypatch) -> None:
    calls = 0
    original = SkyChartExportMetadata.model_dump_json

    def counted(self, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs == {"exclude_none": False, "by_alias": True}
        return original(self, **kwargs)

    monkeypatch.setattr(SkyChartExportMetadata, "model_dump_json", counted)
    store = RenderStore()
    render_id = store.put(fixed_chart)
    stored = store.get(render_id)

    assert calls == 1
    assert stored is not None
    assert stored.metadata.render_id == render_id
    assert stored.metadata_json_bytes is not None
    assert json.loads(stored.metadata_json_bytes)["render_id"] == render_id
    assert json.loads(stored.metadata_json_bytes)["render"]["png_sha256"] == sha256(
        stored.png_bytes
    ).hexdigest()


def test_render_store_expires_and_malformed_ids_match_missing() -> None:
    now = [0.0]
    store = RenderStore(
        ttl_seconds=900,
        max_records=2,
        max_bytes=100,
        monotonic_clock=lambda: now[0],
    )
    first = store.put_bytes_for_test(b"a")
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", first)
    assert store.get("not/valid") is None
    assert store.get("missing_but_valid") is None
    now[0] = 901.0
    assert store.get(first) is None


def test_render_store_retries_malformed_generated_id(monkeypatch) -> None:
    generated = iter(["not/url-safe", "A" * 32])
    monkeypatch.setattr(
        sky_chart_module.secrets,
        "token_urlsafe",
        lambda _bytes: next(generated),
    )
    store = RenderStore(max_bytes=100)
    assert store.put_bytes_for_test(b"a") == "A" * 32


def test_render_store_purges_before_malformed_get() -> None:
    now = [0.0]
    store = RenderStore(ttl_seconds=1, monotonic_clock=lambda: now[0])
    render_id = store.put_bytes_for_test(b"a")
    now[0] = 2.0
    assert store.get("bad/id") is None
    now[0] = 0.0
    assert store.get(render_id) is None


def test_render_store_evicts_at_default_record_capacity() -> None:
    store = RenderStore(max_bytes=10_000)
    assert store.max_records == 20
    ids = [store.put_bytes_for_test(str(index).encode()) for index in range(21)]
    assert store.get(ids[0]) is None
    assert all(store.get(render_id) is not None for render_id in ids[1:])


def test_render_store_evicts_at_byte_capacity_and_uses_50_mib_default() -> None:
    assert RenderStore().max_bytes == 50 * 1024 * 1024
    store = RenderStore(max_records=20, max_bytes=5)
    first = store.put_bytes_for_test(b"aaa")
    second = store.put_bytes_for_test(b"bbb")
    assert store.get(first) is None
    assert store.get(second) is not None


def test_render_store_evicts_earliest_expiry_then_insertion_order_and_clears() -> None:
    now = [0.0]
    store = RenderStore(
        ttl_seconds=10,
        max_records=2,
        max_bytes=10,
        monotonic_clock=lambda: now[0],
    )
    first = store.put_bytes_for_test(b"a")
    second = store.put_bytes_for_test(b"b")
    now[0] = 1.0
    third = store.put_bytes_for_test(b"c")
    assert store.get(first) is None
    assert store.get(second) is not None
    assert store.get(third) is not None
    store.clear()
    assert store.get(second) is None
    assert store.get(third) is None
