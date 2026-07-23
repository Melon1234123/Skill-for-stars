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
    assert result["resources"]["relationship"] == (
        f"starskill://runs/{result['run_id']}/relationship"
    )
    assert "angular_separation_deg" in service.read_run_resource(
        result["run_id"], "relationship"
    )


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
