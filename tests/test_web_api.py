from pathlib import Path

from fastapi.testclient import TestClient

from starskill.web_api import FixedWindowRateLimiter, create_web_app
from tests.test_mcp_server import (
    load_observation_payload,
    make_service_with_fake_outreach_providers,
)


class BrokenService:
    def get_observing_conditions(self, request: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("cache directory /private/config should not be exposed")


def test_web_app_does_not_enable_cors_for_a_foreign_origin(tmp_path: Path) -> None:
    client = TestClient(
        create_web_app(
            make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path
        )
    )

    response = client.get("/healthz", headers={"Origin": "https://foreign.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_web_api_returns_human_review_without_transport_metadata(tmp_path: Path) -> None:
    client = TestClient(
        create_web_app(
            make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path
        )
    )

    response = client.post(
        "/v1/recommendations/tonight", json={"task": load_observation_payload()}
    )

    assert response.status_code == 200
    assert response.json()["human_review"]
    assert "run_id" not in response.json()
    assert "resources" not in response.json()


def test_web_api_returns_422_for_invalid_service_input(tmp_path: Path) -> None:
    client = TestClient(
        create_web_app(
            make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path
        )
    )

    response = client.post("/v1/conditions", json={"observer": {}})

    assert response.status_code == 422


def test_web_api_returns_429_after_the_configured_client_limit(tmp_path: Path) -> None:
    now = [100.0]
    limiter = FixedWindowRateLimiter(
        requests_per_minute=1, monotonic_clock=lambda: now[0]
    )
    client = TestClient(
        create_web_app(
            make_service_with_fake_outreach_providers(tmp_path),
            frontend_dir=tmp_path,
            rate_limiter=limiter,
        )
    )

    assert client.get("/healthz").status_code == 200
    limited = client.get("/healthz")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "20"

    now[0] = 120.0
    assert client.get("/healthz").status_code == 200


def test_web_api_rejects_bodies_larger_than_one_mib(tmp_path: Path) -> None:
    client = TestClient(
        create_web_app(
            make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path
        )
    )

    response = client.post(
        "/v1/conditions",
        content=b'{"observer":"' + b"x" * (1024 * 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413


def test_web_api_returns_generic_500_for_unexpected_errors(tmp_path: Path) -> None:
    client = TestClient(create_web_app(BrokenService(), frontend_dir=tmp_path))

    response = client.post("/v1/conditions", json={})

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "private" not in response.text


def test_web_api_validates_nasa_date_before_calling_service(tmp_path: Path) -> None:
    client = TestClient(
        create_web_app(
            make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path
        )
    )

    response = client.get("/v1/nasa/apod?date=not-a-date")

    assert response.status_code == 422


def test_web_api_does_not_return_the_desktop_stellarium_url(tmp_path: Path) -> None:
    client = TestClient(
        create_web_app(
            make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path
        )
    )
    task = load_observation_payload()

    response = client.post(
        "/v1/stellarium/sync",
        json={
            "observer": task["observer"],
            "timestamp": "2026-07-23T20:00:00+08:00",
            "target": "M 42",
        },
    )

    assert response.status_code == 200
    assert "base_url" not in response.json()
