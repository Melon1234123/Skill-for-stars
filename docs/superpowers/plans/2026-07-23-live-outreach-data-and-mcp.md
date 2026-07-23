# StarSkill Live Outreach Data and MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add auditable weather, static light-pollution, NASA APOD, local Stellarium bridge, and tonight-recommendation capabilities to the Python domain and stdio MCP server.

**Architecture:** Strict Pydantic result models define every provider outcome. Small injected adapters use bounded JSON transport and deterministic fakes in tests. A conservative rule engine joins existing Astropy geometry with the provider results; FastAPI hosts the built browser app and same-origin API on loopback while MCP remains local stdio.

**Tech Stack:** Python 3.11+, Pydantic 2, stdlib `urllib`, Astropy, FastMCP, FastAPI, Uvicorn, pytest, AnyIO.

## Global Constraints

- Keep `starskill-mcp` on stdio. `starskill-web` hosts the browser app and API only on `127.0.0.1`; neither is a public service.
- Tests use fakes and fixtures only. Live services are optional smoke checks.
- Every external result includes provider, source URL, access time, cache state, and availability.
- Weather is a forecast. Static radiance is not a Bortle class. Neither proves site safety.
- NASA credentials use `STARSKILL_NASA_API_KEY` only and never enter logs or artifacts.
- Stellarium defaults to `http://127.0.0.1:8090`; non-loopback access requires explicit configuration.
- Recommendations always include weather, horizon, equipment, and safety human-review items.

---

### Task 1: Define the outreach result contracts

**Files:**
- Modify: `pyproject.toml:11-31`
- Modify: `src/starskill/schemas.py:1-246`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Produces `ObservingConditionsRequest`, `WeatherForecast`, `LightPollutionResult`, `NasaFeature`, `TonightRecommendationRequest`, `TonightRecommendationResult`, and `StellariumSyncRequest`.
- Produces `starskill-web = "starskill.web_api:main"`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_tonight_request_has_conservative_defaults(valid_payload: dict) -> None:
    request = TonightRecommendationRequest.model_validate({"task": valid_payload})
    assert request.min_target_altitude_deg == 30.0
    assert request.max_sun_altitude_deg == -12.0


def test_conditions_request_rejects_an_empty_time_range(valid_payload: dict) -> None:
    with pytest.raises(ValidationError, match="end"):
        ObservingConditionsRequest.model_validate({
            "observer": valid_payload["observer"],
            "time_range": {"start": "2026-01-10T20:00:00+08:00", "end": "2026-01-10T20:00:00+08:00"},
        })
```

- [ ] **Step 2: Confirm the models do not exist yet**

Run: `pytest tests/test_schemas.py -q`

Expected: FAIL during collection because the new types are absent.

- [ ] **Step 3: Add exact models and package entries**

Append these definitions, reusing the existing `InputModel`, `Observer`, `TimeRange`, `ObservationTask`, and `ObservationPlanResult`:

```python
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
```

Add `fastapi>=0.115,<1`, `uvicorn>=0.30,<1`, `httpx>=0.27,<1` in the appropriate dependency lists and `starskill-web = "starskill.web_api:main"` in the scripts table.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_schemas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add pyproject.toml src/starskill/schemas.py tests/test_schemas.py`, then create commit `feat: define outreach data contracts`.

### Task 2: Build bounded JSON transport and cache records

**Files:**
- Create: `src/starskill/external_data.py`
- Test: `tests/test_external_data.py`

**Interfaces:**
- Produces `JsonBackend`, `UrlJsonBackend`, `ExternalDataError`, `read_cache_record()`, and `write_cache_record()`.

- [ ] **Step 1: Write failing transport tests**

```python
def test_cache_expires_without_returning_stale_payload(tmp_path) -> None:
    path = tmp_path / "weather.json"
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    write_cache_record(path, {"hourly": {"time": []}}, now)
    assert read_cache_record(path, now + timedelta(minutes=29), timedelta(minutes=30)) == {"hourly": {"time": []}}
    assert read_cache_record(path, now + timedelta(minutes=31), timedelta(minutes=30)) is None


def test_backend_rejects_a_non_object_json_response() -> None:
    backend = UrlJsonBackend(opener=lambda request, timeout: FakeResponse(b"[]", "application/json"))
    with pytest.raises(ExternalDataFormatError, match="JSON object"):
        backend.fetch_json("https://example.test", timeout_seconds=1, max_bytes=100)
```

- [ ] **Step 2: Confirm tests fail before the module exists**

Run: `pytest tests/test_external_data.py -q`

Expected: FAIL during collection.

- [ ] **Step 3: Implement bounded transport**

Implement `ExternalDataError`, `ExternalDataNetworkError(code="external_data_network_error")`, `ExternalDataSizeError(code="external_data_size_limit")`, and `ExternalDataFormatError(code="external_data_invalid_response")`. Define `JsonBackend.fetch_json(url, *, timeout_seconds, max_bytes) -> dict[str, Any]`. `UrlJsonBackend` sends `Accept: application/json` and the existing StarSkill user agent, rejects declared or actual bodies over `max_bytes`, requires `application/json`, parses UTF-8 JSON, and accepts only a top-level object. Retry only one time after `URLError` or HTTP 502/503/504; never retry a validation, size, or other 4xx error. Map exhausted retry failures to the network error without recording response bodies.

Implement `read_cache_record(path, now, ttl)` using a JSON object `{ "cached_at": <ISO datetime>, "payload": <object> }`; it returns `None` for no file, invalid content, naive cache time, or expiry. `write_cache_record()` creates parent directories and writes sorted UTF-8 JSON.

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_external_data.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add src/starskill/external_data.py tests/test_external_data.py`, then create commit `feat: add bounded external JSON transport`.

### Task 3: Implement Open-Meteo weather evidence

**Files:**
- Create: `src/starskill/weather.py`
- Test: `tests/test_weather.py`

**Interfaces:**
- Consumes Task 1 models and Task 2 JSON transport.
- Produces `OpenMeteoWeatherProvider.get_forecast(request: ObservingConditionsRequest) -> WeatherForecast`.

- [ ] **Step 1: Write failing weather tests with an injected backend**

```python
def test_weather_provider_maps_hourly_values_and_reuses_cache(tmp_path, fixed_clock) -> None:
    backend = StaticJsonBackend({"hourly": {"time": ["2026-01-10T20:00"], "cloud_cover": [24], "precipitation": [0.0], "wind_speed_10m": [7.2], "visibility": [12000]}})
    provider = OpenMeteoWeatherProvider(backend=backend, cache_dir=tmp_path, clock=fixed_clock)
    assert provider.get_forecast(make_conditions_request()).samples[0].visibility_m == 12000
    assert provider.get_forecast(make_conditions_request()).source.availability == "cached"
    assert backend.calls == 1


def test_weather_provider_reports_a_network_failure_as_unavailable(tmp_path, fixed_clock) -> None:
    result = OpenMeteoWeatherProvider(backend=FailingJsonBackend(), cache_dir=tmp_path, clock=fixed_clock).get_forecast(make_conditions_request())
    assert result.samples == []
    assert result.source.issue_code == "external_data_network_error"
```

- [ ] **Step 2: Confirm tests fail before the module exists**

Run: `pytest tests/test_weather.py -q`

Expected: FAIL during collection.

- [ ] **Step 3: Implement provider semantics**

Set `OPEN_METEO_ENDPOINT = "https://api.open-meteo.com/v1/forecast"`. Use `urlencode` with latitude, longitude, observer IANA timezone, start/end dates, and exactly `hourly=cloud_cover,precipitation,wind_speed_10m,visibility`. Cache SHA-256 of the full URL for 30 minutes. Zip `hourly.time` and returned arrays, attach observer timezone to naive timestamps, and map absent optional values to `None`. A mismatched array length is unavailable with code `external_data_invalid_response`. Any `ExternalDataError` returns no samples and an unavailable `ExternalSource`; never synthesize clear weather.

- [ ] **Step 4: Run focused and regression tests**

Run: `pytest tests/test_weather.py tests/test_schemas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add src/starskill/weather.py tests/test_weather.py`, then create commit `feat: add auditable weather forecasts`.

### Task 4: Implement static Black Marble data and NASA APOD

**Files:**
- Create: `src/starskill/light_pollution.py`
- Create: `src/starskill/nasa.py`
- Create: `tests/fixtures/black_marble_snapshot.json`
- Test: `tests/test_light_pollution.py`
- Test: `tests/test_nasa.py`

**Interfaces:**
- Produces `BlackMarbleLightPollutionProvider.lookup(observer: Observer) -> LightPollutionResult` and `NasaApodProvider.get_feature(date: str | None) -> NasaFeature`.

- [ ] **Step 1: Write failing provider tests**

```python
def test_black_marble_provider_uses_the_nearest_snapshot_cell(fixed_clock) -> None:
    result = BlackMarbleLightPollutionProvider(snapshot_path=FIXTURE, clock=fixed_clock).lookup(make_observer(116.4, 39.9))
    assert (result.radiance, result.dataset_id, result.interpolation) == (18.5, "VNP46A4", "nearest_snapshot_cell")


def test_missing_snapshot_is_unavailable(tmp_path, fixed_clock) -> None:
    result = BlackMarbleLightPollutionProvider(snapshot_path=tmp_path / "missing.json", clock=fixed_clock).lookup(make_observer())
    assert result.radiance is None
    assert result.source.availability == "unavailable"


def test_apod_never_calls_network_without_a_key(fixed_clock) -> None:
    backend = StaticJsonBackend({})
    result = NasaApodProvider(api_key=None, backend=backend, clock=fixed_clock).get_feature(None)
    assert (result.source.issue_code, backend.calls) == ("nasa_api_key_missing", 0)
```

- [ ] **Step 2: Confirm tests fail before modules exist**

Run: `pytest tests/test_light_pollution.py tests/test_nasa.py -q`

Expected: FAIL during collection.

- [ ] **Step 3: Implement static snapshot reader**

Read a UTF-8 JSON object no larger than 5 MB with exact fields `dataset_id`, `dataset_version`, `sample_period`, `spatial_resolution`, `unit`, `source_url`, and nonempty `cells`. Each cell has `longitude`, `latitude`, and nonnegative `radiance`. Select the minimum squared latitude/longitude distance and record `interpolation="nearest_snapshot_cell"`. Missing, malformed, oversized, or empty inputs return unavailable with `light_pollution_snapshot_unavailable` or `light_pollution_snapshot_invalid`, without real-time or Bortle wording.

- [ ] **Step 4: Implement APOD provider**

Set `NASA_APOD_ENDPOINT = "https://api.nasa.gov/planetary/apod"`. A configured injected key permits `api_key` and optional ISO `date`, valid results cache for 24 hours, and required upstream fields are `date`, `title`, `media_type`, and `url`. Map `url` to `media_url`, preserve optional `explanation` and `copyright`, and return an unavailable `NasaFeature` for missing key, transport error, or malformed response.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_light_pollution.py tests/test_nasa.py -q`

Expected: PASS.

Run `git add src/starskill/light_pollution.py src/starskill/nasa.py tests/fixtures/black_marble_snapshot.json tests/test_light_pollution.py tests/test_nasa.py`, then create commit `feat: add static light and NASA content providers`.

### Task 5: Add recommendations and loopback Stellarium bridge

**Files:**
- Create: `src/starskill/recommendations.py`
- Create: `src/starskill/stellarium_bridge.py`
- Modify: `src/starskill/pipeline.py:20-170`
- Test: `tests/test_recommendations.py`
- Test: `tests/test_stellarium_bridge.py`

**Interfaces:**
- Produces `recommend_tonight(geometry, weather, light_pollution) -> TonightRecommendationResult` and `StellariumBridge.sync(request: StellariumSyncRequest) -> dict[str, object]`.

- [ ] **Step 1: Write failing rule and security tests**

```python
def test_recommendation_downgrades_heavy_cloud() -> None:
    result = recommend_tonight(make_plan(), make_weather(92, 0), make_light())
    assert result.recommendations[0].grade == "not_recommended"
    assert "云量预报 92%" in result.recommendations[0].reasons
    assert result.human_review


def test_unavailable_weather_cannot_upgrade_a_window() -> None:
    result = recommend_tonight(make_plan(), unavailable_weather(), unavailable_light())
    assert result.recommendations[0].grade == "caution"
    assert "天气预报不可用" in result.recommendations[0].reasons


def test_bridge_rejects_non_loopback_addresses() -> None:
    with pytest.raises(ValueError, match="loopback"):
        StellariumBridge(base_url="http://192.168.1.8:8090", backend=StaticJsonBackend({}))
```

- [ ] **Step 2: Confirm tests fail before modules exist**

Run: `pytest tests/test_recommendations.py tests/test_stellarium_bridge.py -q`

Expected: FAIL during collection.

- [ ] **Step 3: Implement deterministic grades**

Create `HUMAN_REVIEW_ITEMS` from the four existing review-checklist items and import it into `pipeline.py` to avoid drift. For each geometry window, use inclusive matching weather samples: unavailable means `caution` and `天气预报不可用，候选窗口仅基于几何条件`; cloud cover at least 85% or positive precipitation means `not_recommended`; cloud cover at least 60% means `caution`; otherwise `recommended`. Append either `静态环境亮度指标：<radiance> <unit>` or `光害静态指标不可用`; radiance never upgrades a grade.

- [ ] **Step 4: Implement fixed RemoteControl operations**

Permit only localhost/127.0.0.1 port 8090 unless explicit `allow_non_loopback=True`. Use `GET /api/main/status`, `POST /api/location/setlocationfields`, `POST /api/main/time`, and `POST /api/main/focus`. Send URL-encoded latitude, longitude, name, `planet=Earth`, `time=Time(request.timestamp).jd`, `timerate=0`, target, and `mode=center`. Return `{ok, base_url, operations, error}` and make connection errors structured false outcomes. Test exact paths and form data against a fake backend.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_recommendations.py tests/test_stellarium_bridge.py tests/test_pipeline.py -q`

Expected: PASS.

Run `git add src/starskill/recommendations.py src/starskill/stellarium_bridge.py src/starskill/pipeline.py tests/test_recommendations.py tests/test_stellarium_bridge.py tests/test_pipeline.py`, then create commit `feat: recommend tonight and bridge Stellarium`.

### Task 6: Extend MCP, safe run resources, and stdio discovery

**Files:**
- Modify: `src/starskill/mcp_server.py:1-315`
- Modify: `docs/mcp-server.md:1-75`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Produces MCP tools `get_observing_conditions`, `recommend_tonight`, `get_nasa_feature`, and `sync_stellarium`.

- [ ] **Step 1: Write failing MCP tests**

```python
def test_recommendation_writes_only_allowlisted_resources(tmp_path) -> None:
    service = make_service_with_fake_outreach_providers(tmp_path)
    result = service.recommend_tonight(load_observation_payload())
    assert result["resources"]["recommendation"].endswith("/recommendation")
    assert "天气预报" in service.read_run_resource(result["run_id"], "conditions")


def test_stdio_server_advertises_outreach_tools(tmp_path) -> None:
    assert {"get_observing_conditions", "recommend_tonight", "get_nasa_feature", "sync_stellarium"} <= listed_tool_names(tmp_path)
```

- [ ] **Step 2: Confirm tests fail before implementation**

Run: `pytest tests/test_mcp_server.py -q`

Expected: FAIL because the new tools are absent.

- [ ] **Step 3: Implement service-owned artifacts**

Append only these resource allowlist entries: `conditions: conditions.json`, `recommendation: recommendation.json`, `nasa-feature: nasa_feature.json`, and `stellarium-sync: stellarium_sync.json`. Inject provider factories into `StarSkillMcpService`. Validate each tool payload, create a `_new_run()`, serialize full model output to the fixed file, and return `ok`, `run_id`, `resources`, and `result`, where `result` is the corresponding complete Pydantic model dumped in JSON mode. Recommendation first calls the existing geometry pipeline; optional provider failures become unavailable evidence, while geometry failure uses `_run_failure()`. Add four `@server.tool(structured_output=True)` wrappers and document configuration plus scientific boundaries.

- [ ] **Step 4: Run a real stdio discovery test**

Run: `pytest tests/test_mcp_server.py -q`

Expected: PASS, including `ClientSession.list_tools()`.

- [ ] **Step 5: Commit**

Run `git add src/starskill/mcp_server.py docs/mcp-server.md tests/test_mcp_server.py`, then create commit `feat: expose outreach recommendations through MCP`.

### Task 7: Add authenticated FastAPI transport

**Files:**
- Create: `src/starskill/web_api.py`
- Create: `tests/test_web_api.py`
- Modify: `README.md:376-381`

**Interfaces:**
- Produces `create_web_app(service: StarSkillMcpService, frontend_dir: Path) -> FastAPI`.

- [ ] **Step 1: Write failing API tests**

```python
def test_web_app_does_not_enable_cors_for_a_foreign_origin(tmp_path) -> None:
    client = TestClient(create_web_app(make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path))
    response = client.get("/healthz", headers={"Origin": "https://foreign.example"})
    assert "access-control-allow-origin" not in response.headers


def test_web_api_returns_human_review(tmp_path) -> None:
    client = TestClient(create_web_app(make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path))
    response = client.post("/v1/recommendations/tonight", json={"task": load_observation_payload()})
    assert response.status_code == 200
    assert response.json()["human_review"]


def test_web_api_returns_429_after_the_configured_client_limit(tmp_path) -> None:
    client = TestClient(create_web_app(make_service_with_fake_outreach_providers(tmp_path), frontend_dir=tmp_path, requests_per_minute=1))
    assert client.get("/healthz").status_code == 200
    assert client.get("/healthz").status_code == 429
```

- [ ] **Step 2: Confirm tests fail before the module exists**

Run: `pytest tests/test_web_api.py -q`

Expected: FAIL during collection.

- [ ] **Step 3: Implement guarded routes**

Use `FastAPI`, a 1 MiB request-body middleware, and no CORS middleware. Add an injected monotonic-clock `FixedWindowRateLimiter` keyed by `Request.client.host`; it allows `requests_per_minute` requests per 60-second bucket and returns 429 with `Retry-After` for subsequent requests. `main()` resolves a required `web/dist` directory and starts Uvicorn with the literal host `127.0.0.1`; it must not accept a host environment override. Mount static files at `/` only after registering the API routes. Implement only `GET /healthz`, `POST /v1/conditions`, `POST /v1/recommendations/tonight`, `GET /v1/nasa/apod?date=YYYY-MM-DD`, and `POST /v1/stellarium/sync`. Delegate to service methods and return their complete `result` object, never the transport-only run metadata. Map validation to 422, rate limit to 429, body limit to 413, and unknown errors to a generic 500 without configuration values.

- [ ] **Step 4: Run API regression tests**

Run: `pytest tests/test_web_api.py tests/test_mcp_server.py tests/test_pipeline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add src/starskill/web_api.py tests/test_web_api.py README.md pyproject.toml`, then create commit `feat: add authenticated outreach web API`.

### Task 8: Verify and document the server-side feature

**Files:**
- Modify: `README.md:376-381`
- Modify: `docs/mcp-server.md:1-120`
- Test: `tests/test_external_data.py`
- Test: `tests/test_weather.py`
- Test: `tests/test_light_pollution.py`
- Test: `tests/test_nasa.py`
- Test: `tests/test_recommendations.py`
- Test: `tests/test_stellarium_bridge.py`
- Test: `tests/test_web_api.py`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Produces configuration and smoke-test documentation used by the browser plan.

- [ ] **Step 1: Document exact configuration names**

Document cloning, Python installation, `npm --prefix web install`, `make -C web engine`, `npm --prefix web run build`, and `starskill-web`. Document `STARSKILL_NASA_API_KEY`, `STARSKILL_LIGHT_POLLUTION_SNAPSHOT`, and `STARSKILL_STELLARIUM_BASE_URL` as optional enhancements; core local star map, geometry, and weather work without them, while unavailable NASA/light panels remain explicit.

- [ ] **Step 2: Run all offline provider and transport tests**

Run: `pytest tests/test_external_data.py tests/test_weather.py tests/test_light_pollution.py tests/test_nasa.py tests/test_recommendations.py tests/test_stellarium_bridge.py tests/test_web_api.py tests/test_mcp_server.py -q`

Expected: PASS without public requests.

- [ ] **Step 3: Run the full Python suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 4: Run an opt-in APOD smoke test**

Run: `STARSKILL_NASA_API_KEY="$STARSKILL_NASA_API_KEY" python -c 'from starskill.nasa import NasaApodProvider; print(NasaApodProvider.from_environment().get_feature(None).source.availability)'`

Expected: `fresh` or `cached` with a valid key; `unavailable` is a valid service degradation, never a CI failure.

- [ ] **Step 5: Commit documentation**

Run `git add README.md docs/mcp-server.md tests`, then create commit `docs: document outreach service configuration`.
