"""Loopback-only HTTP transport for the StarSkill outreach workflows."""

import math
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from starskill.mcp_server import StarSkillMcpService, service_from_environment


MAX_REQUEST_BODY_BYTES = 1024 * 1024


class TonightRecommendationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: dict[str, Any]
    min_target_altitude_deg: float = Field(default=30.0)
    max_sun_altitude_deg: float = Field(default=-12.0)


class FixedWindowRateLimiter:
    """Bound local-client requests using an injected monotonic clock."""

    def __init__(
        self,
        *,
        requests_per_minute: int,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be positive")
        self.requests_per_minute = requests_per_minute
        self.monotonic_clock = monotonic_clock
        self._requests: dict[tuple[str, int], int] = {}

    def allow(self, client_host: str) -> tuple[bool, int]:
        now = self.monotonic_clock()
        window = math.floor(now / 60)
        key = (client_host, window)
        count = self._requests.get(key, 0)
        retry_after = max(1, math.ceil((window + 1) * 60 - now))
        if count >= self.requests_per_minute:
            return False, retry_after
        self._requests[key] = count + 1
        return True, retry_after


def _response_result(outcome: dict[str, Any]) -> JSONResponse:
    if outcome.get("ok") is False:
        if outcome.get("error") == "validation_error":
            return JSONResponse(status_code=422, content={"detail": "Invalid request"})
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    result = outcome.get("result")
    if not isinstance(result, dict):
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    return JSONResponse(status_code=200, content=result)


def _internal_error_response() -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def create_web_app(
    service: StarSkillMcpService,
    frontend_dir: Path,
    *,
    requests_per_minute: int = 60,
    monotonic_clock: Callable[[], float] = time.monotonic,
    rate_limiter: FixedWindowRateLimiter | None = None,
) -> FastAPI:
    """Create a same-origin local web application with bounded HTTP inputs."""
    limiter = rate_limiter or FixedWindowRateLimiter(
        requests_per_minute=requests_per_minute,
        monotonic_clock=monotonic_clock,
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard_local_requests(request: Request, call_next: Any) -> Any:
        client_host = request.client.host if request.client is not None else "unknown"
        allowed, retry_after = limiter.allow(client_host)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(retry_after)},
            )

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})
            if declared_length > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})

        if len(await request.body()) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        return await call_next(request)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/conditions")
    def conditions(request_body: dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            return _response_result(service.get_observing_conditions(request_body))
        except Exception:
            return _internal_error_response()

    @app.post("/v1/recommendations/tonight")
    def tonight(request_body: TonightRecommendationBody) -> JSONResponse:
        try:
            return _response_result(
                service.recommend_tonight(
                    request_body.task,
                    min_target_altitude_deg=request_body.min_target_altitude_deg,
                    max_sun_altitude_deg=request_body.max_sun_altitude_deg,
                )
            )
        except Exception:
            return _internal_error_response()

    @app.get("/v1/nasa/apod")
    def nasa_apod(date_value: date | None = Query(default=None, alias="date")) -> JSONResponse:
        try:
            return _response_result(
                service.get_nasa_feature(
                    None if date_value is None else date_value.isoformat()
                )
            )
        except Exception:
            return _internal_error_response()

    @app.post("/v1/stellarium/sync")
    def stellarium_sync(request_body: dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            outcome = service.sync_stellarium(request_body)
            result = outcome.get("result")
            if isinstance(result, dict):
                outcome = {
                    **outcome,
                    "result": {
                        key: value for key, value in result.items() if key != "base_url"
                    },
                }
            return _response_result(outcome)
        except Exception:
            return _internal_error_response()

    # API routes must remain above this mount so static files never shadow them.
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


def main() -> None:
    frontend_dir = Path(__file__).resolve().parents[2] / "web" / "dist"
    if not frontend_dir.is_dir():
        raise FileNotFoundError(f"Required frontend distribution is missing: {frontend_dir}")
    uvicorn.run(
        create_web_app(service_from_environment(), frontend_dir=frontend_dir),
        host="127.0.0.1",
    )


if __name__ == "__main__":
    main()
