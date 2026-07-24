from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sys

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from PIL import Image
import pytest

from starskill.mcp_server import StarSkillMcpService
from starskill.schemas import (
    ExternalSource,
    LightPollutionResult,
    NasaFeature,
    WeatherForecast,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StaticTargetBackend:
    service_url = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

    def query_object(self, query_name: str) -> dict[str, object]:
        return {
            "canonical_name": "M 42",
            "ra_deg": 83.8201,
            "dec_deg": -5.3876,
            "object_type": "HII",
            "aliases": ["M 42", "NGC 1976", "Orion Nebula"],
        }


class StaticImageBackend:
    def __init__(self) -> None:
        image = Image.new("RGB", (512, 512), "#101820")
        output = BytesIO()
        image.save(output, format="JPEG")
        self.content = output.getvalue()

    def fetch(
        self, url: str, *, timeout_seconds: int, max_bytes: int
    ) -> tuple[bytes, str]:
        return self.content, "image/jpeg"


class StaticWeatherProvider:
    def get_forecast(self, request: object) -> WeatherForecast:
        return WeatherForecast(
            samples=[],
            source=ExternalSource(
                provider="测试天气预报",
                source_url="https://example.test/weather",
                accessed_at=datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
                from_cache=False,
                availability="unavailable",
                issue_code="test_provider_unavailable",
            ),
        )


class StaticLightPollutionProvider:
    def lookup(self, observer: object) -> LightPollutionResult:
        return LightPollutionResult(
            radiance=18.5,
            unit="nW cm-2 sr-1",
            dataset_id="test-black-marble",
            dataset_version="v1",
            sample_period="2026",
            spatial_resolution="1 km",
            interpolation="nearest_snapshot_cell",
            source=ExternalSource(
                provider="NASA Black Marble",
                source_url="https://example.test/black-marble",
                accessed_at=datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
                from_cache=False,
                availability="fresh",
            ),
        )


class StaticNasaProvider:
    def get_feature(self, date: str | None) -> NasaFeature:
        return NasaFeature(
            date=date or "2026-07-23",
            title="Test APOD",
            media_type="image",
            media_url="https://example.test/apod.jpg",
            source=ExternalSource(
                provider="NASA APOD",
                source_url="https://example.test/apod",
                accessed_at=datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
                from_cache=False,
                availability="fresh",
            ),
        )


class StaticStellariumBridge:
    def sync(self, request: object) -> dict[str, object]:
        return {
            "ok": 1,
            "base_url": "http://127.0.0.1:8090",
            "operations": ["status", "location", "time", "focus"],
            "error": None,
        }


class MalformedStellariumBridge:
    def sync(self, request: object) -> dict[str, object]:
        return {"ok": True}


def load_observation_payload() -> dict[str, object]:
    return json.loads(
        (PROJECT_ROOT / "examples/observation_m42_beijing.json").read_text(
            encoding="utf-8"
        )
    )


def generic_coordinate_task() -> dict[str, object]:
    return {
        "task_type": "astronomical_relationship",
        "primary": {"kind": "coordinates", "label": "A", "ra_deg": 10, "dec_deg": 20},
        "secondary": {"kind": "coordinates", "label": "B", "ra_deg": 11, "dec_deg": 21},
        "observer": {
            "location_name": "Shanghai",
            "longitude": 121.4737,
            "latitude": 31.2304,
            "timezone": "Asia/Shanghai",
        },
        "time_range": {
            "start": "2026-01-10T18:00:00+08:00",
            "end": "2026-01-10T18:20:00+08:00",
        },
        "interval_minutes": 20,
    }


def make_service_with_fake_outreach_providers(
    tmp_path: Path,
    *,
    stellarium_bridge_factory=StaticStellariumBridge,
) -> StarSkillMcpService:
    return StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        target_backend_factory=StaticTargetBackend,
        weather_provider_factory=StaticWeatherProvider,
        light_pollution_provider_factory=StaticLightPollutionProvider,
        nasa_provider_factory=StaticNasaProvider,
        stellarium_bridge_factory=stellarium_bridge_factory,
        clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
    )


def test_plan_observation_writes_audited_run_under_the_service_root(tmp_path) -> None:
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        target_backend_factory=StaticTargetBackend,
        clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
    )

    result = service.plan_observation(
        json.loads(
            (PROJECT_ROOT / "examples/observation_m42_beijing.json").read_text(
                encoding="utf-8"
            )
        )
    )

    assert result["status"] == "success"
    assert result["run_id"]
    assert result["resources"]["manifest"] == (
        f"starskill://runs/{result['run_id']}/manifest"
    )
    assert result["resources"]["report"] == (
        f"starskill://runs/{result['run_id']}/report"
    )
    assert "# 观测报告" in service.read_run_resource(result["run_id"], "report")
    assert (tmp_path / "runs" / result["run_id"] / "run.json").is_file()


def test_relationship_tool_writes_results_as_server_resources(tmp_path) -> None:
    task = json.loads(
        (PROJECT_ROOT / "examples/moon_jupiter_shanghai.json").read_text(
            encoding="utf-8"
        )
    )
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
    )

    result = service.calculate_moon_jupiter_relationship(task)

    assert result["ok"] is True
    assert result["sample_count"] > 0
    assert set(result) == {
        "ok",
        "run_id",
        "sample_count",
        "minimum_separation_deg",
        "maximum_separation_deg",
        "resources",
    }
    assert result["resources"]["relationship"] == (
        f"starskill://runs/{result['run_id']}/relationship"
    )
    metadata = json.loads(service.read_run_resource(result["run_id"], "relationship"))
    assert "schema_version" not in metadata["settings"]
    assert "angular_separation_deg" in service.read_run_resource(
        result["run_id"], "relationship"
    )


def test_mcp_generic_relationship_publishes_only_run_resources(tmp_path: Path) -> None:
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
    )

    result = service.calculate_astronomical_relationship(generic_coordinate_task())

    assert result["ok"] is True
    assert result["resources"]["relationship"].startswith("starskill://runs/")
    assert result["resources"]["relationship-table"].startswith("starskill://runs/")
    assert "output_dir" not in result
    metadata = json.loads(
        service.read_run_resource(result["run_id"], "relationship")
    )
    assert metadata["settings"]["schema_version"] == "2.0"


def test_mcp_generic_target_resolution_is_pure_for_coordinates(tmp_path: Path) -> None:
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        target_backend_factory=lambda: pytest.fail("coordinates must not query SIMBAD"),
        clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
    )

    result = service.resolve_astronomy_target(
        {"kind": "coordinates", "label": "A", "ra_deg": 10, "dec_deg": 20}
    )

    assert result["ok"] is True
    assert result["target"]["source"]["provider"] == "user_coordinates"
    assert not (tmp_path / "runs").exists()


def test_mcp_generic_target_resolution_supports_solar_system_and_simbad(
    tmp_path: Path,
) -> None:
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        target_backend_factory=StaticTargetBackend,
        clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
    )

    solar = service.resolve_astronomy_target(
        {"kind": "solar_system", "body": "mars"}
    )
    simbad = service.resolve_astronomy_target({"kind": "simbad", "name": "M42"})

    assert (solar["target"]["motion"], solar["target"]["label"]) == (
        "dynamic",
        "Mars",
    )
    assert simbad["target"]["catalog_target"]["canonical_name"] == "M 42"
    assert not (tmp_path / "runs").exists()


def test_mcp_generic_relationship_returns_unsupported_body_failure(
    tmp_path: Path,
) -> None:
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
    )
    task = generic_coordinate_task()
    task["primary"] = {"kind": "solar_system", "body": "pluto"}

    result = service.calculate_astronomical_relationship(task)

    assert result["ok"] is False
    assert result["error"] == "unsupported_solar_system_body"
    assert result["run_id"]
    assert "output_dir" not in result


def test_image_tool_writes_provenance_as_a_server_resource(tmp_path) -> None:
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
        image_backend_factory=StaticImageBackend,
        clock=lambda: datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc),
    )

    result = service.fetch_m51_sdss_image()

    assert result["ok"] is True
    assert result["from_cache"] is False
    assert result["resources"]["image-metadata"] == (
        f"starskill://runs/{result['run_id']}/image-metadata"
    )
    assert "SDSS SkyServer" in service.read_run_resource(
        result["run_id"], "image-metadata"
    )


def test_run_resources_reject_path_traversal(tmp_path) -> None:
    service = StarSkillMcpService(
        runs_root=tmp_path / "runs",
        target_cache_dir=tmp_path / "target-cache",
        image_cache_dir=tmp_path / "image-cache",
    )

    with pytest.raises(ValueError, match="run_id"):
        service.read_run_resource("../outside", "report")
    with pytest.raises(ValueError, match="resource"):
        service.read_run_resource("20260723T080000Z-observation-0123456789ab", "../report")


def test_recommendation_writes_only_allowlisted_resources(tmp_path) -> None:
    service = make_service_with_fake_outreach_providers(tmp_path)

    result = service.recommend_tonight(load_observation_payload())

    assert result["ok"] is True
    assert result["resources"]["recommendation"].endswith("/recommendation")
    assert "天气预报" in service.read_run_resource(result["run_id"], "conditions")
    assert result["result"] == json.loads(
        service.read_run_resource(result["run_id"], "recommendation")
    )


def test_outreach_tools_validate_and_write_server_owned_resources(tmp_path) -> None:
    service = make_service_with_fake_outreach_providers(tmp_path)

    invalid = service.get_observing_conditions({"observer": {}})
    conditions = service.get_observing_conditions(
        {
            "observer": load_observation_payload()["observer"],
            "time_range": load_observation_payload()["time_range"],
        }
    )
    nasa = service.get_nasa_feature("2026-07-23")
    stellarium = service.sync_stellarium(
        {
            "observer": load_observation_payload()["observer"],
            "timestamp": "2026-07-23T20:00:00+08:00",
            "target": "M 42",
        }
    )

    assert invalid["error"] == "validation_error"
    assert conditions["resources"]["conditions"].endswith("/conditions")
    assert nasa["result"]["title"] == "Test APOD"
    assert nasa["resources"]["nasa-feature"].endswith("/nasa-feature")
    assert stellarium["result"]["ok"] is True
    assert stellarium["result"]["operations"] == ["status", "location", "time", "focus"]
    assert stellarium["resources"]["stellarium-sync"].endswith("/stellarium-sync")
    assert stellarium["result"] == json.loads(
        service.read_run_resource(stellarium["run_id"], "stellarium-sync")
    )


def test_malformed_stellarium_bridge_output_is_not_persisted(tmp_path) -> None:
    service = make_service_with_fake_outreach_providers(
        tmp_path,
        stellarium_bridge_factory=MalformedStellariumBridge,
    )

    result = service.sync_stellarium(
        {
            "observer": load_observation_payload()["observer"],
            "timestamp": "2026-07-23T20:00:00+08:00",
            "target": "M 42",
        }
    )

    assert result["ok"] is False
    assert "stellarium-sync" not in result["resources"]


def test_stdio_server_advertises_supported_tools_and_run_resources(tmp_path) -> None:
    async def check_server() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "starskill.mcp_server"],
            cwd=Path(__file__).resolve().parents[1],
            env={
                "STARSKILL_RUNS_DIR": str(tmp_path / "runs"),
                "STARSKILL_TARGET_CACHE_DIR": str(tmp_path / "target-cache"),
                "STARSKILL_IMAGE_CACHE_DIR": str(tmp_path / "image-cache"),
                "PYTHONPATH": os.pathsep.join(
                    filter(None, [str(PROJECT_ROOT / "src"), os.environ.get("PYTHONPATH")])
                ),
            },
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                templates = await session.list_resource_templates()

        assert {tool.name for tool in tools.tools} == {
            "validate_observation_task",
            "resolve_astronomy_target",
            "plan_observation",
            "calculate_moon_jupiter_relationship",
            "calculate_astronomical_relationship",
            "fetch_m51_sdss_image",
            "get_observing_conditions",
            "recommend_tonight",
            "get_nasa_feature",
            "sync_stellarium",
        }
        assert [template.uriTemplate for template in templates.resourceTemplates] == [
            "starskill://runs/{run_id}/{resource}"
        ]

    anyio.run(check_server)


def test_mcp_server_reads_the_optional_local_stellarium_url(monkeypatch) -> None:
    from starskill.mcp_server import service_from_environment

    monkeypatch.setenv("STARSKILL_STELLARIUM_BASE_URL", "http://localhost:8090")

    bridge = service_from_environment().stellarium_bridge_factory()

    assert bridge._base_url == "http://localhost:8090"


def test_mcp_server_keeps_the_default_loopback_bridge_without_environment(
    monkeypatch,
) -> None:
    from starskill.mcp_server import service_from_environment
    from starskill.stellarium_bridge import DEFAULT_BASE_URL

    monkeypatch.delenv("STARSKILL_STELLARIUM_BASE_URL", raising=False)
    service = service_from_environment()

    assert service.stellarium_bridge_factory()._base_url == DEFAULT_BASE_URL
    assert service.validate_observation_task(load_observation_payload())["ok"] is True
