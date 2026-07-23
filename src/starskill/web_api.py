"""Loopback-only HTTP transport for the StarSkill outreach workflows."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from datetime import date, datetime
from importlib.resources import files
import logging
import math
import re
from threading import Event, Thread
import time
from typing import Any
from urllib.request import urlopen
import webbrowser
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from starskill.mcp_server import StarSkillMcpService, service_from_environment
from starskill.schemas import SkyChartRenderResponse, SkyChartRequest
from starskill.sky_chart import RenderStore, SkyChartService
from starskill.sky_chart_catalog import FullCatalogUnavailableError


MAX_REQUEST_BODY_BYTES = 1024 * 1024
MAX_SKY_CHART_REQUEST_BODY_BYTES = 16 * 1024
_SKY_CHART_RENDER_PATH = "/v1/sky-chart/render"
_RENDER_ID_RE = re.compile(r"[A-Za-z0-9_-]{32}\Z")
_LOGGER = logging.getLogger(__name__)


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


def _client_host(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _load_page_html() -> str:
    try:
        return (
            files("starskill")
            .joinpath("static/sky_chart.html")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        _LOGGER.error("Packaged sky-chart page is unavailable")
        raise RuntimeError("Packaged sky-chart page is unavailable") from None


def create_web_app(
    service: StarSkillMcpService,
    sky_chart_service: SkyChartService,
    *,
    requests_per_minute: int = 60,
    sky_chart_requests_per_minute: int = 30,
    monotonic_clock: Callable[[], float] = time.monotonic,
    rate_limiter: FixedWindowRateLimiter | None = None,
    sky_chart_rate_limiter: FixedWindowRateLimiter | None = None,
) -> FastAPI:
    """Create a same-origin local web application with bounded HTTP inputs."""
    page_html = _load_page_html()
    limiter = rate_limiter or FixedWindowRateLimiter(
        requests_per_minute=requests_per_minute,
        monotonic_clock=monotonic_clock,
    )
    sky_limiter = sky_chart_rate_limiter or FixedWindowRateLimiter(
        requests_per_minute=sky_chart_requests_per_minute,
        monotonic_clock=monotonic_clock,
    )
    render_store = RenderStore(monotonic_clock=monotonic_clock)
    render_gate = asyncio.Semaphore(1)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        acquired = False
        try:
            await asyncio.wait_for(render_gate.acquire(), timeout=10)
            acquired = True
        except TimeoutError:
            pass
        finally:
            if acquired:
                render_gate.release()
            render_store.clear()

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.render_store = render_store

    @app.exception_handler(RequestValidationError)
    async def stable_sky_chart_validation(
        request: Request, exc: RequestValidationError
    ) -> Response:
        if request.url.path == _SKY_CHART_RENDER_PATH:
            return JSONResponse(
                status_code=422,
                content={"detail": "Invalid sky-chart request"},
            )
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def guard_local_requests(request: Request, call_next: Any) -> Any:
        is_sky_chart_render = (
            request.method == "POST" and request.url.path == _SKY_CHART_RENDER_PATH
        )
        if not is_sky_chart_render:
            allowed, retry_after = limiter.allow(_client_host(request))
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                    headers={"Retry-After": str(retry_after)},
                )

        body_limit = (
            MAX_SKY_CHART_REQUEST_BODY_BYTES
            if is_sky_chart_render
            else MAX_REQUEST_BODY_BYTES
        )
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=413, content={"detail": "Request body too large"}
                )
            if declared_length < 0 or declared_length > body_limit:
                return JSONResponse(
                    status_code=413, content={"detail": "Request body too large"}
                )

        if len(await request.body()) > body_limit:
            return JSONResponse(
                status_code=413, content={"detail": "Request body too large"}
            )
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

    @app.post("/v1/sky-chart/render", response_model=SkyChartRenderResponse)
    async def render_sky_chart(
        request_body: SkyChartRequest, request: Request
    ) -> SkyChartRenderResponse:
        if not sky_limiter.allow(_client_host(request))[0]:
            raise HTTPException(status_code=429, detail="Too many requests")
        try:
            await asyncio.wait_for(render_gate.acquire(), timeout=10)
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Renderer busy; retry shortly"
            ) from exc
        try:
            try:
                chart = await asyncio.to_thread(sky_chart_service.render, request_body)
                render_id = render_store.put(chart)
            except FullCatalogUnavailableError as exc:
                raise HTTPException(
                    status_code=422, detail="Invalid sky-chart request"
                ) from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(
                    status_code=500, detail="Internal server error"
                ) from exc
            return SkyChartRenderResponse(
                render_id=render_id,
                png_url=f"/v1/sky-chart/renders/{render_id}.png",
                json_url=f"/v1/sky-chart/renders/{render_id}.json",
                catalog_mode_used=chart.catalog_mode_used,
                catalog_status=chart.catalog_status,
                warnings=chart.metadata.warnings,
            )
        finally:
            render_gate.release()

    def stored_render(render_id: str):
        if not _RENDER_ID_RE.fullmatch(render_id):
            raise HTTPException(status_code=404, detail="Render not found")
        chart = render_store.get(render_id)
        if chart is None:
            raise HTTPException(status_code=404, detail="Render not found")
        return chart

    @app.get("/v1/sky-chart/renders/{render_id}.png")
    def export_sky_chart_png(render_id: str) -> Response:
        chart = stored_render(render_id)
        return Response(
            chart.png_bytes,
            media_type="image/png",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="starskill-sky-chart-{render_id}.png"'
                )
            },
        )

    @app.get("/v1/sky-chart/renders/{render_id}.json")
    def export_sky_chart_json(render_id: str) -> Response:
        chart = stored_render(render_id)
        return Response(
            chart.metadata_json_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="starskill-sky-chart-{render_id}.json"'
                )
            },
        )

    @app.get("/", response_class=HTMLResponse)
    def root() -> HTMLResponse:
        timestamp = (
            datetime.now(ZoneInfo("Asia/Shanghai"))
            .replace(second=0, microsecond=0)
            .isoformat()
        )
        return HTMLResponse(
            page_html.replace("__DEFAULT_TIMESTAMP_LOCAL__", timestamp),
            headers={"Cache-Control": "no-store"},
        )

    return app


def default_web_app() -> FastAPI:
    return create_web_app(service_from_environment(), SkyChartService())


def get_health_status(url: str) -> int:
    with urlopen(url, timeout=1) as response:
        return int(response.status)


def run_web_server(
    port: int,
    open_browser: bool,
    *,
    web_app_factory: Callable[[], FastAPI] = default_web_app,
    browser_open: Callable[[str], bool] = webbrowser.open,
    health_get: Callable[[str], int] = get_health_status,
) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("port must be in 1024..65535")

    app = web_app_factory()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    base_url = f"http://127.0.0.1:{port}/"
    stop_helper = Event()
    helper: Thread | None = None

    if open_browser:
        health_url = f"http://127.0.0.1:{port}/healthz"

        def open_after_health() -> None:
            while not stop_helper.is_set():
                if not server.started:
                    stop_helper.wait(0.05)
                    continue
                try:
                    healthy = health_get(health_url) == 200
                except Exception:
                    healthy = False
                if healthy:
                    try:
                        opened = browser_open(base_url)
                    except Exception:
                        opened = False
                    if not opened:
                        print(base_url)
                    return
                stop_helper.wait(0.1)

        helper = Thread(target=open_after_health, daemon=True, name="starskill-browser")
        helper.start()
    else:
        print(base_url)

    try:
        server.run()
    finally:
        stop_helper.set()
        if helper is not None:
            helper.join(timeout=1)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="starskill-web")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    run_web_server(args.port, open_browser=False)


if __name__ == "__main__":
    main()
