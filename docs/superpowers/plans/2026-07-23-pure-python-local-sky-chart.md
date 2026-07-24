# Pure Python Local Sky Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an offline-first, loopback-only `starskill sky-chart` page that renders reproducible local sky charts with Python, exports SHA-256-linked PNG and JSON, and needs neither Node.js nor Docker.

**Architecture:** The existing FastAPI process remains the single local transport, but its root page is read from package data instead of `web/dist`. `SkyChartService` combines a verified bundled catalog or an explicitly downloaded catalog with Astropy coordinates and a deterministic Matplotlib renderer, then places paired PNG/metadata bytes in a bounded in-memory store. Existing MCP, weather, NASA, recommendations, and optional Stellarium RemoteControl routes continue to use `StarSkillMcpService`; the new page never calls or displays the Stellarium bridge.

**Tech Stack:** Python 3.11+, FastAPI/Uvicorn, Pydantic v2, Astropy 7.2.0, Matplotlib 3.10.9, NumPy 2.4.2, pytest, standard-library HTML/CSS/JavaScript.

## Global Constraints

- The core install, CLI, renderer, page, tests, and fresh-clone acceptance use Python only: no `package.json`, Node.js, npm, Docker, Docker Desktop, Make, WebAssembly, CDN, remote fonts, JavaScript framework, Stellarium Web Engine, or desktop Stellarium dependency.
- Require Python `>=3.11`; retain the existing pinned Astropy `7.2.0`, Matplotlib `3.10.9`, NumPy `2.4.2`, FastAPI, Uvicorn, Pydantic, and tzdata dependencies. Do not add a runtime package for this feature.
- Bind every web-server entry point to the literal `127.0.0.1`; expose no host option, add no CORS middleware, and keep FastAPI docs, ReDoc, and OpenAPI disabled.
- Preserve `starskill-mcp`, `StarSkillMcpService`, `/healthz`, `/v1/conditions`, `/v1/recommendations/tonight`, `/v1/nasa/apod`, `/v1/stellarium/sync`, `StellariumBridge`, and `sync_stellarium` compatibility. The new page must not depend on, call, or present Stellarium.
- The API accepts no client filesystem path, URL, upstream source URL, font path, Matplotlib config, cache path, filename, shell syntax, or target resolver command. Never return cache paths, absolute paths, client IPs, credentials, headers, stack traces, or bridge `base_url`.
- Keep the current 1 MiB general request-body guard. Enforce a 16 KiB cap only for `POST /v1/sky-chart/render`, 30 render requests/minute/client, a single renderer, a 10-second renderer wait, and `503 {"detail":"Renderer busy; retry shortly"}` on timeout.
- Store render outputs only in process memory for 15 minutes, with at most 20 records or 50 MiB, evicting earliest-expiring records. Clear the store during shutdown; render results never write into the repository or a temporary image directory.
- `render_id` is `secrets.token_urlsafe(24)` and only URL-safe IDs are considered. Malformed, unknown, and expired IDs all return the same 404 response.
- Use `iers.conf.auto_download = False`, Astropy `AltAz(..., pressure=0*u.hPa)`, and `solar_system_ephemeris.set("builtin")`. Do not download JPL/SPICE data. The map uses a fixed 1200x900 pixel opaque black canvas at 100 DPI, DejaVu Sans, fixed colors, fixed seed `0`, and no automatic layout.
- Render layers strictly in this order: background/mask, horizon grid, constellation lines, stars (dim-to-bright), Moon, planets, target, footer. Use zenith-centred azimuthal equidistant projection `r=(90-alt_deg)/90`, `x=r*sin(az_rad)`, `y=r*cos(az_rad)`, and draw only `alt_deg >= 0` objects.
- `SkyChartRequest` forbids unknown fields. It accepts only its defined observer, timestamp, target, and catalog values; image dimensions are server constants and are never client input.
- The bundled catalog works with no network. A full catalog is local-cache-only at render time; `auto` uses it only after integrity validation, `bundled` always uses bundled data, and `full` without a valid cache returns 422 instructing the user to run `starskill sky-chart --download-catalog`.
- Before code, docs, fixtures, or tests name an HYG download URL, license identifier/text, checksum, or final asset name, retrieve and record the actual HYG v4.1 upstream release metadata. Do not invent, copy from memory, or silently change these values. A failed verification means the downloader is not implemented or advertised as available.
- All automated tests are offline: no real network, browser, Docker, Node, or desktop Stellarium. Pin observer/time fixtures and use fake downloader/resolver/clock/open-browser dependencies.
- Preserve observed-vs-derived provenance: JSON links the exact PNG SHA-256, catalog content SHA-256 and source/license/version, calculation settings, package versions, warnings, and per-object ICRS/AltAz data. Do not claim cross-operating-system PNG byte identity.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/starskill/schemas.py` | Add strict Pydantic request, target, response, and export-metadata contracts without changing the existing outreach models. |
| `src/starskill/sky_chart_catalog.py` | Load checked-in bright-star data, validate/publish a full catalog cache, and download only a verified fixed upstream asset. |
| `src/starskill/sky_chart_targets.py` | Resolve built-in objects, solar-system names, and the existing target resolver through a narrow injected adapter. |
| `src/starskill/sky_chart.py` | Define constants, deterministic Astropy/Matplotlib rendering, paired export metadata, and the bounded in-memory render store. |
| `src/starskill/web_api.py` | Serve package HTML at `/`, preserve old routes, add guarded sky-chart routes, and hard-code loopback Uvicorn startup. |
| `src/starskill/cli.py` | Add `sky-chart`, fixed-port validation, `--open`, and explicit catalog download behavior. |
| `src/starskill/data/bright_stars.json` | Versioned, license-attributed offline bright-star records used by the default renderer. |
| `src/starskill/data/constellation_segments.json` | Versioned, license-attributed segments whose endpoints are bundled bright-star keys. |
| `src/starskill/data/hyg_v4_1_source.json` | Checked-in result of upstream verification: actual v4.1 URL, asset filename, license identifier/text reference, release date, and compressed SHA-256. |
| `src/starskill/static/sky_chart.html` | Package-distributed same-origin page with native form controls, CSS, and JavaScript. |
| `docs/sources/hyg-v4.1.md` | Human-readable evidence of the verified upstream release values and verification commands/date. |
| `tests/test_sky_chart_schemas.py` | Request and metadata validation boundaries. |
| `tests/test_sky_chart_catalog.py` | Bundled load, complete-cache validation, download atomicity, and catalog mode behavior. |
| `tests/test_sky_chart_targets.py` | Offline built-in, coordinate, and controlled resolver behavior. |
| `tests/test_sky_chart.py` | Rendering layer/order/visibility/export/store behavior with fixed inputs. |
| `tests/test_web_api.py` | Existing web regression coverage plus page, render, export, body, rate, busy, and TTL routes. |
| `tests/test_cli.py` | Existing CLI regression coverage plus sky-chart parser/download/open behavior. |
| `README.md`, `skills/run-starskill/SKILL.md` | Python-only installation/use and explicit science/security boundaries. |
| `pyproject.toml` | Ensure `data/*.json` and `static/*.html` ship in wheels. |

### Task 1: Remove the Abandoned Browser Engine Route Before Adding Its Replacement

**Files:**
- Delete: `.gitmodules`
- Delete: `LICENSE`
- Delete: `web/Makefile`
- Delete: `web/THIRD_PARTY_NOTICES.md`
- Delete: `web/scripts/`
- Delete: `web/vendor/stellarium-web-engine` (the staged Git submodule/gitlink)
- Delete: `docs/superpowers/plans/2026-07-23-browser-starmap-web.md`
- Modify: `README.md:3-9` to remove only the staged Stellarium/AGPL engine notice
- Modify: `docs/superpowers/specs/2026-07-23-live-outreach-design.md:1-39,45-65,154-172`

**Interfaces:**
- Consumes: the current staged/untracked browser artifacts shown by `git status --short`: `.gitmodules`, `LICENSE`, `web/`, and the README license insertion.
- Produces: a repository with no tracked or untracked Stellarium Web Engine, Docker/Make build path, browser-engine notice, or obsolete browser implementation plan; existing Python outreach API tests still define the compatibility baseline.

- [ ] **Step 1: Record and constrain the exact deletion target.**

Run:

```bash
git status --short
git diff --cached -- .gitmodules README.md
git submodule status
find web -maxdepth 2 -type f -o -type l | sort
```

Expected: the only removal targets are the abandoned staged `.gitmodules`/gitlink, untracked `LICENSE`, `web/Makefile`, `web/THIRD_PARTY_NOTICES.md`, `web/scripts/`, and the old browser plan. Stop if a new unrelated file appears under `web/`; do not delete it without an explicit scope decision.

- [ ] **Step 2: Record the Python API regression baseline before removing the abandoned route.**

Run:

```bash
pytest tests/test_web_api.py -q
```

Expected: PASS. Task 6 will introduce the `create_web_app(..., sky_chart_service=...)` contract together with its tests, so this cleanup task never commits a deliberately failing test.

- [ ] **Step 3: Remove only the abandoned route and mark the surviving outreach specification correctly.**

Use `git rm --cached` for the staged submodule and `rm` only on the enumerated artifact paths, then remove the staged README license paragraph. Add this exact notice immediately after the title/status in `docs/superpowers/specs/2026-07-23-live-outreach-design.md`:

```markdown
> **Web supersession (2026-07-23):** For `sky-chart`, `starskill-web`, browser dependencies, and local startup, this document is superseded by `2026-07-23-pure-python-local-sky-chart-design.md`. Its weather, light-pollution, NASA, recommendation, MCP, and optional desktop-Stellarium bridge requirements remain in force.
```

Do not alter the existing `StellariumBridge` implementation, MCP tool name, or `/v1/stellarium/sync` route. Remove the obsolete browser plan rather than editing it into a second implementation source of truth.

- [ ] **Step 4: Verify the cleanup and retain the Python API baseline.**

Run:

```bash
test ! -e .gitmodules
test ! -e LICENSE
test ! -e web
test ! -e docs/superpowers/plans/2026-07-23-browser-starmap-web.md
pytest tests/test_web_api.py -q
```

Expected: all commands pass; no test or runtime path mentions an absent Docker/Node/Stellarium asset.

- [ ] **Step 5: Commit the isolated cleanup.**

```bash
git add -u README.md docs/superpowers/specs/2026-07-23-live-outreach-design.md docs/superpowers/plans/2026-07-23-browser-starmap-web.md .gitmodules web LICENSE
git commit -m "chore: remove abandoned Stellarium web route"
```

### Task 2: Verify Source Provenance and Ship Offline Catalog Package Data

**Files:**
- Create: `docs/sources/hyg-v4.1.md`
- Create: `src/starskill/data/bright_stars.json`
- Create: `src/starskill/data/constellation_segments.json`
- Create: `src/starskill/data/hyg_v4_1_source.json`
- Modify: `pyproject.toml:36-38`
- Create: `tests/test_sky_chart_catalog.py`

**Interfaces:**
- Consumes: `importlib.resources.files("starskill")` and only JSON catalog data shipped with the installed wheel.
- Produces: `load_bundled_catalog() -> BundledCatalog` and `load_hyg_source() -> HygSource`, where `BundledCatalog` has `stars: tuple[CatalogStar, ...]`, `segments: tuple[ConstellationSegment, ...]`, `metadata: CatalogMetadata`; `HygSource` has `url: str`, `asset_name: str`, `version: Literal["4.1"]`, `license: str`, and `compressed_sha256: str`.

- [ ] **Step 1: Write offline tests for package distribution and schema shape.**

Create `tests/test_sky_chart_catalog.py` with this minimum contract:

```python
from importlib.resources import files

from starskill.sky_chart_catalog import load_bundled_catalog, load_hyg_source


def test_bundled_catalog_is_available_from_installed_package_data() -> None:
    catalog = load_bundled_catalog()
    assert len(catalog.stars) >= 100
    assert catalog.metadata.dataset_id == "bundled-bright-stars"
    assert len(catalog.metadata.sha256) == 64
    assert all(-90 <= star.dec_deg <= 90 and 0 <= star.ra_deg < 360 for star in catalog.stars)
    assert files("starskill").joinpath("data/bright_stars.json").is_file()


def test_constellation_segments_reference_known_bundled_stars() -> None:
    catalog = load_bundled_catalog()
    ids = {star.star_id for star in catalog.stars}
    assert catalog.segments
    assert all(segment.start_star_id in ids and segment.end_star_id in ids for segment in catalog.segments)


def test_hyg_source_has_verified_fixed_metadata() -> None:
    source = load_hyg_source()
    assert source.version == "4.1"
    assert source.url.startswith("https://")
    assert len(source.compressed_sha256) == 64
    assert source.license
```

- [ ] **Step 2: Run the package-data test before implementation.**

Run:

```bash
pytest tests/test_sky_chart_catalog.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'starskill.sky_chart_catalog'`.

- [ ] **Step 3: Verify HYG v4.1 upstream before assigning any source constant.**

Use the official HYG Database release page and its linked source repository, not an unauthenticated mirror. Fetch the release/asset headers and bytes to a directory outside the repository, calculate the downloaded compressed SHA-256, inspect the release's actual license text, and save the exact observed URL, release tag/date, asset filename, license identifier/text reference, `ETag`/`Last-Modified` when present, byte count, and SHA-256 in `docs/sources/hyg-v4.1.md`.

The evidence document must use this concrete table format, populated only from the observed command output:

```markdown
| Field | Observed value |
| --- | --- |
| Official release page | `<observed HTTPS URL>` |
| Release tag | `4.1` |
| Asset URL | `<observed HTTPS URL>` |
| Asset filename | `<observed filename>` |
| License | `<observed identifier and source link>` |
| Downloaded bytes | `<observed integer>` |
| Compressed SHA-256 | `<observed lowercase SHA-256>` |
| ETag / Last-Modified | `<observed header or not supplied>` |
| Verified at UTC | `<observed timestamp>` |
```

If the official release lacks a distributable v4.1 asset, an auditable license, or a retrievable immutable checksum, stop this task before committing downloader code. Report that concrete absence for a product decision; do not select a substitute host. This is a required verification gate, not a network-dependent test.

- [ ] **Step 4: Implement data shipping and exact validation.**

Add the package-data declaration:

```toml
[tool.setuptools.package-data]
starskill = ["data/*.json", "static/*.html"]
```

Use this JSON envelope for both bundled files so the renderer can propagate provenance without hard-coded facts:

```json
{
  "dataset_id": "bundled-bright-stars",
  "version": "2026.07.23",
  "source_url": "<verified source URL>",
  "license": "<verified license>",
  "sha256": "<sha256 of canonical records payload>",
  "records": []
}
```

Populate `bright_stars.json` with at least 100 verified naked-eye stars, each as `{"star_id":"hr-2491","name":"Sirius","ra_deg":101.287155,"dec_deg":-16.716116,"magnitude":-1.46}` (with the actual verified source IDs/values), and `constellation_segments.json` with `{"constellation":"Ori","start_star_id":"...","end_star_id":"..."}` records. The loader must recompute the canonical-records SHA-256 using `json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`, reject a mismatch, reject duplicate IDs, and reject any segment endpoint absent from the star map.

Write `hyg_v4_1_source.json` only after Step 3 passes, using the observed fixed values:

```json
{"version":"4.1","url":"<observed HTTPS asset URL>","asset_name":"<observed asset name>","license":"<observed license>","compressed_sha256":"<observed lowercase SHA-256>"}
```

`load_hyg_source()` must validate HTTPS scheme, `version == "4.1"`, nonblank asset/license, and the 64-lowercase-hex digest before it returns `HygSource`. This prevents a malformed package resource from turning into a browser-controlled downloader.

- [ ] **Step 5: Verify source package and built wheel both contain the assets.**

Run:

```bash
pytest tests/test_sky_chart_catalog.py -q
python -m build --wheel --no-isolation
python -c 'import zipfile; w=next(__import__("pathlib").Path("dist").glob("starskill-*.whl")); z=zipfile.ZipFile(w); assert "starskill/data/bright_stars.json" in z.namelist(); assert "starskill/static/sky_chart.html" not in z.namelist()'
```

Expected: catalog tests pass; the wheel contains the JSON data. The final assertion intentionally confirms Task 2 has not yet added the page resource.

- [ ] **Step 6: Commit verified provenance and offline package data.**

```bash
git add pyproject.toml docs/sources/hyg-v4.1.md src/starskill/data/bright_stars.json src/starskill/data/constellation_segments.json src/starskill/data/hyg_v4_1_source.json src/starskill/sky_chart_catalog.py tests/test_sky_chart_catalog.py
git commit -m "feat: package verified sky chart catalogs"
```

### Task 3: Define Strict Sky-Chart Contracts and Target Resolution

**Files:**
- Modify: `src/starskill/schemas.py`
- Create: `src/starskill/sky_chart_targets.py`
- Create: `tests/test_sky_chart_schemas.py`
- Create: `tests/test_sky_chart_targets.py`

**Interfaces:**
- Consumes: current `InputModel`, `Observer`, `ResolvedTarget`, and `resolve_target()` from `src/starskill/target_resolver.py`.
- Produces: `SkyChartRequest`, `SkyChartObserver`, `SkyChartTarget`, `SkyChartRenderResponse`, `SkyChartExportMetadata`, `ResolvedSkyTarget`, and `SkyChartTargetResolver.resolve(target: SkyChartTarget) -> ResolvedSkyTarget | None`.

- [ ] **Step 1: Write schema and target-resolution failures first.**

Create `tests/test_sky_chart_schemas.py`:

```python
from datetime import datetime

import pytest
from pydantic import ValidationError

from starskill.schemas import SkyChartRequest


def valid_request() -> dict[str, object]:
    return {"observer": {"location_name": "北京", "longitude": 116.4074, "latitude": 39.9042, "timezone": "Asia/Shanghai"}, "timestamp_local": "2026-01-10T20:00:00+08:00", "target": {"mode": "name", "name": "M42"}, "catalog_mode": "auto"}


@pytest.mark.parametrize("path,value", [("observer.longitude", 180.1), ("observer.latitude", -90.1), ("target.name", " "), ("catalog_mode", "remote")])
def test_request_rejects_invalid_sky_chart_values(path: str, value: object) -> None:
    payload = valid_request()
    container, key = path.rsplit(".", 1) if "." in path else ("", path)
    target = payload if not container else payload[container]  # type: ignore[index]
    target[key] = value  # type: ignore[index]
    with pytest.raises(ValidationError):
        SkyChartRequest.model_validate(payload)


def test_timestamp_offset_must_match_named_timezone() -> None:
    payload = valid_request()
    payload["timestamp_local"] = "2026-01-10T20:00:00+00:00"
    with pytest.raises(ValidationError, match="offset"):
        SkyChartRequest.model_validate(payload)


def test_coordinate_mode_requires_ra_and_dec_and_forbids_name() -> None:
    payload = valid_request()
    payload["target"] = {"mode": "coordinates", "ra_deg": 83.822083, "dec_deg": -5.391111, "name": "M42"}
    with pytest.raises(ValidationError, match="coordinates"):
        SkyChartRequest.model_validate(payload)
```

Create `tests/test_sky_chart_targets.py`:

```python
from starskill.schemas import SkyChartTarget
from starskill.sky_chart_targets import SkyChartTargetResolver


def test_coordinate_target_never_calls_network_resolver() -> None:
    called = []
    resolver = SkyChartTargetResolver(external_resolver=lambda name: called.append(name))
    result = resolver.resolve(SkyChartTarget(mode="coordinates", ra_deg=83.822083, dec_deg=-5.391111))
    assert result is not None and result.source == "input_coordinates"
    assert called == []


def test_builtin_m42_is_resolved_without_network() -> None:
    result = SkyChartTargetResolver(external_resolver=lambda name: None).resolve(SkyChartTarget(mode="name", name="M42"))
    assert result is not None
    assert result.label == "M42"
    assert result.source == "bundled"
```

- [ ] **Step 2: Run contract tests to confirm the new surface is absent.**

Run:

```bash
pytest tests/test_sky_chart_schemas.py tests/test_sky_chart_targets.py -q
```

Expected: collection FAILS because the sky-chart models and target module are absent.

- [ ] **Step 3: Add the models with one canonical representation.**

Append these model boundaries to `src/starskill/schemas.py`; preserve all existing class names and behavior:

```python
class SkyChartObserver(InputModel):
    location_name: str = Field(default="北京", min_length=1, max_length=80)
    longitude: float = Field(default=116.4074, ge=-180, le=180)
    latitude: float = Field(default=39.9042, ge=-90, le=90)
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


class SkyChartTarget(InputModel):
    mode: Literal["name", "coordinates"] = "name"
    name: str | None = "M42"
    ra_deg: float | None = None
    dec_deg: float | None = None

    @model_validator(mode="after")
    def enforce_target_mode(self) -> "SkyChartTarget":
        if self.mode == "name":
            if self.ra_deg is not None or self.dec_deg is not None or not self.name or len(self.name.strip()) > 120 or any(ord(c) < 32 for c in self.name):
                raise ValueError("name target requires only a visible 1..120 character name")
            self.name = self.name.strip()
        elif self.name is not None or self.ra_deg is None or self.dec_deg is None or not 0 <= self.ra_deg < 360 or not -90 <= self.dec_deg <= 90:
            raise ValueError("coordinates target requires only ra_deg and dec_deg")
        return self


class SkyChartRequest(InputModel):
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
        zone_offset = self.timestamp_local.astimezone(ZoneInfo(self.observer.timezone)).utcoffset()
        if self.timestamp_local.utcoffset() != zone_offset:
            raise ValueError("timestamp_local offset must match observer timezone")
        return self
```

Define `SkyChartRenderResponse` with `render_id`, `png_url`, `json_url`, `catalog_mode_used`, `catalog_status`, and `warnings`; define metadata as strict nested Pydantic models containing exactly the schema shape in the approved design. Add the metadata validator that guarantees a 64-character lowercase `render.png_sha256`, six-decimal numeric serialization, `UTC` time scale, `AltAz` horizontal frame, `builtin` ephemeris, and `iers_auto_download=False`.

- [ ] **Step 4: Implement the resolver with an injected network boundary.**

Use immutable built-ins for `M42` (ICRS `83.822083`, `-5.391111`) and fixed solar-system body names. Coordinates and bundled names resolve without any network call; the optional `external_resolver` is a callable supplied by server construction and returns a current `ResolvedTarget | None` from an existing validated cache/SIMBAD adapter. It receives only the stripped name after rejecting URL delimiters, path separators, control characters, shell metacharacters, and names longer than 120 characters:

```python
@dataclass(frozen=True)
class ResolvedSkyTarget:
    label: str
    ra_deg: float | None
    dec_deg: float | None
    solar_system_body: str | None
    source: Literal["input_coordinates", "bundled", "solar_system", "existing_resolver"]


class SkyChartTargetResolver:
    def __init__(self, external_resolver: Callable[[str], ResolvedTarget | None]) -> None:
        self._external_resolver = external_resolver

    def resolve(self, target: SkyChartTarget) -> ResolvedSkyTarget | None:
        if target.mode == "coordinates":
            return ResolvedSkyTarget("RA/Dec target", target.ra_deg, target.dec_deg, None, "input_coordinates")
        # return a bundled/solar-system match before invoking _external_resolver
```

Catch existing `InvalidTargetNameError`, `TargetNotFoundError`, and `TargetServiceError` at the service boundary and turn them into `None` plus machine-readable warning codes. Do not let externally resolved names alter the outgoing network host, cache directory, or request model.

- [ ] **Step 5: Run focused contracts and current schema/target regression tests.**

Run:

```bash
pytest tests/test_sky_chart_schemas.py tests/test_sky_chart_targets.py tests/test_schemas.py tests/test_target_resolver.py -q
```

Expected: PASS. Confirm manually that a sky-chart validation error identifies only `Invalid sky-chart request` at HTTP transport level in Task 6, while existing CLI validation keeps its structured detail output.

- [ ] **Step 6: Commit strict contracts.**

```bash
git add src/starskill/schemas.py src/starskill/sky_chart_targets.py tests/test_sky_chart_schemas.py tests/test_sky_chart_targets.py
git commit -m "feat: define sky chart input contracts"
```

### Task 4: Implement Full-Catalog Cache Integrity and Explicit Downloader

**Files:**
- Modify: `src/starskill/sky_chart_catalog.py`
- Modify: `tests/test_sky_chart_catalog.py`
- Create: `tests/fixtures/sky_chart/hyg-valid.csv`

**Interfaces:**
- Consumes: verified `HygSource`, `CatalogMetadata`, `CatalogStar`, and the user-selected `catalog_mode`.
- Produces: `FullCatalogCache(cache_dir: Path, source: HygSource)`, `FullCatalogCache.load_valid() -> FullCatalog | None`, `FullCatalogCache.download_and_publish(fetch: CatalogFetcher) -> CatalogDownloadSummary`, and `select_catalog(mode: CatalogMode, bundled: BundledCatalog, full_cache: FullCatalogCache) -> CatalogSelection`.

- [ ] **Step 1: Add deterministic cache/download failures.**

Extend `tests/test_sky_chart_catalog.py`:

```python
def test_auto_uses_bundled_when_no_full_cache(tmp_path: Path) -> None:
    selection = select_catalog("auto", load_bundled_catalog(), FullCatalogCache(tmp_path, load_hyg_source()))
    assert selection.mode_used == "bundled"
    assert selection.status == "degraded"


def test_full_rejects_missing_cache_without_network(tmp_path: Path) -> None:
    with pytest.raises(FullCatalogUnavailableError, match="--download-catalog"):
        select_catalog("full", load_bundled_catalog(), FullCatalogCache(tmp_path, load_hyg_source()))


def test_invalid_download_keeps_prior_valid_cache(tmp_path: Path, hyg_csv_bytes: bytes) -> None:
    cache = FullCatalogCache(tmp_path, load_hyg_source())
    cache.publish_fixture_for_test(hyg_csv_bytes)
    before = cache.manifest_path.read_bytes()
    with pytest.raises(CatalogDownloadError):
        cache.download_and_publish(fetch=FakeFetcher(status=200, chunks=[b"bad,csv\n"]))
    assert cache.manifest_path.read_bytes() == before
    assert cache.load_valid() is not None
```

Also cover stream size `128 * 1024 * 1024 + 1`, non-200 status, compressed SHA mismatch, bad CSV header, fewer than 100001 data rows, mismatched published CSV digest, and a temp partial file never becoming the manifest/current CSV.

- [ ] **Step 2: Run catalog-cache tests to prove the behavior is missing.**

Run:

```bash
pytest tests/test_sky_chart_catalog.py -q
```

Expected: FAIL with missing `FullCatalogCache`, `select_catalog`, and error classes.

- [ ] **Step 3: Implement cache validation and atomic publish.**

Use only `cache_dir / "hyg-v4.1"` and fixed names `catalog.csv` and `manifest.json`; resolve the directory once, create it with `parents=True`, and never derive it from HTTP data. Define:

```python
MAX_HYG_DOWNLOAD_BYTES = 128 * 1024 * 1024
MIN_HYG_ROWS = 100_001
REQUIRED_HYG_COLUMNS = frozenset({"ra", "dec", "mag", "proper"})

class CatalogFetcher(Protocol):
    def stream(self, url: str, *, max_bytes: int) -> tuple[int, Mapping[str, str], Iterable[bytes]]: ...

def canonical_manifest(*, source: HygSource, compressed_sha256: str, csv_sha256: str, row_count: int, headers: Mapping[str, str]) -> dict[str, object]: ...
```

`download_and_publish()` must stream only `source.url`, fail before write when the status is not 200, write compressed bytes to a `NamedTemporaryFile(dir=cache_dir, delete=False)`, cap total bytes, hash the exact bytes, and require equality with `source.compressed_sha256`. Extract only the verified archive member/CSV form recorded in `HygSource`; reject archive traversal and a different member name. Parse the decoded CSV using `csv.DictReader`, require `REQUIRED_HYG_COLUMNS`, count more than 100000 rows, and hash the final UTF-8 CSV bytes. Write a complete manifest with source URL/version/license, `ETag`/`Last-Modified` if present, access UTC time, compressed/csv hashes, and row count to a second temporary file. `os.replace(temp_csv, catalog.csv)` then `os.replace(temp_manifest, manifest.json)` publishes only fully validated data. On every exception unlink only the known temporary paths; leave the previous `catalog.csv` and manifest untouched.

`load_valid()` re-hashes the published CSV, re-parses headers and row count, and confirms every manifest field equals the package `HygSource`; it returns `None` rather than a partially trusted catalog. `select_catalog()` returns `CatalogSelection(mode_used="bundled", status="available")` for explicit bundled, `("full", "available")` only for valid full, and `("bundled", "degraded")` for auto without one.

- [ ] **Step 4: Verify all offline catalog modes.**

Run:

```bash
pytest tests/test_sky_chart_catalog.py -q
pytest tests/test_sky_chart_catalog.py -q -k 'not download_live'
```

Expected: PASS. There is no `download_live` test in the repository: the second command documents and enforces that all tests use the injected fake fetcher.

- [ ] **Step 5: Commit full-catalog integrity independently.**

```bash
git add src/starskill/sky_chart_catalog.py tests/test_sky_chart_catalog.py tests/fixtures/sky_chart/hyg-valid.csv
git commit -m "feat: add verified sky catalog cache"
```

### Task 5: Build the Deterministic Renderer, Paired Metadata, and TTL Store

**Files:**
- Create: `src/starskill/sky_chart.py`
- Create: `tests/test_sky_chart.py`
- Modify: `src/starskill/sky_chart_catalog.py`
- Modify: `src/starskill/schemas.py`

**Interfaces:**
- Consumes: `SkyChartRequest`, `CatalogSelection`, `SkyChartTargetResolver`, selected catalog records, and an injected UTC/monotonic clock.
- Produces: `SkyChartService.render(request: SkyChartRequest) -> RenderedSkyChart`, `RenderedSkyChart(png_bytes: bytes, metadata: SkyChartExportMetadata, catalog_mode_used: str, catalog_status: str)`, `RenderStore.put(chart: RenderedSkyChart) -> str`, `RenderStore.get(render_id: str) -> RenderedSkyChart | None`, and `SkyChartRenderer.render(request, selection, resolved_target) -> RenderedSkyChart`.

- [ ] **Step 1: Write renderer and store tests with no external state.**

Create `tests/test_sky_chart.py`:

```python
from hashlib import sha256

from starskill.schemas import SkyChartRequest
from starskill.sky_chart import RenderStore, SkyChartService


FIXED_REQUEST = SkyChartRequest.model_validate({"observer": {"location_name": "北京", "longitude": 116.4074, "latitude": 39.9042, "timezone": "Asia/Shanghai"}, "timestamp_local": "2026-01-10T20:00:00+08:00", "target": {"mode": "coordinates", "ra_deg": 83.822083, "dec_deg": -5.391111}, "catalog_mode": "bundled"})


def test_render_has_expected_layer_order_and_linked_png_digest(service: SkyChartService) -> None:
    chart = service.render(FIXED_REQUEST)
    assert chart.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert chart.metadata.render.layer_order == ["background", "horizon_grid", "constellations", "stars", "moon", "planets", "target", "footer"]
    assert chart.metadata.render.png_sha256 == sha256(chart.png_bytes).hexdigest()
    assert chart.metadata.calculation.horizontal_frame == "AltAz"
    assert chart.metadata.calculation.atmospheric_refraction is False


def test_invisible_object_is_recorded_but_not_drawn(service: SkyChartService) -> None:
    chart = service.render(FIXED_REQUEST)
    assert all(item.drawn is item.visible for item in [chart.metadata.objects.moon, *chart.metadata.objects.planets])


def test_render_store_expires_and_evicts_by_expiry() -> None:
    now = [0.0]
    store = RenderStore(ttl_seconds=900, max_records=2, max_bytes=100, monotonic_clock=lambda: now[0])
    first = store.put_bytes_for_test(b"a")
    now[0] = 901.0
    assert store.get(first) is None
```

Add tests for target-unresolved warning/`objects.target is None`, `auto` degraded catalog footer/status, full cache selection, exactly 1200x900 RGB PNG, star magnitude order, constellation endpoints below horizon not drawn, no Sun in `objects.planets`, all serialized coordinate values have six decimal places, and store eviction at both 20 records and 50 MiB.

- [ ] **Step 2: Run tests to establish RED.**

Run:

```bash
pytest tests/test_sky_chart.py -q
```

Expected: FAIL because `starskill.sky_chart` does not exist.

- [ ] **Step 3: Implement a deterministic coordinate/render context.**

Use a context that freezes all non-input dependencies before any plotting:

```python
CANVAS_WIDTH_PX = 1200
CANVAS_HEIGHT_PX = 900
CANVAS_DPI = 100
LAYER_ORDER = ["background", "horizon_grid", "constellations", "stars", "moon", "planets", "target", "footer"]

def project_altaz(altitude_deg: float, azimuth_deg: float) -> tuple[float, float]:
    radius = (90.0 - altitude_deg) / 90.0
    azimuth_rad = np.deg2rad(azimuth_deg)
    return (float(radius * np.sin(azimuth_rad)), float(radius * np.cos(azimuth_rad)))

@contextmanager
def deterministic_astropy_matplotlib() -> Iterator[None]:
    old_iers = iers.conf.auto_download
    old_rc = matplotlib.rcParams.copy()
    iers.conf.auto_download = False
    matplotlib.rcParams.update({"figure.dpi": 100, "savefig.dpi": 100, "font.family": "DejaVu Sans", "figure.facecolor": "#000000", "savefig.transparent": False})
    np.random.seed(0)
    try:
        with solar_system_ephemeris.set("builtin"):
            yield
    finally:
        iers.conf.auto_download = old_iers
        matplotlib.rcParams.update(old_rc)
```

Convert `request.timestamp_local` to `Time(...).utc`, make `EarthLocation.from_geodetic(lon=..., lat=...)`, and make exactly one `AltAz(obstime=time_utc, location=location, pressure=0 * u.hPa)` frame. Transform ICRS stars/targets and `get_body()` Moon/planet coordinates into it. The planet sequence is `mercury`, `venus`, `mars`, `jupiter`, `saturn`, `uranus`, `neptune`; do not add `sun`. Compute Moon illumination from Sun-Moon elongation and record it. Every object metadata record contains label, ICRS values when applicable, `altitude_deg`, `azimuth_deg`, `visible`, and `drawn`; draw only visible ones.

Create a `Figure(figsize=(12, 9), dpi=100, facecolor="#000000")` and `Axes` with fixed `set_xlim(-1.05, 1.05)`, `set_ylim(-1.05, 1.05)`, `set_aspect("equal")`, `axis("off")`; never use `tight_layout`, automatic legends, generated timestamps, random IDs, or system-local output paths in the image. Apply the approved layers in `LAYER_ORDER`, record each count, write with `figure.savefig(BytesIO(), format="png", dpi=100, facecolor="#000000", edgecolor="#000000", metadata={})`, close the figure, then hash exactly those PNG bytes before constructing `SkyChartExportMetadata`.

- [ ] **Step 4: Implement service and memory store semantics.**

`SkyChartService.render()` selects the catalog, resolves target with the Task 3 adapter, invokes the renderer, and appends only stable codes such as `catalog_degraded`, `target_unresolved`, and `target_resolution_unavailable` to metadata warnings. It must never include a resolver exception string.

Implement store records as `(expires_at_monotonic, png_bytes, metadata_json_bytes)` guarded by a `threading.Lock`. On `put`, call `purge_expired(now)`, generate `token_urlsafe(24)` until unique, then evict the record with the smallest `(expires_at_monotonic, insertion_order)` until both capacity limits admit the new bytes. `get` calls the same purge and returns `None` for every invalid/missing/expired id. `clear()` drops all bytes. Serialize metadata once with `model_dump_json(exclude_none=False, by_alias=True)` so JSON download is the exact item whose `render.png_sha256` matched the stored PNG.

- [ ] **Step 5: Run focused and adjacent regression suites.**

Run:

```bash
pytest tests/test_sky_chart.py tests/test_sky_chart_catalog.py tests/test_sky_chart_schemas.py tests/test_solar_system_relationship.py -q
```

Expected: PASS. Inspect one generated test PNG with Pillow in the test, not a browser, and assert it is nonblank/RGB instead of asserting bytes match a committed golden file across operating systems.

- [ ] **Step 6: Commit renderer/store behavior.**

```bash
git add src/starskill/sky_chart.py src/starskill/sky_chart_catalog.py src/starskill/schemas.py tests/test_sky_chart.py
git commit -m "feat: render reproducible local sky charts"
```

### Task 6: Replace `web/dist` with a Same-Origin Python Page and Guarded Routes

**Files:**
- Create: `src/starskill/static/sky_chart.html`
- Modify: `src/starskill/web_api.py`
- Modify: `tests/test_web_api.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `StarSkillMcpService`, `SkyChartService`, `RenderStore`, `SkyChartRequest`, `SkyChartRenderResponse`, and package resource `static/sky_chart.html`.
- Produces: `create_web_app(service: StarSkillMcpService, sky_chart_service: SkyChartService, *, requests_per_minute: int = 60, sky_chart_requests_per_minute: int = 30, monotonic_clock: Callable[[], float] = time.monotonic, rate_limiter: FixedWindowRateLimiter | None = None, sky_chart_rate_limiter: FixedWindowRateLimiter | None = None) -> FastAPI`; `run_web_server(port: int, open_browser: bool) -> None`; and `main(argv: Sequence[str] | None = None) -> None` for `starskill-web`.

- [ ] **Step 1: Add API/page tests before changing the transport.**

Replace all current `create_web_app(..., frontend_dir=tmp_path)` calls in `tests/test_web_api.py` with a fake `SkyChartService`/store and add:

```python
def test_root_serves_packaged_same_origin_page(tmp_path: Path) -> None:
    client = TestClient(create_web_app(make_service_with_fake_outreach_providers(tmp_path), FakeSkyChartService()))
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "type=\"range\"" in response.text
    assert "/v1/sky-chart/render" in response.text
    assert all(token not in response.text.lower() for token in ("npm", "docker", "stellarium", "cdn", "http://"))


def test_render_and_both_exports_share_one_opaque_id(tmp_path: Path) -> None:
    client = TestClient(create_web_app(make_service_with_fake_outreach_providers(tmp_path), FakeSkyChartService()))
    response = client.post("/v1/sky-chart/render", json=valid_sky_chart_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["png_url"] == f"/v1/sky-chart/renders/{body['render_id']}.png"
    assert client.get(body["png_url"]).headers["content-type"] == "image/png"
    metadata = client.get(body["json_url"]).json()
    assert metadata["render_id"] == body["render_id"]


def test_sky_chart_body_limit_busy_and_invalid_ids_are_stable(tmp_path: Path) -> None:
    client = TestClient(create_web_app(make_service_with_fake_outreach_providers(tmp_path), FakeBusySkyChartService()))
    assert client.post("/v1/sky-chart/render", content=b"x" * (16 * 1024 + 1), headers={"content-type": "application/json"}).status_code == 413
    assert client.get("/v1/sky-chart/renders/not-valid!.png").status_code == 404
    assert client.get("/v1/sky-chart/renders/missing.png").status_code == 404
    assert client.post("/v1/sky-chart/render", json=valid_sky_chart_payload()).json() == {"detail": "Renderer busy; retry shortly"}
```

Add tests for 30th/31st render request 429, 15-minute expiry with injected monotonic clock, full-cache 422 error message, no CORS header, existing `/v1` response shapes, and generic exceptions not leaking a path.

- [ ] **Step 2: Run the transport tests to establish RED.**

Run:

```bash
pytest tests/test_web_api.py -q
```

Expected: FAIL because the current signature requires `frontend_dir`, root mounting reads a directory, and no sky-chart routes exist.

- [ ] **Step 3: Replace static-directory mounting with package resource HTML.**

Delete `Path`/`StaticFiles` use and the `frontend_dir` parameter. Use `importlib.resources.files("starskill").joinpath("static/sky_chart.html").read_text(encoding="utf-8")` at app construction; fail only with a concise startup log if the package resource is missing. Add `@app.get("/")` returning `HTMLResponse(page_html.replace("__DEFAULT_TIMESTAMP_LOCAL__", datetime.now(ZoneInfo("Asia/Shanghai")).replace(second=0, microsecond=0).isoformat()))` and `Cache-Control: no-store`.

Keep the current global `FixedWindowRateLimiter` behavior for legacy routes. Before `/v1/sky-chart/render`, use a separate injected 30-RPM limiter keyed by `Request.client.host`, so rendering has its stricter budget without changing weather/MCP API limits. In middleware, retain the 1 MiB global check and add a route-specific `content-length`/actual-body 16 KiB check with `{"detail":"Request body too large"}`. Do not mount any fallback static directory.

- [ ] **Step 4: Add render/export routes and the single-render gate.**

Use an app-owned `asyncio.Semaphore(1)`. The handler validates `SkyChartRequest` through FastAPI; map any model or domain validation to exactly `422 {"detail":"Invalid sky-chart request"}`. Then:

```python
@app.post("/v1/sky-chart/render", response_model=SkyChartRenderResponse)
async def render_sky_chart(request_body: SkyChartRequest, request: Request) -> SkyChartRenderResponse:
    if not sky_limiter.allow(client_host(request))[0]:
        raise HTTPException(status_code=429, detail="Too many requests")
    try:
        await asyncio.wait_for(render_gate.acquire(), timeout=10)
    except TimeoutError as exc:
        raise HTTPException(status_code=503, detail="Renderer busy; retry shortly") from exc
    try:
        chart = await asyncio.to_thread(sky_chart_service.render, request_body)
        render_id = render_store.put(chart)
        return SkyChartRenderResponse(render_id=render_id, png_url=f"/v1/sky-chart/renders/{render_id}.png", json_url=f"/v1/sky-chart/renders/{render_id}.json", catalog_mode_used=chart.catalog_mode_used, catalog_status=chart.catalog_status, warnings=chart.metadata.warnings)
    finally:
        render_gate.release()
```

Validate `{render_id}` against `re.fullmatch(r"[A-Za-z0-9_-]{32}", render_id)` before each export lookup. Return one `HTTPException(status_code=404, detail="Render not found")` for malformed, missing, and expired records. Return `Response(bytes, media_type="image/png", headers={"Content-Disposition": f'attachment; filename="starskill-sky-chart-{render_id}.png"'})` and the matching JSON equivalent; export body comes exclusively from `RenderStore`.

On FastAPI shutdown, wait up to 10 seconds for the gate if occupied and call `render_store.clear()`; do not delay process exit indefinitely. Preserve API route declaration before `/` and retain the existing route-specific `base_url` redaction.

- [ ] **Step 5: Implement the no-build page.**

Build `src/starskill/static/sky_chart.html` as a complete HTML document with no external resource URL. It must include labels/controls for location name, longitude, latitude, IANA timezone, `datetime-local`, name/RA-Dec segmented radio mode, target inputs, `auto|bundled|full` select, a 24-hour `input type="range"` stepping 15 minutes, update command, and disabled-until-render export links. Its JavaScript constructs an offset-bearing ISO timestamp from the selected local time and IANA-zone offset returned by `Intl.DateTimeFormat(..., {timeZoneName: "longOffset"})`; it POSTs JSON to only `/v1/sky-chart/render`.

The browser logic must use this lifecycle: set Beijing/default M42/current server-provided minute on first load; keep `baseTimestamp`; on manual datetime change set `baseTimestamp` and reset slider to 0; calculate slider timestamp in `[-720, 720]` minutes at `15` minute increments; debounce slider input 250 ms; abort the previous fetch with `AbortController`; retain the previous `<img>` source until a successful new response; then update both export anchors from the same response `render_id`. On a 422 full-cache or unresolved-target result, show the server's stable short message/warnings in an `aria-live` status element, never an exception or HTML injection.

- [ ] **Step 6: Implement loopback-only server start and `--open` health ordering.**

Define `run_web_server(port: int, open_browser: bool, *, web_app_factory: Callable[[], FastAPI] = default_web_app, browser_open: Callable[[str], bool] = webbrowser.open, health_get: Callable[[str], int] = get_health_status) -> None`. Reject ports outside `1024..65535` before Uvicorn construction. Always build `uvicorn.Config(app, host="127.0.0.1", port=port, ...)`; never accept a host environment variable. For `open_browser=True`, start one daemon helper that polls `http://127.0.0.1:{port}/healthz` through `urllib.request.urlopen` for 200 before calling `browser_open("http://127.0.0.1:{port}/")` once. A false/exceptional browser open prints the URL but does not terminate the server. A bind failure propagates to the caller as a nonzero CLI outcome and never starts the helper's browser action.

Make `web_api.main()` parse only `--port` with default 8000 and call `run_web_server(port, open_browser=False)`. This keeps `starskill-web` operational with the same Python app and no `web/dist` test.

- [ ] **Step 7: Verify complete HTTP behavior and package installation.**

Run:

```bash
pytest tests/test_web_api.py tests/test_stellarium_bridge.py tests/test_mcp_server.py -q
python -m build --wheel --no-isolation
python -c 'import zipfile; w=next(__import__("pathlib").Path("dist").glob("starskill-*.whl")); assert "starskill/static/sky_chart.html" in zipfile.ZipFile(w).namelist()'
```

Expected: PASS; installed wheel contains both JSON data and HTML, and no test needs a `web/dist` fixture.

- [ ] **Step 8: Commit the Python web migration.**

```bash
git add pyproject.toml src/starskill/static/sky_chart.html src/starskill/web_api.py tests/test_web_api.py
git commit -m "feat: serve local sky chart from Python"
```

### Task 7: Add the CLI Without Breaking Existing Commands

**Files:**
- Modify: `src/starskill/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `src/starskill/web_api.py`

**Interfaces:**
- Consumes: `FullCatalogCache.download_and_publish`, `HygSource`, `run_web_server(port, open_browser)`, and existing `main(argv)` exit-code convention.
- Produces: `starskill sky-chart [--port PORT] [--open] [--download-catalog] [--catalog-cache-dir PATH]`; JSON summary on successful catalog download; nonzero return without service start on validation/download/bind failures.

- [ ] **Step 1: Add CLI RED tests using monkeypatches.**

Append to `tests/test_cli.py`:

```python
def test_sky_chart_help_and_port_bounds(capsys) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["sky-chart", "--help"])
    assert help_exit.value.code == 0
    with pytest.raises(SystemExit) as port_exit:
        main(["sky-chart", "--port", "1023"])
    assert port_exit.value.code == 2


def test_download_catalog_does_not_start_uvicorn(tmp_path, monkeypatch, capsys) -> None:
    started = []
    monkeypatch.setattr(cli, "run_web_server", lambda **kwargs: started.append(kwargs))
    monkeypatch.setattr(cli, "download_full_catalog", lambda cache_dir: {"downloaded": True, "cache_dir": str(cache_dir), "rows": 100001})
    assert main(["sky-chart", "--download-catalog", "--catalog-cache-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["downloaded"] is True
    assert started == []


def test_sky_chart_passes_only_loopback_port_and_open_flag(monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(cli, "run_web_server", lambda **kwargs: observed.append(kwargs))
    assert main(["sky-chart", "--port", "8123", "--open"]) == 0
    assert observed == [{"port": 8123, "open_browser": True}]
```

Add a test where `download_full_catalog` raises `CatalogDownloadError` and assert return `1`, JSON `{"downloaded": false, "error": "catalog_download_failed"}`, and no Uvicorn call.

- [ ] **Step 2: Run the CLI tests to prove the command is unavailable.**

Run:

```bash
pytest tests/test_cli.py -q -k sky_chart
```

Expected: FAIL because argparse has no `sky-chart` command.

- [ ] **Step 3: Implement parser and explicit branch before generic JSON-file parsing.**

Add exactly these parser arguments near the other subparsers:

```python
sky_chart_parser = commands.add_parser("sky-chart", help="start the local Python sky chart")
sky_chart_parser.add_argument("--port", type=int, default=8000)
sky_chart_parser.add_argument("--open", action="store_true")
sky_chart_parser.add_argument("--download-catalog", action="store_true")
sky_chart_parser.add_argument("--catalog-cache-dir", type=Path, default=Path("cache/sky-chart"))
```

Immediately after `args = parser.parse_args(argv)`, before the existing final `payload = json.loads(args.input_path...)`, add:

```python
if args.command == "sky-chart":
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if args.download_catalog:
        try:
            summary = download_full_catalog(args.catalog_cache_dir)
        except CatalogDownloadError:
            print(json.dumps({"downloaded": False, "error": "catalog_download_failed"}, ensure_ascii=False), file=sys.stderr)
            return 1
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    run_web_server(port=args.port, open_browser=args.open)
    return 0
```

`download_full_catalog()` wraps `FullCatalogCache(...).download_and_publish(HttpCatalogFetcher())` and returns only version, row count, hashes, and cache status, never the upstream URL/path from exception text. It must not run Uvicorn. Catch a Uvicorn bind/start error in this CLI branch, print a short JSON error without internals, and return 1. Do not add `--host`, a URL option, a browser-engine option, or a network flag.

- [ ] **Step 4: Run new and existing CLI regressions.**

Run:

```bash
pytest tests/test_cli.py -q
python -m starskill sky-chart --help
```

Expected: PASS. Help lists exactly the four documented options; it does not start the server or download a catalog.

- [ ] **Step 5: Commit the CLI.**

```bash
git add src/starskill/cli.py src/starskill/web_api.py tests/test_cli.py
git commit -m "feat: add local sky chart CLI"
```

### Task 8: Migrate User Documentation and the Run Skill to Python-Only Operation

**Files:**
- Modify: `README.md:367-438` and web/security sections near `README.md:445-465`
- Modify: `skills/run-starskill/SKILL.md`
- Modify: `skills/run-starskill/references/cli-contract.md`
- Test: `tests/test_cli.py`
- Test: `tests/test_web_api.py`

**Interfaces:**
- Consumes: final CLI synopsis, `/healthz`, export route contract, current optional outreach environment variables, and science/security constraints.
- Produces: copy-pasteable Python-only clean-clone instructions and Skill guidance that names `sky-chart` as a local visual workflow while preserving existing observation commands.

- [ ] **Step 1: Write documentation assertions first.**

Add test assertions that inspect repository text rather than execute documentation commands:

```python
def test_readme_documents_python_only_sky_chart() -> None:
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert 'pip install -e ".[dev]"' in text
    assert "starskill sky-chart --open" in text
    assert "node --version" not in text
    assert "npm --prefix web" not in text
    assert "make -c web" not in text
    assert "docker version" not in text
```

- [ ] **Step 2: Run the documentation guard before editing prose.**

Run:

```bash
pytest tests/test_cli.py -q -k readme_documents_python_only
```

Expected: FAIL because the current README requires Node, npm, Docker, Make, a browser engine build, and `web/dist`.

- [ ] **Step 3: Replace only obsolete browser startup prose and preserve outreach boundaries.**

In README, replace the current browser-engine prerequisite/build block with:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/starskill sky-chart --open
```

Document `--port 8000`, manual URL `http://127.0.0.1:8000/`, the separate offline full-catalog command, the fact that it is the only operation allowed to contact the verified HYG source, and `auto`/`bundled`/`full` behavior. State that render PNG/JSON share an opaque render ID and JSON carries the PNG SHA-256. State that no location/browser permission or upload occurs, the service is loopback-only/no CORS, and the visualization does not simulate Stellarium, guarantee weather/visibility/safety, or use live light pollution.

Retain the `STARSKILL_NASA_API_KEY`, `STARSKILL_LIGHT_POLLUTION_SNAPSHOT`, and `STARSKILL_STELLARIUM_BASE_URL` table as optional, but explicitly say they enhance existing outreach/MCP routes only and are not prerequisites for `sky-chart`.

Extend `skills/run-starskill/SKILL.md` selection with `sky-chart` only for a local visual sky chart, require the user to run `starskill sky-chart --download-catalog` themselves for full density, and direct agents to report the render ID, catalog mode/status, hash-linked exports, warnings, and remaining human/scientific checks. Extend `references/cli-contract.md` with the exact synopsis, exit outcomes, loopback URL, cache directory default, and prohibition on Node/Docker/Stellarium dependency.

- [ ] **Step 4: Run documentation and regression tests.**

Run:

```bash
pytest tests/test_cli.py tests/test_web_api.py tests/test_mcp_server.py -q
rg -n -i 'node --version|npm --prefix web|make -c web|docker version|stellarium web engine|web/dist' README.md skills/run-starskill docs/superpowers
```

Expected: tests PASS; ripgrep returns no operational dependency instruction. The strings retained in historical evaluation reports are outside the user-facing README/Skill and are not edited.

- [ ] **Step 5: Commit documentation migration.**

```bash
git add README.md skills/run-starskill/SKILL.md skills/run-starskill/references/cli-contract.md tests/test_cli.py
git commit -m "docs: document Python-only local sky chart"
```

### Task 9: Run Full Offline Verification, Clean-Clone Acceptance, and Publish

**Files:**
- Modify only if verification exposes a reproducible defect: the exact implementation/test/documentation file that fixes it
- Test: full `tests/` suite and a clean clone

**Interfaces:**
- Consumes: all completed commits, public `origin` remote, Python package distribution, and locally available Git credentials.
- Produces: a verified Python-only clone run and a pushed commit sequence. No claim of successful optional full-catalog download is made unless its explicit live command actually succeeds.

- [ ] **Step 1: Run static scope checks and the full offline suite.**

Run:

```bash
git status --short
pytest -q
rg -n -i 'package.json|npm|docker|stellarium web engine|web/dist|staticfiles\(directory=frontend' pyproject.toml src tests README.md skills/run-starskill
```

Expected: `pytest -q` PASS. The scoped ripgrep returns no core dependency/implementation match; permitted `stellarium_bridge.py`, MCP test names, and `/v1/stellarium/sync` references remain because they are not Web Engine dependencies. Resolve every failing test with a new focused RED/GREEN regression before proceeding, then commit that correction separately.

- [ ] **Step 2: Execute a pre-publication clean-clone acceptance from the committed local repository.**

Run from a fresh temporary directory, never copying caches, `runs/`, `.env`, source `web/`, or package artifacts. Cloning the local committed repository first detects packaging and startup defects before any public branch is advanced:

```bash
clone_dir=$(mktemp -d)
git clone --no-local "$PWD" "$clone_dir"
cd "$clone_dir"
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/starskill sky-chart --port 8000 >server.log 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/healthz && break; sleep 1; done
curl -fsS http://127.0.0.1:8000/ >index.html
test -s index.html
curl -fsS -H 'content-type: application/json' -d '{"observer":{"location_name":"北京","longitude":116.4074,"latitude":39.9042,"timezone":"Asia/Shanghai"},"timestamp_local":"2026-01-10T20:00:00+08:00","target":{"mode":"name","name":"M42"},"catalog_mode":"bundled"}' http://127.0.0.1:8000/v1/sky-chart/render >render.json
render_id=$(.venv/bin/python -c 'import json; print(json.load(open("render.json"))["render_id"])')
curl -fsS "http://127.0.0.1:8000/v1/sky-chart/renders/${render_id}.png" -o chart.png
curl -fsS "http://127.0.0.1:8000/v1/sky-chart/renders/${render_id}.json" -o chart.json
.venv/bin/python -c 'import hashlib,json; metadata=json.load(open("chart.json")); assert open("chart.png","rb").read(8)==b"\x89PNG\r\n\x1a\n"; assert hashlib.sha256(open("chart.png","rb").read()).hexdigest()==metadata["render"]["png_sha256"]'
```

Expected: health prints `{"status":"ok"}`, page/PNG/JSON are nonempty, and the digest assertion exits 0. The run invokes no Node/npm/Docker/Make/Stellarium command. Stop the background server before leaving the clone.

- [ ] **Step 3: Run the optional live catalog smoke separately and report it honestly.**

Only with network access and after Task 2 evidence exists:

```bash
.venv/bin/starskill sky-chart --download-catalog --catalog-cache-dir cache/sky-chart
```

Expected on success: a JSON summary with verified version, row count, and hashes, followed by a manual `catalog_mode="full"` render check. On a network/upstream failure: retain the offline acceptance result, report the nonzero exit and error category, and do not mark the live download as passed or modify a valid cache.

- [ ] **Step 4: Publish the locally accepted commits and repeat the acceptance through the public clone URL.**

Run:

```bash
git status --short
git log --oneline origin/main..HEAD
git diff --check origin/main...HEAD
git push origin HEAD:main
published_clone_dir=$(mktemp -d)
git clone git@github.com:Melon1234123/Skill-for-stars.git "$published_clone_dir"
cd "$published_clone_dir"
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/starskill sky-chart --port 8000 >server.log 2>&1 &
published_server_pid=$!
trap 'kill "$published_server_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/healthz && break; sleep 1; done
curl -fsS http://127.0.0.1:8000/ >index.html
test -s index.html
kill "$published_server_pid"
wait "$published_server_pid" || true
```

Expected: `git diff --check` has no whitespace errors, the SSH push succeeds, and the newly cloned public `main` serves its Python-only health/page path. Do not force-push, stage unrelated files, or publish while the local clean-clone/core tests are failing. If the public-clone verification fails, fix it in a new commit, rerun Step 2, push the new commit, and repeat this public-clone check; never claim the published URL is usable until it passes.

## Plan Self-Review

- **Spec coverage:** Task 1 removes the abandoned route and preserves the optional bridge; Task 2 supplies verified, package-distributed offline data and source evidence; Tasks 3-5 cover strict contracts, deterministic Astropy/Matplotlib geometry, fixed layers, PNG/JSON SHA linkage, target handling, full cache/downloader integrity, and TTL/bounds; Task 6 replaces the actual `web/dist` coupling with same-origin FastAPI HTML and all HTTP resource limits; Task 7 covers all CLI modes and `--open` ordering; Task 8 migrates README/Skill; Task 9 verifies a clean Python-only clone and pushes. The non-goals, no-CORS/loopback restrictions, and existing outreach routes are explicit global constraints and regression tests.
- **Placeholder scan:** This plan intentionally contains no unverified HYG URL, license, asset filename, or checksum. Task 2 treats their observed values as a mandatory provenance gate before downloader code is committed; no fabricated source constant is allowed. All other files, APIs, test calls, error responses, limits, and commit commands are named concretely.
- **Type consistency:** `SkyChartRequest` is the POST body through `SkyChartService.render`; `RenderedSkyChart` feeds `RenderStore`; `RenderStore` feeds the two export routes; `SkyChartRenderResponse` exposes their same opaque ID. `FullCatalogCache` feeds `select_catalog`, which feeds the renderer. `create_web_app` uses the final `SkyChartService` signature and no `frontend_dir`; legacy `StarSkillMcpService` is retained solely for existing routes.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-23-pure-python-local-sky-chart.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, and use two-stage review.

2. **Inline Execution** - Execute tasks in this session using `executing-plans`, in batches with review checkpoints.
