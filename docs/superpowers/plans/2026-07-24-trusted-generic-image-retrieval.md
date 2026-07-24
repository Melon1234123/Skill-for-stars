# Trusted Generic Astronomy Image Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the M51-only SDSS fetcher with a generic astronomy-image search that discovers public candidates but automatically downloads only validated, registered high-credibility archive content.

**Architecture:** This plan consumes the `TargetRef` resolver from the generalized-targets plan. Provider adapters return normalized candidate metadata and never execute page content; a deterministic trust gate selects a candidate, then a restricted HTTP backend validates redirects, DNS/IP safety, size, MIME, decoded format, and dimensions before cache/provenance publication. M51/SDSS remains a thin compatibility wrapper over the generic request.

**Tech Stack:** Python 3.11+, Pydantic 2, httpx, Astropy, astroquery MAST/ESA Sky, Pillow, astropy.io.fits, pytest.

## Global Constraints

- This plan starts only after `docs/superpowers/plans/2026-07-24-generalized-targets-and-relationships.md` is complete, because every new image request contains a `TargetRef`.
- A `solar_system` image request must include an offset-aware `observed_at`; the target is converted with Astropy `builtin` at that instant before discovery. SIMBAD and direct-coordinate requests may omit it because their first-phase coordinates are fixed ICRS.
- Registered Tier-1 adapters are SDSS DR18, MAST, ESA Sky, and Pan-STARRS; callers may choose only a registered provider ID or `auto_trusted`.
- Open candidate discovery may ingest untrusted page/API metadata, but no downloaded content or metadata field can cause shell execution, browser execution, local-file reads, private-network access, or arbitrary follow-up URLs.
- Automatic download requires HTTPS at the initial and every redirected URL, at most three redirects, a registered provider allowlist match, a license/policy URL, public DNS/IP targets, byte-limit checks before and after streaming, accepted MIME and decoded format, and requested dimension bounds.
- An optional model ranker is metadata-only. It emits strict JSON and cannot confer trust; when configured its selected candidate must have confidence `>= 0.85` in addition to all deterministic gates.
- JPEG, PNG, and FITS are accepted. HTML, SVG, PDF, archives, executable formats, and image bytes whose MIME or decoded format disagree are rejected.
- Live archive/model checks are opt-in smoke tests only. Unit, contract, and acceptance tests use fakes and fixtures with no real network access.
- Keep the legacy `SDSSImageRequest`, `fetch_sdss_image`, `fetch_m51_sdss_image`, M51 filename layout, and existing SDSS metadata fields available as adapters.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/starskill/schemas.py` | Defines generic image request, candidate, rank, trust-decision, provenance, and result models. |
| `src/starskill/image_providers.py` | Registers the four archive adapters and exposes normalized metadata-only discovery. |
| `src/starskill/image_retrieval.py` | Resolves image targets to an ICRS search coordinate at the declared time, ranks candidates, applies the trust gate, downloads bounded content, validates files, manages cache, and writes artifacts. |
| `src/starskill/public_data_fetcher.py` | Retains the SDSS/M51 public API as a converter to `image_retrieval`. |
| `src/starskill/cli.py` | Dispatches generic `fetch-image` requests and keeps the M51 input accepted. |
| `src/starskill/mcp_server.py` | Adds the generic image MCP tool, resource names, and server-owned cache wiring. |
| `tests/test_image_providers.py` | Tests registered provider descriptions and normalized discovery with fakes. |
| `tests/test_image_retrieval.py` | Exercises every trust gate, formats, cache rules, and provenance artifacts. |
| `tests/test_public_data_fetcher.py`, `tests/test_cli.py`, `tests/test_mcp_server.py` | Covers legacy compatibility and transports. |
| `tests/live/test_image_archive_smoke.py` | Contains explicitly skipped-by-default archive smoke checks. |

### Task 1: Define Generic Image Contracts and Provider Registry Metadata

**Files:**
- Modify: `src/starskill/schemas.py:247-285`
- Create: `src/starskill/image_providers.py`
- Create: `tests/test_image_providers.py`
- Modify: `tests/test_schemas.py`

**Interfaces:**
- Consumes `TargetRef` from the generalized-targets plan.
- Produces `AstronomyImageSearchRequest`, `ImageCandidate`, `ImageProviderDescriptor`, `ImageTrustDecision`, `ImageRank`, `ModelRanker`, `ImageSearchResult`, and `ImageProvider`.
- Produces `IMAGE_PROVIDER_REGISTRY: Mapping[str, ImageProvider]` keyed by `sdss_dr18`, `mast`, `esa_sky`, and `panstarrs`.

- [ ] **Step 1: Write failing schema and registry tests.**

```python
def test_generic_image_request_accepts_target_and_registered_provider() -> None:
    request = AstronomyImageSearchRequest.model_validate({
        "target": {"kind": "coordinates", "label": "M31", "ra_deg": 10.684708, "dec_deg": 41.26875},
        "field_of_view_arcmin": 12,
        "bands": ["g", "r", "i"],
        "provider_mode": "panstarrs",
    })
    assert request.allowed_formats == ["jpeg", "png", "fits"]

def test_registry_has_only_declared_tier_one_archives() -> None:
    assert set(IMAGE_PROVIDER_REGISTRY) == {"sdss_dr18", "mast", "esa_sky", "panstarrs"}
    assert all(descriptor.license_url.startswith("https://") for descriptor in (provider.descriptor for provider in IMAGE_PROVIDER_REGISTRY.values()))
```

- [ ] **Step 2: Run focused tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_schemas.py tests/test_image_providers.py -q`

Expected: FAIL because generic image models and the provider registry do not exist.

- [ ] **Step 3: Define immutable request and provider contracts.**

```python
class AstronomyImageSearchRequest(InputModel):
    target: TargetRef
    observed_at: datetime | None = None
    field_of_view_arcmin: float = Field(default=12, gt=0, le=120)
    bands: list[str] = Field(default_factory=list, max_length=8)
    max_width: int = Field(default=2048, ge=64, le=4096)
    max_height: int = Field(default=2048, ge=64, le=4096)
    allowed_formats: list[Literal["jpeg", "png", "fits"]] = Field(default_factory=lambda: ["jpeg", "png", "fits"])
    timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_bytes: int = Field(default=20_000_000, ge=1, le=50_000_000)
    provider_mode: Literal["auto_trusted", "sdss_dr18", "mast", "esa_sky", "panstarrs"] = "auto_trusted"

    @model_validator(mode="after")
    def require_dynamic_target_time(self) -> "AstronomyImageSearchRequest":
        if isinstance(self.target, SolarSystemTargetRef) and self.observed_at is None:
            raise ValueError("solar-system image requests require observed_at")
        if self.observed_at is not None and (self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None):
            raise ValueError("observed_at must include a timezone offset")
        return self
```

Define `ResolvedImageTarget` with `label`, `ra_deg`, `dec_deg`, `coordinate_frame="ICRS"`, `source`, and `observed_at`; it is the only target type accepted by provider discovery. Define `ImageCandidate` with only provider-generated `candidate_id`, `provider_id`, `source_url`, `download_url`, `band`, `format`, dimensions, query parameters, and license URL. The `ImageProvider` protocol must implement `discover(request: AstronomyImageSearchRequest, target: ResolvedImageTarget) -> list[ImageCandidate]`; its descriptor contains organization, allowed HTTPS hosts, allowed redirect hosts, endpoint roots, formats, byte cap, and license URL. Instantiate descriptors for SDSS DR18, MAST, ESA Sky, and Pan-STARRS using their documented fixed API bases.

Define `ImageRank` with `candidate_id`, `confidence: float = Field(ge=0, le=1)`, `relevance: float = Field(ge=0, le=1)`, and bounded `reason`. Define `ModelRanker` as `rank(request: AstronomyImageSearchRequest, candidates: list[ImageCandidate]) -> list[ImageRank]`; validate that it returns one unique rank per candidate and no candidate ID outside the input list. Persist the model ID, model version, prompt hash, validated ranks, and raw structured response in `image_search.json`, but never a credential or provider-request body.

- [ ] **Step 4: Run schema and registry tests.**

Run: `.venv/bin/python -m pytest tests/test_schemas.py tests/test_image_providers.py -q`

Expected: PASS; arbitrary download URLs and unregistered provider identifiers fail validation.

- [ ] **Step 5: Commit contracts and registry metadata.**

```bash
git add src/starskill/schemas.py src/starskill/image_providers.py tests/test_schemas.py tests/test_image_providers.py
git commit -m "feat: define trusted astronomy image providers"
```

### Task 2: Implement Metadata-Only Discovery Adapters

**Files:**
- Modify: `src/starskill/image_providers.py`
- Modify: `tests/test_image_providers.py`
- Create: `tests/fixtures/images/provider_candidates.json`

**Interfaces:**
- Consumes `AstronomyImageSearchRequest` and a resolved ICRS search coordinate at request time.
- Produces `SDSSDr18Provider.discover`, `MastProvider.discover`, `EsaSkyProvider.discover`, and `PanStarrsProvider.discover` returning normalized `ImageCandidate` lists.
- Produces `select_discovery_providers(provider_mode: str, registry: Mapping[str, ImageProvider]) -> Sequence[ImageProvider]`.
- Produces `resolve_image_target(request: AstronomyImageSearchRequest, *, target_backend: TargetBackend | None, cache_dir: Path | None, clock: Callable[[], datetime] = utc_now) -> ResolvedImageTarget`.

- [ ] **Step 1: Write failing adapter normalization tests.**

```python
@pytest.mark.parametrize("provider_id", ["sdss_dr18", "mast", "esa_sky", "panstarrs"])
def test_provider_normalizes_its_fixture_without_downloading(provider_id: str) -> None:
    provider = fake_registry_from_fixture()[provider_id]
    candidates = provider.discover(image_request(), resolved_m31())
    assert candidates
    assert all(candidate.provider_id == provider_id for candidate in candidates)
    assert all(candidate.download_url.startswith("https://") for candidate in candidates)

def test_auto_mode_uses_deterministic_registry_order() -> None:
    assert [p.descriptor.provider_id for p in select_discovery_providers("auto_trusted", fake_registry_from_fixture())] == ["sdss_dr18", "mast", "esa_sky", "panstarrs"]

def test_dynamic_image_target_requires_a_timestamp_and_resolves_at_that_instant() -> None:
    with pytest.raises(ValidationError, match="observed_at"):
        AstronomyImageSearchRequest.model_validate({"target": {"kind": "solar_system", "body": "mars"}})
    target = resolve_image_target(AstronomyImageSearchRequest.model_validate({"target": {"kind": "solar_system", "body": "mars"}, "observed_at": "2026-01-10T18:00:00+08:00"}), target_backend=None, cache_dir=None)
    assert (target.coordinate_frame, target.observed_at.isoformat()) == ("ICRS", "2026-01-10T10:00:00+00:00")
```

- [ ] **Step 2: Run adapter tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_image_providers.py -q`

Expected: FAIL because adapters and provider selection do not exist.

- [ ] **Step 3: Implement explicit query builders and metadata normalization.**

```python
def select_discovery_providers(provider_mode: str, registry: Mapping[str, ImageProvider]) -> Sequence[ImageProvider]:
    if provider_mode == "auto_trusted":
        return tuple(registry[provider_id] for provider_id in ("sdss_dr18", "mast", "esa_sky", "panstarrs"))
    return (registry[provider_mode],)

def _candidate(provider: ImageProviderDescriptor, *, candidate_id: str, source_url: str, download_url: str,
               image_format: str, width: int | None, height: int | None, query: dict[str, str | int | float], band: str | None) -> ImageCandidate:
    return ImageCandidate(candidate_id=candidate_id, provider_id=provider.provider_id, source_url=source_url,
        download_url=download_url, format=image_format, width=width, height=height, band=band,
        query_parameters=query, license_url=provider.license_url)
```

Each adapter may issue only its fixed archive API query and must turn a malformed provider response into `ImageDiscoveryError(code="image_discovery_error")`. Do not parse HTML, execute JavaScript, or accept a URL supplied in response prose. Use injected small HTTP/query clients in adapter constructors so tests provide fixture responses rather than invoking live archives.

`resolve_image_target` must delegate SIMBAD/direct-coordinate handling to `resolve_target_ref`; for a solar-system target it uses the required `observed_at`, `solar_system_ephemeris.set("builtin")`, `get_body`, and `SkyCoord.icrs` to construct an ICRS coordinate. Persist that exact instant and source in `ResolvedImageTarget`; do not use the current clock as an implicit dynamic-target query time.

- [ ] **Step 4: Run discovery tests.**

Run: `.venv/bin/python -m pytest tests/test_image_providers.py -q`

Expected: PASS; every adapter returns normalized candidates and none fetches image bytes.

- [ ] **Step 5: Commit metadata-only discovery.**

```bash
git add src/starskill/image_providers.py tests/test_image_providers.py tests/fixtures/images/provider_candidates.json
git commit -m "feat: discover astronomy image candidates"
```

### Task 3: Build the Deterministic Trust Gate and Bounded Downloader

**Files:**
- Create: `src/starskill/image_retrieval.py`
- Create: `tests/test_image_retrieval.py`
- Modify: `src/starskill/schemas.py`

**Interfaces:**
- Consumes `ImageCandidate`, `ImageProviderDescriptor`, `AstronomyImageSearchRequest`.
- Produces `validate_candidate(candidate: ImageCandidate, descriptor: ImageProviderDescriptor, *, rank: ImageRank | None) -> ImageTrustDecision`.
- Produces `RestrictedImageHttpClient.fetch(candidate: ImageCandidate, descriptor: ImageProviderDescriptor, *, timeout_seconds: int, max_bytes: int) -> DownloadedImage`.
- Produces `validate_downloaded_image(downloaded: DownloadedImage, request: AstronomyImageSearchRequest) -> ValidatedImage`.

- [ ] **Step 1: Write failing trust-gate regression tests.**

```python
@pytest.mark.parametrize("mutation,expected_code", [
    (lambda c: c.model_copy(update={"download_url": "http://example.org/x.jpg"}), "non_https_url"),
    (lambda c: c.model_copy(update={"download_url": "https://evil.example/x.jpg"}), "unregistered_download_host"),
    (lambda c: c.model_copy(update={"license_url": None}), "missing_license_evidence"),
])
def test_candidate_gate_rejects_untrusted_metadata(mutation, expected_code) -> None:
    decision = validate_candidate(mutation(trusted_candidate()), sdss_descriptor(), rank=None)
    assert (decision.allowed, decision.reason_code) == (False, expected_code)

def test_ranker_cannot_override_deterministic_gate() -> None:
    decision = validate_candidate(untrusted_host_candidate(), sdss_descriptor(), rank=ImageRank(candidate_id="x", confidence=1.0, relevance=1.0, reason="x"))
    assert decision.allowed is False

def test_downloader_rejects_private_redirect_before_connecting() -> None:
    with pytest.raises(ImageDownloadError, match="private_redirect_target"):
        RestrictedImageHttpClient(FakeTransport.redirect_to("https://127.0.0.1/image.jpg")).fetch(trusted_candidate(), sdss_descriptor(), timeout_seconds=5, max_bytes=1024)
```

- [ ] **Step 2: Run trust tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_image_retrieval.py -q`

Expected: FAIL because the trust gate and restricted client do not exist.

- [ ] **Step 3: Implement ordered gate checks and streaming limits.**

```python
def validate_candidate(candidate: ImageCandidate, descriptor: ImageProviderDescriptor, *, rank: ImageRank | None) -> ImageTrustDecision:
    parsed = urlsplit(candidate.download_url)
    if parsed.scheme != "https": return ImageTrustDecision(allowed=False, reason_code="non_https_url")
    if parsed.hostname not in descriptor.allowed_hosts: return ImageTrustDecision(allowed=False, reason_code="unregistered_download_host")
    if not candidate.license_url: return ImageTrustDecision(allowed=False, reason_code="missing_license_evidence")
    if rank is not None and rank.confidence < 0.85: return ImageTrustDecision(allowed=False, reason_code="model_confidence_below_threshold")
    return ImageTrustDecision(allowed=True, reason_code="trusted")
```

Use `httpx.Client(follow_redirects=False)` and manually permit at most three `301`, `302`, `303`, `307`, or `308` hops. For every hop, require `https`, an adapter-allowed host, and DNS results for which `ipaddress.ip_address(address).is_global` is true. Reject invalid `Content-Length` or a value above `max_bytes` before streaming. Stream chunks and fail as soon as cumulative bytes exceed the limit. Do not provide a generic `fetch(url)` API; the client accepts the already-gated candidate and its descriptor only.

- [ ] **Step 4: Add MIME, decode, format, and dimension tests and implementation.**

```python
@pytest.mark.parametrize("content_type,body,expected", [
    ("image/jpeg", jpeg_bytes(64, 64), "jpeg"),
    ("image/png", png_bytes(64, 64), "png"),
    ("image/fits", fits_bytes(64, 64), "fits"),
])
def test_valid_downloaded_formats_are_verified(content_type: str, body: bytes, expected: str) -> None:
    image = validate_downloaded_image(DownloadedImage(body=body, content_type=content_type, redirect_chain=[]), image_request())
    assert image.format == expected
```

Decode JPEG/PNG with Pillow and FITS with `astropy.io.fits`; verify headers before trusting dimensions; require declared MIME, detected format, and request `allowed_formats` to agree. Reject HTML/SVG/PDF and malformed image bytes with distinct `mime_not_allowed`, `decoded_format_mismatch`, or `invalid_image_content` codes. Require decoded width/height to be positive and not exceed the request limits.

- [ ] **Step 5: Run the full trust test module.**

Run: `.venv/bin/python -m pytest tests/test_image_retrieval.py -q`

Expected: PASS, including private-IP redirects, missing licenses, low ranks, byte limits, MIME/decode mismatches, JPEG/PNG/FITS, and dimensions.

- [ ] **Step 6: Commit the restricted retrieval layer.**

```bash
git add src/starskill/image_retrieval.py src/starskill/schemas.py tests/test_image_retrieval.py
git commit -m "feat: enforce trusted astronomy image downloads"
```

### Task 4: Orchestrate Search, Ranking, Cache, and Provenance Artifacts

**Files:**
- Modify: `src/starskill/image_retrieval.py`
- Modify: `src/starskill/schemas.py`
- Modify: `tests/test_image_retrieval.py`

**Interfaces:**
- Consumes a provider registry, restricted client, optional `ModelRanker`, target resolver, and cache root.
- Produces `search_astronomy_images(request: AstronomyImageSearchRequest, *, cache_dir: Path, providers: Mapping[str, ImageProvider], target_backend: TargetBackend | None = None, ranker: ModelRanker | None = None, http_client: RestrictedImageHttpClient | None = None, clock: Callable[[], datetime] = utc_now) -> ImageSearchResult`.
- Produces `write_image_search_artifacts(result: ImageSearchResult, output_dir: Path) -> None` which writes `image_search.json`, `image_metadata.json`, raw data, display PNG, and a hash-bearing `run.json` record.

- [ ] **Step 1: Write failing orchestration and cache tests.**

```python
def test_search_writes_full_provenance_without_model(tmp_path: Path) -> None:
    result = search_astronomy_images(image_request(), cache_dir=tmp_path / "cache", providers=fake_registry(), http_client=fake_image_client())
    write_image_search_artifacts(result, tmp_path / "run")
    search = json.loads((tmp_path / "run" / "image_search.json").read_text())
    metadata = json.loads((tmp_path / "run" / "image_metadata.json").read_text())
    assert search["selected_candidate_id"] == result.selected_candidate.candidate_id
    assert metadata["sha256"] == hashlib.sha256((tmp_path / "run" / "data" / "source.png").read_bytes()).hexdigest()

def test_hash_mismatched_cache_is_not_reused(tmp_path: Path) -> None:
    first = search_astronomy_images(image_request(), cache_dir=tmp_path, providers=fake_registry(), http_client=fake_image_client())
    first.cache_path.write_bytes(b"corrupt")
    second = search_astronomy_images(image_request(), cache_dir=tmp_path, providers=fake_registry(), http_client=fake_image_client())
    assert second.from_cache is False

def test_no_trusted_candidate_reports_reasons_without_download(tmp_path: Path) -> None:
    result = search_astronomy_images(image_request(), cache_dir=tmp_path, providers=only_untrusted_registry(), http_client=FailIfCalledClient())
    assert result.status == "requires_human_review"
    assert result.selected_candidate is None
```

- [ ] **Step 2: Run orchestration tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_image_retrieval.py -q`

Expected: FAIL because no generic orchestration function or provenance artifact writer exists.

- [ ] **Step 3: Implement selection and cache keying with auditable failures.**

```python
def _cache_key(candidate: ImageCandidate, validated: ValidatedImage) -> str:
    material = json.dumps({"provider": candidate.provider_id, "url": candidate.download_url, "sha256": validated.sha256}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()

def _select(candidates: list[ImageCandidate], decisions: dict[str, ImageTrustDecision], ranks: dict[str, ImageRank]) -> ImageCandidate | None:
    allowed = [candidate for candidate in candidates if decisions[candidate.candidate_id].allowed]
    return min(allowed, key=lambda candidate: (-ranks.get(candidate.candidate_id, ImageRank.zero(candidate.candidate_id)).confidence, candidate.provider_id, candidate.candidate_id), default=None)
```

At the start of `search_astronomy_images`, call `resolve_image_target` once and pass its returned ICRS coordinate to every provider. Collect the resolved image target, every discovered candidate, gate decision, optional strict rank response, selected candidate, and rejection reason in `image_search.json`. Store no model credential. Cache raw bytes and a serialized metadata sidecar only after full validation; on a cache hit, recompute SHA-256 and revalidate metadata before returning `from_cache=True`. The final metadata must record original source URL, policy URL, fixed query parameters, redirect chain, response content type, detected format, byte count, dimensions, SHA-256, cache status, and display-processing steps. Generate the display PNG from accepted raw image data only and do not label it as raw FITS content.

- [ ] **Step 4: Run image retrieval tests.**

Run: `.venv/bin/python -m pytest tests/test_image_retrieval.py tests/test_image_providers.py -q`

Expected: PASS; no candidate result writes a fabricated image or uses an unrelated historical cache entry.

- [ ] **Step 5: Commit search and artifact publication.**

```bash
git add src/starskill/image_retrieval.py src/starskill/schemas.py tests/test_image_retrieval.py
git commit -m "feat: record trusted astronomy image searches"
```

### Task 5: Preserve SDSS/M51 Compatibility and Expose CLI/MCP

**Files:**
- Modify: `src/starskill/public_data_fetcher.py:1-260`
- Modify: `src/starskill/cli.py:24-430`
- Modify: `src/starskill/mcp_server.py:22-270`
- Modify: `tests/test_public_data_fetcher.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Retains `fetch_sdss_image(request: SDSSImageRequest, *, cache_dir: Path, source_path: Path, display_path: Path, backend: ImageBackend, clock: Callable[[], datetime]) -> PublicImageResult` as an adapter to `search_astronomy_images` constrained to `sdss_dr18`.
- CLI: `starskill fetch-image INPUT --output-dir DIR --cache-dir DIR` accepts `AstronomyImageSearchRequest` and legacy `SDSSImageRequest`.
- MCP: `StarSkillMcpService.fetch_astronomy_image(request: dict[str, Any]) -> dict[str, Any]` writes generic artifacts in a service-owned run; `fetch_m51_sdss_image` stays available.

- [ ] **Step 1: Write failing compatibility and transport tests.**

```python
def test_legacy_m51_sdss_request_uses_generic_sdss_provider(tmp_path: Path) -> None:
    result = fetch_sdss_image(SDSSImageRequest(), cache_dir=tmp_path / "cache", source_path=tmp_path / "data" / "m51_sdss.jpg", display_path=tmp_path / "figures" / "m51_display.png", backend=FakeImageBackend(jpeg_bytes(512, 512)), clock=fixed_clock)
    assert result.request.target_name == "M51"
    assert result.source.database == "SDSS SkyServer"

def test_mcp_generic_fetch_returns_only_resource_uris(service: StarSkillMcpService) -> None:
    result = service.fetch_astronomy_image(generic_image_payload())
    assert result["ok"] is True
    assert set(result["resources"]).issuperset({"image-search", "image-metadata"})
    assert "cache_dir" not in result
```

- [ ] **Step 2: Run legacy and transport tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_public_data_fetcher.py tests/test_cli.py tests/test_mcp_server.py -q`

Expected: FAIL because neither generic fetch dispatch nor generic MCP image tool exists.

- [ ] **Step 3: Implement adapters without duplicating download policy.**

```python
def _legacy_request_to_generic(request: SDSSImageRequest) -> AstronomyImageSearchRequest:
    return AstronomyImageSearchRequest(
        target=CoordinateTargetRef(kind="coordinates", label="M51", ra_deg=request.ra_deg, dec_deg=request.dec_deg),
        field_of_view_arcmin=request.width * request.scale_arcsec_per_pixel / 60,
        max_width=request.width, max_height=request.height, allowed_formats=["jpeg"],
        timeout_seconds=request.timeout_seconds, max_bytes=request.max_bytes, provider_mode="sdss_dr18",
    )
```

Use `TypeAdapter(AstronomyImageSearchRequest | SDSSImageRequest)` in CLI dispatch. Add MCP resource entries `image-search: image_search.json` and retain `image-metadata`. The MCP generic method must inject only its configured provider registry, `image_cache_dir`, target backend factory, restricted HTTP client factory, and optional ranker factory. It must never accept provider definitions, URLs, cache paths, local paths, or model credentials from the client.

- [ ] **Step 4: Run compatibility and transport regressions.**

Run: `.venv/bin/python -m pytest tests/test_public_data_fetcher.py tests/test_cli.py tests/test_mcp_server.py -q`

Expected: PASS. Existing M51 fixtures retain their filenames and legacy metadata shape; generic tools publish the two new JSON resources.

- [ ] **Step 5: Commit adapters and transports.**

```bash
git add src/starskill/public_data_fetcher.py src/starskill/cli.py src/starskill/mcp_server.py tests/test_public_data_fetcher.py tests/test_cli.py tests/test_mcp_server.py
git commit -m "feat: expose trusted generic image retrieval"
```

### Task 6: Document Boundaries and Run Offline, Live, and Fresh-Clone Acceptance

**Files:**
- Modify: `README.md`
- Modify: `skills/run-starskill/SKILL.md`
- Modify: `skills/run-starskill/references/cli-contract.md`
- Modify: `tests/test_evaluation_cases.py`
- Modify: `tests/test_evaluation_replay.py`
- Create: `tests/live/test_image_archive_smoke.py`
- Modify: `docs/starskill-evaluation/acceptance-2026-07-23.md`

**Interfaces:**
- Adds a generic image acceptance fixture whose provider response and image bytes are local and hash-checked.
- Adds opt-in marker `live_archive` so normal `pytest` excludes live providers and ranking calls.
- Documents provider registration, discovery versus auto-download, model ranking boundary, all rejection classes, and artifact provenance fields.

- [ ] **Step 1: Write failing offline acceptance and live-marker collection tests.**

```python
def test_generic_image_replay_records_search_and_metadata_hashes() -> None:
    execution = execute_case(load_case("generic-image-coordinate"), runs_root=tmp_path / "runs")
    assert execution.return_code == 0
    assert (execution.run_dir / "image_search.json").is_file()
    assert sha256_file(execution.run_dir / "image_metadata.json") == execution.manifest.artifact_hashes["image_metadata.json"]

def test_live_archive_tests_are_not_selected_by_default(pytester: pytest.Pytester) -> None:
    result = pytester.runpytest("-q", "--collect-only")
    assert "test_sdss_live_smoke" not in result.stdout.str()
```

- [ ] **Step 2: Run acceptance/document test scope and verify it fails.**

Run: `.venv/bin/python -m pytest tests/test_evaluation_cases.py tests/test_evaluation_replay.py -q`

Expected: FAIL because generic image fixtures and the `live_archive` marker are missing.

- [ ] **Step 3: Add bounded documentation and opt-in smoke tests.**

Document that discovery metadata is untrusted, automatic download is restricted to registered Tier-1 archive candidates, model scores do not grant trust, and each failure is recorded in `image_search.json`. Place real provider smoke functions behind `@pytest.mark.live_archive` and require `STARSKILL_LIVE_ARCHIVE=1`; each smoke test uses one fixed M31 request, writes an isolated temporary run, and asserts only that trusted artifacts validate. Do not make live tests part of normal CI or recorded offline acceptance.

- [ ] **Step 4: Run full offline tests, syntax checks, and an opt-in smoke command that is skipped by default.**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS with no network usage.

Run: `.venv/bin/python -m pytest tests/live/test_image_archive_smoke.py -m live_archive -q`

Expected: SKIPPED unless `STARSKILL_LIVE_ARCHIVE=1` is deliberately set.

Run: `git diff --check`

Expected: no output and exit `0`.

- [ ] **Step 5: Perform fresh-clone acceptance and synchronize the installed Skill after publication.**

Run:

```bash
STARSKILL_FRESH_DIR="$(mktemp -d /tmp/starskill-fresh.XXXXXX)"
git clone --branch main --single-branch "$(git config --get remote.origin.url)" "$STARSKILL_FRESH_DIR"
cd "$STARSKILL_FRESH_DIR"
python3.11 -m venv .venv
.venv/bin/python -m pip install ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m starskill relationship examples/relationships/mars_m31.json --output /tmp/starskill-mars-m31.csv --metadata /tmp/starskill-mars-m31.json
```

Expected: the clone is from the published `origin/main`, installation succeeds with Python 3.11+, the full offline suite passes, and the generalized relationship command exits `0` with schema `2.0` metadata. After that verified publication, update the globally installed `run-starskill` Skill from that same `origin/main` revision and repeat its documented generic relationship smoke command; record the remote commit ID and command outputs in the acceptance note.

- [ ] **Step 6: Commit acceptance and documentation.**

```bash
git add README.md skills/run-starskill tests/test_evaluation_cases.py tests/test_evaluation_replay.py tests/live docs/starskill-evaluation
git commit -m "docs: specify trusted astronomy image retrieval"
```
