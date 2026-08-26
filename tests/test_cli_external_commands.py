"""CLI coverage for the external-evidence commands and the uniform envelope."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from starskill import cli
from starskill.cli import main
from starskill.schemas import (
    ExternalSource,
    NasaFeature,
    WeatherForecast,
    WeatherSample,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENVELOPE_KEYS = {
    "envelope_version",
    "status",
    "workflow",
    "summary",
    "artifacts",
    "sources",
    "human_review",
}


def write_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def conditions_request() -> dict[str, object]:
    return {
        "observer": {
            "location_name": "北京",
            "longitude": 116.4074,
            "latitude": 39.9042,
            "timezone": "Asia/Shanghai",
        },
        "time_range": {
            "start": "2026-01-05T19:00:00",
            "end": "2026-01-06T02:00:00",
        },
    }


def fresh_forecast() -> WeatherForecast:
    return WeatherForecast(
        samples=[
            WeatherSample(
                timestamp_local=datetime(
                    2026, 1, 5, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
                cloud_cover_percent=20.0,
                precipitation_mm=0.0,
                wind_speed_kmh=8.0,
                visibility_m=20000.0,
            )
        ],
        source=ExternalSource(
            provider="Open-Meteo",
            source_url="https://api.open-meteo.com/v1/forecast?stub",
            accessed_at=datetime.now(timezone.utc),
            from_cache=False,
            availability="fresh",
        ),
    )


class StubWeatherProvider:
    forecast: WeatherForecast | None = None
    raises: bool = False

    def __init__(self, *, cache_dir: Path, **_kwargs: object) -> None:
        self.cache_dir = cache_dir

    def get_forecast(self, request: object) -> WeatherForecast:
        if type(self).raises or type(self).forecast is None:
            raise RuntimeError("stub weather failure")
        return type(self).forecast


class StubSimbadBackend:
    service_url = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

    def query_object(self, query_name: str) -> dict[str, object]:
        return {
            "canonical_name": "M 42",
            "ra_deg": 83.822083,
            "dec_deg": -5.391111,
            "object_type": "HII",
            "aliases": ["M 42", "NGC 1976", "Orion Nebula"],
        }


class StubImageBackend:
    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> tuple[bytes, str]:
        image = Image.new("RGB", (512, 512), "#101820")
        draw = ImageDraw.Draw(image)
        draw.ellipse((100, 80, 410, 430), fill="#d9e5f2")
        output = BytesIO()
        image.save(output, format="JPEG", quality=90)
        return output.getvalue(), "image/jpeg"


def assert_envelope(payload: dict[str, object], workflow: str, status: str) -> None:
    assert ENVELOPE_KEYS <= set(payload)
    assert payload["envelope_version"] == "1.0"
    assert payload["status"] == status
    assert payload["workflow"] == workflow


def test_conditions_writes_forecast_and_uniform_envelope(
    tmp_path, capsys, monkeypatch
) -> None:
    StubWeatherProvider.forecast = fresh_forecast()
    StubWeatherProvider.raises = False
    monkeypatch.setattr(cli, "OpenMeteoWeatherProvider", StubWeatherProvider)
    input_path = write_json(tmp_path / "request.json", conditions_request())
    output_path = tmp_path / "conditions.json"

    exit_code = main(
        [
            "conditions",
            str(input_path),
            "--output",
            str(output_path),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert_envelope(payload, "conditions", "success")
    assert payload["summary"]["sample_count"] == 1
    assert payload["summary"]["availability"] == "fresh"
    assert payload["sources"][0]["provider"] == "Open-Meteo"
    assert payload["artifacts"][0]["path"] == str(output_path)
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    assert stored["source"]["availability"] == "fresh"


def test_conditions_provider_failure_is_degraded_not_fabricated(
    tmp_path, capsys, monkeypatch
) -> None:
    StubWeatherProvider.raises = True
    monkeypatch.setattr(cli, "OpenMeteoWeatherProvider", StubWeatherProvider)
    input_path = write_json(tmp_path / "request.json", conditions_request())
    output_path = tmp_path / "conditions.json"

    exit_code = main(["conditions", str(input_path), "--output", str(output_path)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 5
    assert_envelope(payload, "conditions", "degraded")
    assert payload["summary"]["sample_count"] == 0
    assert payload["summary"]["issue_code"] == "weather_provider_error"
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    assert stored["samples"] == []
    assert stored["source"]["availability"] == "unavailable"


def test_conditions_rejects_invalid_request(tmp_path, capsys) -> None:
    request = conditions_request()
    request["observer"]["latitude"] = 200
    input_path = write_json(tmp_path / "request.json", request)

    exit_code = main(
        ["conditions", str(input_path), "--output", str(tmp_path / "out.json")]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert payload["status"] == "failed"
    assert payload["workflow"] == "conditions"
    assert payload["error"] == "validation_error"
    assert not (tmp_path / "out.json").exists()


def test_apod_without_api_key_is_degraded(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("STARSKILL_NASA_API_KEY", raising=False)
    output_path = tmp_path / "nasa_feature.json"

    exit_code = main(
        ["apod", "--output", str(output_path), "--cache-dir", str(tmp_path / "cache")]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 5
    assert_envelope(payload, "apod", "degraded")
    assert payload["summary"]["issue_code"] == "nasa_api_key_missing"
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    assert stored["source"]["availability"] == "unavailable"


def test_apod_rejects_invalid_date_without_network(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setenv("STARSKILL_NASA_API_KEY", "stub-key")

    exit_code = main(
        [
            "apod",
            "--date",
            "2026-13-99",
            "--output",
            str(tmp_path / "nasa_feature.json"),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert payload["error"] == "validation_error"
    assert payload["details"][0]["location"] == ["date"]
    assert not (tmp_path / "nasa_feature.json").exists()
    assert "stub-key" not in json.dumps(payload)


def test_apod_success_uses_provider_result(tmp_path, capsys, monkeypatch) -> None:
    feature = NasaFeature(
        date="2026-01-05",
        title="Orion in Gas and Dust",
        media_type="image",
        media_url="https://apod.nasa.gov/apod/image/stub.jpg",
        explanation="stub",
        source=ExternalSource(
            provider="NASA APOD",
            source_url="https://api.nasa.gov/planetary/apod?date=2026-01-05",
            accessed_at=datetime.now(timezone.utc),
            from_cache=False,
            availability="fresh",
        ),
    )

    class StubNasaProvider:
        def __init__(self, *, api_key: str | None, cache_dir: Path, **_kw: object) -> None:
            self.api_key = api_key

        def get_feature(self, date: str | None) -> NasaFeature:
            return feature

    monkeypatch.setattr(cli, "NasaApodProvider", StubNasaProvider)
    output_path = tmp_path / "nasa_feature.json"

    exit_code = main(["apod", "--date", "2026-01-05", "--output", str(output_path)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert_envelope(payload, "apod", "success")
    assert payload["summary"]["title"] == "Orion in Gas and Dust"
    assert json.loads(output_path.read_text(encoding="utf-8"))["date"] == "2026-01-05"


def test_recommend_combines_geometry_weather_and_light_pollution(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "SimbadBackend", StubSimbadBackend)
    StubWeatherProvider.forecast = fresh_forecast()
    StubWeatherProvider.raises = False
    monkeypatch.setattr(cli, "OpenMeteoWeatherProvider", StubWeatherProvider)
    output_dir = tmp_path / "recommendation-run"

    exit_code = main(
        [
            "recommend",
            str(PROJECT_ROOT / "examples/observation_m42_beijing.json"),
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--weather-cache-dir",
            str(tmp_path / "weather-cache"),
            "--light-pollution-snapshot",
            str(PROJECT_ROOT / "tests/fixtures/black_marble_snapshot.json"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert_envelope(payload, "recommend", "success")
    assert payload["summary"]["pipeline_status"] == "success"
    assert payload["summary"]["weather_availability"] == "fresh"
    assert payload["summary"]["light_pollution_availability"] in ("fresh", "cached")
    assert payload["human_review"]
    assert len(payload["sources"]) == 2
    recommendation = json.loads(
        (output_dir / "recommendation.json").read_text(encoding="utf-8")
    )
    assert recommendation["human_review"]
    assert (output_dir / "conditions.json").is_file()
    assert (output_dir / "run.json").is_file()


def test_recommend_with_unavailable_weather_is_degraded(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "SimbadBackend", StubSimbadBackend)
    StubWeatherProvider.raises = True
    monkeypatch.setattr(cli, "OpenMeteoWeatherProvider", StubWeatherProvider)
    output_dir = tmp_path / "degraded-recommendation"

    exit_code = main(
        [
            "recommend",
            str(PROJECT_ROOT / "examples/observation_m42_beijing.json"),
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--light-pollution-snapshot",
            str(tmp_path / "missing-snapshot.json"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 5
    assert_envelope(payload, "recommend", "degraded")
    assert payload["summary"]["weather_availability"] == "unavailable"
    assert payload["summary"]["light_pollution_availability"] == "unavailable"
    recommendation = json.loads(
        (output_dir / "recommendation.json").read_text(encoding="utf-8")
    )
    assert recommendation["weather_forecast"]["samples"] == []


def test_stellarium_sync_success_writes_outcome(tmp_path, capsys, monkeypatch) -> None:
    class StubBridge:
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

        def sync(self, request: object) -> dict[str, object]:
            return {
                "ok": True,
                "base_url": "http://127.0.0.1:8090",
                "operations": ["status", "location", "time", "focus"],
                "error": None,
            }

    monkeypatch.setattr(cli, "StellariumBridge", StubBridge)
    input_path = write_json(
        tmp_path / "sync.json",
        {
            "observer": conditions_request()["observer"],
            "timestamp": "2026-01-05T20:00:00+08:00",
            "target": "M42",
        },
    )
    output_path = tmp_path / "stellarium_sync.json"

    exit_code = main(
        ["stellarium-sync", str(input_path), "--output", str(output_path)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert_envelope(payload, "stellarium-sync", "success")
    assert payload["summary"]["operations"] == ["status", "location", "time", "focus"]
    assert payload["synced"] is True
    assert json.loads(output_path.read_text(encoding="utf-8"))["ok"] is True


def test_stellarium_sync_connection_failure_returns_exit_10(
    tmp_path, capsys, monkeypatch
) -> None:
    class StubBridge:
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

        def sync(self, request: object) -> dict[str, object]:
            return {
                "ok": False,
                "base_url": "http://127.0.0.1:8090",
                "operations": ["status"],
                "error": "connection_error",
            }

    monkeypatch.setattr(cli, "StellariumBridge", StubBridge)
    input_path = write_json(
        tmp_path / "sync.json",
        {
            "observer": conditions_request()["observer"],
            "timestamp": "2026-01-05T20:00:00+08:00",
            "target": "M42",
        },
    )
    output_path = tmp_path / "stellarium_sync.json"

    exit_code = main(
        ["stellarium-sync", str(input_path), "--output", str(output_path)]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 10
    assert payload["status"] == "failed"
    assert payload["error"] == "connection_error"
    assert payload["operations"] == ["status"]
    assert json.loads(output_path.read_text(encoding="utf-8"))["ok"] is False


def test_stellarium_sync_rejects_non_loopback_base_url(
    tmp_path, capsys
) -> None:
    input_path = write_json(
        tmp_path / "sync.json",
        {
            "observer": conditions_request()["observer"],
            "timestamp": "2026-01-05T20:00:00+08:00",
            "target": "M42",
        },
    )

    exit_code = main(
        [
            "stellarium-sync",
            str(input_path),
            "--output",
            str(tmp_path / "sync-out.json"),
            "--base-url",
            "http://evil.example:8090",
        ]
    )
    payload = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert payload["error"] == "invalid_base_url"
    assert not (tmp_path / "sync-out.json").exists()


def test_fetch_image_generalizes_target_names(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "UrlImageBackend", StubImageBackend)
    input_path = write_json(
        tmp_path / "request.json",
        {"target_name": "NGC 4565", "ra_deg": 189.0866, "dec_deg": 25.9877},
    )
    output_dir = tmp_path / "image-run"

    exit_code = main(
        [
            "fetch-image",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert_envelope(payload, "fetch-image", "success")
    assert payload["summary"]["target_name"] == "NGC 4565"
    assert (output_dir / "data/ngc_4565_sdss.jpg").is_file()
    assert (output_dir / "figures/ngc_4565_display.png").is_file()
    assert (output_dir / "image_metadata.json").is_file()


def test_validate_success_uses_uniform_envelope(capsys) -> None:
    exit_code = main(
        ["validate", str(PROJECT_ROOT / "examples/observation_m42_beijing.json")]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert_envelope(payload, "validate", "success")
    assert payload["valid"] is True
    assert payload["summary"]["task_type"] == "observation_plan"
