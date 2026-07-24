# Generalized Astronomy Targets and Relationships Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one reusable target-reference model so StarSkill can calculate observer-specific apparent relationships for every supported ordered pair of solar-system, SIMBAD, and direct ICRS-coordinate targets while preserving the Moon-Jupiter v1 contract.

**Architecture:** `TargetRef` is a Pydantic discriminated union in the schema layer and is resolved by one domain service into either a dynamic solar-system target or a fixed ICRS target. The generalized relationship calculator consumes that resolved representation and produces schema-v2 artifacts; the legacy task is an input/output adapter over the same calculator. Observation, ephemeris, CLI, MCP, and the local chart use the same resolver rather than independently classifying strings.

**Tech Stack:** Python 3.11+, Pydantic 2, Astropy 7.2 `builtin` ephemeris, astroquery SIMBAD, pytest, FastMCP.

## Global Constraints

- `TargetRef` supports only `solar_system`, `simbad`, and `coordinates`; no caller supplies URLs, paths, or ephemeris provider settings.
- Supported dynamic solar-system bodies are exactly `sun`, `moon`, and `mercury` through `neptune`; `pluto`, comets, asteroids, and all other names fail with `unsupported_solar_system_body`.
- Fixed targets use ICRS coordinates and solar-system targets use Astropy `solar_system_ephemeris.set("builtin")`; IERS auto-download remains disabled and atmospheric pressure is `0 hPa`.
- Relationship v2 reports apparent AltAz, above-horizon visibility (`altitude_deg >= 0`), and apparent angular separation only. It must not report physical distance or astronomical-event claims.
- Keep `SolarSystemRelationshipTask`, `SolarSystemRelationshipResult`, their `moon_*` / `jupiter_*` CSV columns, `calculate_solar_system_relationship`, and `calculate_moon_jupiter_relationship` as v1-compatible adapters.
- Tests must use fixed times, locations, fake SIMBAD backends, and offline IERS data. No test calls a live catalog, image archive, or model.
- Preserve existing M42, Moon-Jupiter, and sky-chart behavior while extending their accepted target input.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/starskill/schemas.py` | Defines target references, generalized relationship/ephemeris models, and legacy adapters' retained models. |
| `src/starskill/target_references.py` | Normalizes and resolves `TargetRef` through Astropy or the existing SIMBAD resolver. |
| `src/starskill/solar_system_relationship.py` | Computes generic apparent positions, writes v2 artifacts, and adapts legacy Moon-Jupiter results. |
| `src/starskill/ephemeris_calculator.py` | Calculates an ephemeris from a resolved dynamic or fixed target. |
| `src/starskill/pipeline.py` | Accepts a normalized `TargetRef` for observation runs and records its provenance. |
| `src/starskill/sky_chart_targets.py` | Converts the chart target input to `TargetRef` and delegates resolution to the core service. |
| `src/starskill/cli.py` | Validates and dispatches generic target references for resolve, ephemeris, plan, run, and relationship inputs without changing v1 command arguments. |
| `src/starskill/mcp_server.py` | Exposes generic target resolution and relationship tools while retaining legacy MCP wrappers. |
| `tests/test_target_references.py` | Covers union validation, resolution, cache behavior, and unsupported-body failures. |
| `tests/test_astronomical_relationship.py` | Covers all nine ordered target-kind pairs, artifacts, and v1 equivalence. |
| `tests/test_ephemeris_calculator.py`, `tests/test_pipeline.py`, `tests/test_sky_chart_targets.py`, `tests/test_cli.py`, `tests/test_mcp_server.py` | Contract regressions at each transport and existing workflow boundary. |
| `examples/relationships/*.json` | Fixed v2 inputs for Mars-Saturn, Mars-M31, M31-coordinate, and coordinate-coordinate acceptance. |

### Task 1: Define `TargetRef` and Generalized Result Schemas

**Files:**
- Modify: `src/starskill/schemas.py:1-285`
- Modify: `tests/test_schemas.py:1-160`
- Create: `tests/test_target_references.py`

**Interfaces:**
- Produces `TargetRef = Annotated[SolarSystemTargetRef | SimbadTargetRef | CoordinateTargetRef, Field(discriminator="kind")]`.
- Produces `AstronomicalRelationshipTask`, `ResolvedAstronomicalTarget`, `AstronomicalRelationshipSample`, and `AstronomicalRelationshipResult`.
- Retains `SolarSystemRelationshipTask` and `SolarSystemRelationshipResult` as v1 models.

- [ ] **Step 1: Write failing discriminated-union and validation tests.**

```python
from pydantic import TypeAdapter, ValidationError
from starskill.schemas import AstronomicalRelationshipTask, TargetRef

def test_target_ref_accepts_each_supported_kind() -> None:
    adapter = TypeAdapter(TargetRef)
    assert adapter.validate_python({"kind": "solar_system", "body": "Mars"}).body == "mars"
    assert adapter.validate_python({"kind": "simbad", "name": "M31"}).name == "M31"
    assert adapter.validate_python(
        {"kind": "coordinates", "label": "Andromeda center", "ra_deg": 10.684708, "dec_deg": 41.26875}
    ).ra_deg == 10.684708

def test_coordinates_and_general_relationship_reject_invalid_contracts(valid_observer: dict) -> None:
    with pytest.raises(ValidationError, match="ra_deg"):
        TypeAdapter(TargetRef).validate_python({"kind": "coordinates", "label": "x", "ra_deg": 360, "dec_deg": 0})
    task = AstronomicalRelationshipTask.model_validate({
        "task_type": "astronomical_relationship",
        "primary": {"kind": "coordinates", "label": "A", "ra_deg": 0, "dec_deg": 0},
        "secondary": {"kind": "coordinates", "label": "B", "ra_deg": 1, "dec_deg": 1},
        "observer": valid_observer,
        "time_range": {"start": "2026-01-10T18:00:00+08:00", "end": "2026-01-10T18:20:00+08:00"},
    })
    assert task.interval_minutes == 20
```

- [ ] **Step 2: Run the focused schema tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_schemas.py tests/test_target_references.py -q`

Expected: FAIL during collection because `TargetRef` and `AstronomicalRelationshipTask` do not exist.

- [ ] **Step 3: Add the exact schema hierarchy.**

```python
class SolarSystemTargetRef(InputModel):
    kind: Literal["solar_system"]
    body: str

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        body = " ".join(value.split()).casefold()
        if not body or len(body) > 64 or not re.fullmatch(r"[a-z][a-z0-9_ -]*", body):
            raise ValueError("solar-system body must be a safe non-empty name")
        return body

class SimbadTargetRef(InputModel):
    kind: Literal["simbad"]
    name: str

class CoordinateTargetRef(InputModel):
    kind: Literal["coordinates"]
    label: str = Field(min_length=1, max_length=120)
    ra_deg: float = Field(ge=0, lt=360, allow_inf_nan=False)
    dec_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)

TargetRef = Annotated[
    SolarSystemTargetRef | SimbadTargetRef | CoordinateTargetRef,
    Field(discriminator="kind"),
]
```

Define the generalized task with ordered `primary: TargetRef` and `secondary: TargetRef`. Define each sample with `primary_altitude_deg`, `primary_azimuth_deg`, `primary_is_above_horizon`, equivalent `secondary_*` fields, and `angular_separation_deg`. Define result settings with `schema_version: Literal["2.0"] = "2.0"`, `time_scale="UTC"`, `horizontal_frame="AltAz"`, `solar_system_ephemeris="builtin"`, `atmospheric_refraction=False`, and `iers_auto_download=False`. Give `ResolvedAstronomicalTarget` `label`, `kind`, `motion: Literal["dynamic", "fixed_icrs"]`, `ra_deg`, `dec_deg`, `source`, and optional `catalog_target: ResolvedTarget` so each calculation has auditable provenance.

- [ ] **Step 4: Run schema tests and the existing schema suite.**

Run: `.venv/bin/python -m pytest tests/test_schemas.py tests/test_target_references.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the independently validated schema contract.**

```bash
git add src/starskill/schemas.py tests/test_schemas.py tests/test_target_references.py
git commit -m "feat: define generalized astronomy target references"
```

### Task 2: Resolve Dynamic and Fixed Targets Through One Core Service

**Files:**
- Create: `src/starskill/target_references.py`
- Modify: `src/starskill/target_resolver.py:15-166`
- Modify: `src/starskill/sky_chart_targets.py:1-79`
- Modify: `tests/test_target_references.py`
- Modify: `tests/test_sky_chart_targets.py`

**Interfaces:**
- Consumes `TargetRef`, `TargetBackend`, `resolve_target`, `ResolvedTarget`.
- Produces `resolve_target_ref(target: TargetRef, *, backend: TargetBackend | None, cache_dir: Path | None, clock: Callable[[], datetime] = utc_now) -> ResolvedAstronomicalTarget`.
- Produces `SUPPORTED_SOLAR_SYSTEM_BODIES: Mapping[str, str]` and `UnsupportedSolarSystemBodyError(code="unsupported_solar_system_body")`.

- [ ] **Step 1: Write failing resolution tests with a fake SIMBAD backend.**

```python
def test_resolve_target_ref_marks_motion_and_provenance(tmp_path: Path) -> None:
    solar = resolve_target_ref(
        TypeAdapter(TargetRef).validate_python({"kind": "solar_system", "body": "mars"})
    )
    catalog = resolve_target_ref(
        TypeAdapter(TargetRef).validate_python({"kind": "simbad", "name": "M31"}),
        backend=StaticSimbadBackend(), cache_dir=tmp_path,
    )
    direct = resolve_target_ref(
        TypeAdapter(TargetRef).validate_python({"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20})
    )
    assert (solar.motion, solar.source.provider) == ("dynamic", "astropy_builtin_ephemeris")
    assert (catalog.motion, catalog.catalog_target.canonical_name) == ("fixed_icrs", "M 31")
    assert (direct.motion, direct.source.provider, direct.ra_deg) == ("fixed_icrs", "user_coordinates", 10)

def test_pluto_is_an_explicit_unsupported_solar_system_failure() -> None:
    ref = TypeAdapter(TargetRef).validate_python({"kind": "solar_system", "body": "pluto"})
    with pytest.raises(UnsupportedSolarSystemBodyError) as exc_info:
        resolve_target_ref(ref)
    assert exc_info.value.code == "unsupported_solar_system_body"
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `.venv/bin/python -m pytest tests/test_target_references.py -q`

Expected: FAIL because `resolve_target_ref` and `UnsupportedSolarSystemBodyError` do not exist.

- [ ] **Step 3: Implement deterministic target resolution and make the chart delegate.**

```python
SUPPORTED_SOLAR_SYSTEM_BODIES = MappingProxyType({
    "sun": "Sun", "moon": "Moon", "mercury": "Mercury", "venus": "Venus",
    "mars": "Mars", "jupiter": "Jupiter", "saturn": "Saturn",
    "uranus": "Uranus", "neptune": "Neptune",
})

def resolve_target_ref(target: TargetRef, *, backend: TargetBackend | None = None,
                       cache_dir: Path | None = None,
                       clock: Callable[[], datetime] = utc_now) -> ResolvedAstronomicalTarget:
    if isinstance(target, SolarSystemTargetRef):
        label = SUPPORTED_SOLAR_SYSTEM_BODIES.get(target.body)
        if label is None:
            raise UnsupportedSolarSystemBodyError(f"builtin ephemeris does not support: {target.body}")
        return ResolvedAstronomicalTarget(label=label, kind=target.kind, motion="dynamic", ra_deg=None, dec_deg=None,
            source=AstronomicalTargetSource(provider="astropy_builtin_ephemeris", from_cache=False, accessed_at=clock()))
    if isinstance(target, CoordinateTargetRef):
        return ResolvedAstronomicalTarget(label=target.label, kind=target.kind, motion="fixed_icrs", ra_deg=target.ra_deg, dec_deg=target.dec_deg,
            source=AstronomicalTargetSource(provider="user_coordinates", from_cache=False, accessed_at=clock()))
    if backend is None:
        raise TargetServiceError("SIMBAD target resolution requires a target backend")
    catalog_target = resolve_target(target.name, backend=backend, cache_dir=cache_dir, clock=clock)
    return ResolvedAstronomicalTarget(label=catalog_target.canonical_name, kind=target.kind, motion="fixed_icrs", ra_deg=catalog_target.ra_deg, dec_deg=catalog_target.dec_deg,
        source=AstronomicalTargetSource(provider="simbad_cache" if catalog_target.source.from_cache else "simbad", from_cache=catalog_target.source.from_cache, accessed_at=catalog_target.source.accessed_at), catalog_target=catalog_target)
```

Replace `SkyChartTargetResolver`'s duplicated solar-system mapping and direct coordinate construction with a conversion from `SkyChartTarget` to `TargetRef`, then use an injected `resolve_target_ref` adapter. Keep its existing `ResolvedSkyTarget` output until the chart API is migrated in a later compatibility-preserving change.

- [ ] **Step 4: Run target resolver and chart target tests.**

Run: `.venv/bin/python -m pytest tests/test_target_resolver.py tests/test_target_references.py tests/test_sky_chart_targets.py -q`

Expected: PASS, including the explicit Pluto error and no SIMBAD query for direct coordinates.

- [ ] **Step 5: Commit resolution behavior.**

```bash
git add src/starskill/target_references.py src/starskill/target_resolver.py src/starskill/sky_chart_targets.py tests/test_target_references.py tests/test_sky_chart_targets.py
git commit -m "feat: resolve generalized astronomy targets"
```

### Task 3: Calculate Generalized Apparent Relationships and Preserve v1 Artifacts

**Files:**
- Modify: `src/starskill/solar_system_relationship.py:1-127`
- Modify: `tests/test_solar_system_relationship.py`
- Create: `tests/test_astronomical_relationship.py`

**Interfaces:**
- Consumes `AstronomicalRelationshipTask`, `resolve_target_ref`, `build_time_grid`.
- Produces `calculate_astronomical_relationship(task: AstronomicalRelationshipTask, *, target_backend: TargetBackend | None = None, cache_dir: Path | None = None, clock: Callable[[], datetime] = utc_now) -> AstronomicalRelationshipResult`.
- Produces `write_astronomical_relationship_csv(result: AstronomicalRelationshipResult, output_path: Path) -> None`.
- Retains `calculate_solar_system_relationship(task: SolarSystemRelationshipTask, *, clock: Callable[[], datetime] = utc_now) -> SolarSystemRelationshipResult` by calling the generic calculator and adapting its fields.

- [ ] **Step 1: Write failing tests for all target-kind combinations and legacy equivalence.**

```python
@pytest.mark.parametrize("primary,secondary", [
    ({"kind": "solar_system", "body": "mars"}, {"kind": "solar_system", "body": "saturn"}),
    ({"kind": "solar_system", "body": "mars"}, {"kind": "simbad", "name": "M31"}),
    ({"kind": "solar_system", "body": "mars"}, {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20}),
    ({"kind": "simbad", "name": "M31"}, {"kind": "solar_system", "body": "mars"}),
    ({"kind": "simbad", "name": "M31"}, {"kind": "simbad", "name": "M42"}),
    ({"kind": "simbad", "name": "M31"}, {"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20}),
    ({"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20}, {"kind": "solar_system", "body": "mars"}),
    ({"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20}, {"kind": "simbad", "name": "M31"}),
    ({"kind": "coordinates", "label": "C", "ra_deg": 10, "dec_deg": 20}, {"kind": "coordinates", "label": "D", "ra_deg": 11, "dec_deg": 21}),
])
def test_all_ordered_target_kinds_produce_apparent_altaz(primary: dict, secondary: dict) -> None:
    result = calculate_astronomical_relationship(make_task(primary, secondary), target_backend=StaticSimbadBackend())
    assert result.settings.schema_version == "2.0"
    assert all(0 <= sample.angular_separation_deg <= 180 for sample in result.samples)
    assert all(sample.primary_is_above_horizon == (sample.primary_altitude_deg >= 0) for sample in result.samples)

def test_legacy_moon_jupiter_fields_are_adapted_from_v2() -> None:
    legacy = calculate_solar_system_relationship(legacy_moon_jupiter_task())
    generic = calculate_astronomical_relationship(as_generic_moon_jupiter_task())
    assert legacy.samples[0].moon_altitude_deg == pytest.approx(generic.samples[0].primary_altitude_deg)
    assert legacy.samples[0].jupiter_azimuth_deg == pytest.approx(generic.samples[0].secondary_azimuth_deg)
```

- [ ] **Step 2: Run the generic relationship tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_astronomical_relationship.py tests/test_solar_system_relationship.py -q`

Expected: FAIL because `calculate_astronomical_relationship` and the v2 artifact writer do not exist.

- [ ] **Step 3: Implement one coordinate-construction path and two writers.**

```python
def _to_altaz(target: ResolvedAstronomicalTarget, *, times: Time, location: EarthLocation, frame: AltAz) -> SkyCoord:
    if target.motion == "dynamic":
        assert target.kind == "solar_system"
        return get_body(target.label.casefold(), times, location=location).transform_to(frame)
    assert target.ra_deg is not None and target.dec_deg is not None
    return SkyCoord(ra=target.ra_deg * u.deg, dec=target.dec_deg * u.deg, frame="icrs").transform_to(frame)

def calculate_astronomical_relationship(task: AstronomicalRelationshipTask, *, target_backend: TargetBackend | None = None,
                                        cache_dir: Path | None = None, clock: Callable[[], datetime] = utc_now) -> AstronomicalRelationshipResult:
    primary = resolve_target_ref(task.primary, backend=target_backend, cache_dir=cache_dir, clock=clock)
    secondary = resolve_target_ref(task.secondary, backend=target_backend, cache_dir=cache_dir, clock=clock)
    points = build_time_grid(start=task.time_range.start, end=task.time_range.end,
                             timezone_name=task.observer.timezone, interval_minutes=task.interval_minutes)
    with TemporaryDirectory(prefix="starskill-astropy-") as cache_dir:
        with set_temp_cache(cache_dir), iers.conf.set_temp("auto_download", False), solar_system_ephemeris.set("builtin"):
            times = Time([point.utc for point in points], scale="utc")
            location = EarthLocation(lon=task.observer.longitude * u.deg, lat=task.observer.latitude * u.deg, height=0 * u.m)
            frame = AltAz(obstime=times, location=location, pressure=0 * u.hPa)
            primary_altaz = _to_altaz(primary, times=times, location=location, frame=frame)
            secondary_altaz = _to_altaz(secondary, times=times, location=location, frame=frame)
            separation = primary_altaz.separation(secondary_altaz)
    return AstronomicalRelationshipResult(
        task=task, primary=primary, secondary=secondary,
        settings=AstronomicalRelationshipSettings(calculated_at=clock(), astropy_version=astropy.__version__),
        samples=[AstronomicalRelationshipSample(timestamp_local=point.local, timestamp_utc=point.utc,
            primary_altitude_deg=float(primary_altaz.alt[index].to_value(u.deg)), primary_azimuth_deg=float(primary_altaz.az[index].to_value(u.deg)),
            primary_is_above_horizon=bool(primary_altaz.alt[index] >= 0 * u.deg),
            secondary_altitude_deg=float(secondary_altaz.alt[index].to_value(u.deg)), secondary_azimuth_deg=float(secondary_altaz.az[index].to_value(u.deg)),
            secondary_is_above_horizon=bool(secondary_altaz.alt[index] >= 0 * u.deg),
            angular_separation_deg=float(separation[index].to_value(u.deg))) for index, point in enumerate(points)],
    )
```

Use CSV columns `timestamp_local`, `timestamp_utc`, `primary_altitude_deg`, `primary_azimuth_deg`, `primary_is_above_horizon`, `secondary_altitude_deg`, `secondary_azimuth_deg`, `secondary_is_above_horizon`, and `angular_separation_deg`. Leave the old CSV writer unchanged and make its input the legacy adapter result only. Include target references and resolved provenance in the v2 JSON output.

- [ ] **Step 4: Run relationship regression tests.**

Run: `.venv/bin/python -m pytest tests/test_solar_system_relationship.py tests/test_astronomical_relationship.py -q`

Expected: PASS. The generic test covers all nine ordered kinds; the legacy CSV header remains exactly `moon_*` / `jupiter_*`.

- [ ] **Step 5: Commit the shared relationship core.**

```bash
git add src/starskill/solar_system_relationship.py tests/test_solar_system_relationship.py tests/test_astronomical_relationship.py
git commit -m "feat: calculate arbitrary apparent target relationships"
```

### Task 4: Extend Ephemeris and Observation Runs Without Treating Dynamic Bodies as Catalog Coordinates

**Files:**
- Modify: `src/starskill/ephemeris_calculator.py:18-142`
- Modify: `src/starskill/pipeline.py:1-300`
- Modify: `src/starskill/schemas.py:88-204`
- Modify: `tests/test_ephemeris_calculator.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes `ResolvedAstronomicalTarget` and `TargetRef`.
- Produces `calculate_ephemeris(task: ObservationTask, target: ResolvedAstronomicalTarget, *, clock: Callable[[], datetime] = utc_now) -> EphemerisResult`.
- Produces `run_pipeline(task: ObservationTask, *, output_dir: Path, cache_dir: Path | None, backend: TargetBackend | None, criteria: VisibilityCriteria | None = None, clock: Callable[[], datetime] = utc_now) -> PipelineOutcome`, where `ObservationTask.target` accepts either legacy `str` or `TargetRef` and normalizes the legacy string to `SimbadTargetRef`.

- [ ] **Step 1: Write failing dynamic-target and direct-coordinate pipeline tests.**

```python
def test_ephemeris_uses_dynamic_mars_position_at_each_sample() -> None:
    result = calculate_ephemeris(observation_task_for({"kind": "solar_system", "body": "mars"}), resolved_mars())
    assert result.target.motion == "dynamic"
    assert result.samples[0].target_altitude_deg != pytest.approx(result.samples[-1].target_altitude_deg)

def test_pipeline_preserves_user_coordinate_provenance(tmp_path: Path) -> None:
    outcome = run_pipeline(observation_task_for({"kind": "coordinates", "label": "A", "ra_deg": 10, "dec_deg": 20}), output_dir=tmp_path / "run", cache_dir=tmp_path / "cache", backend=FailIfCalledBackend())
    result = json.loads((tmp_path / "run" / "result.json").read_text())
    assert outcome.status in {"success", "degraded"}
    assert result["target"]["source"]["provider"] == "user_coordinates"
```

- [ ] **Step 2: Run focused ephemeris/pipeline tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_ephemeris_calculator.py tests/test_pipeline.py -q`

Expected: FAIL because existing functions accept only `ResolvedTarget` and invoke no dynamic target path.

- [ ] **Step 3: Make fixed/dynamic computation explicit.**

```python
def _target_altaz(target: ResolvedAstronomicalTarget, times: Time, location: EarthLocation, frame: AltAz) -> SkyCoord:
    if target.motion == "dynamic":
        assert target.kind == "solar_system"
        return get_body(target.label.casefold(), times, location=location).transform_to(frame)
    assert target.ra_deg is not None and target.dec_deg is not None
    return SkyCoord(ra=target.ra_deg * u.deg, dec=target.dec_deg * u.deg, frame="icrs").transform_to(frame)
```

Change `ObservationTask.target` to `str | TargetRef` and add a `model_validator(mode="after")` that converts a non-blank legacy string into `SimbadTargetRef(kind="simbad", name=value)`. In the pipeline, resolve that `TargetRef` once, write its serialized provenance to `intermediate/target_resolved.json`, and pass it directly to ephemeris calculation. Retain legacy `ResolvedTarget` serialization fields for SIMBAD downstream readers by including the original `catalog_target` when available.

- [ ] **Step 4: Run targeted and existing observation tests.**

Run: `.venv/bin/python -m pytest tests/test_ephemeris_calculator.py tests/test_observation_planner.py tests/test_pipeline.py tests/test_examples.py -q`

Expected: PASS, including current M42 input as a normalized SIMBAD target.

- [ ] **Step 5: Commit the target-aware observation path.**

```bash
git add src/starskill/schemas.py src/starskill/ephemeris_calculator.py src/starskill/pipeline.py tests/test_ephemeris_calculator.py tests/test_pipeline.py
git commit -m "feat: use generalized targets in observation runs"
```

### Task 5: Expose v2 Through CLI, MCP, and Fixed Examples

**Files:**
- Modify: `src/starskill/cli.py:13-420`
- Modify: `src/starskill/mcp_server.py:58-270`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mcp_server.py`
- Create: `examples/relationships/mars_saturn.json`
- Create: `examples/relationships/mars_m31.json`
- Create: `examples/relationships/m31_coordinates.json`
- Create: `examples/relationships/coordinates_coordinates.json`

**Interfaces:**
- CLI: `starskill resolve-target INPUT --cache-dir PATH` accepts one `TargetRef`; `validate` accepts every currently implemented target-bearing task; `ephemeris` resolves `ObservationTask.target` itself unless the retained legacy `--target-file` is supplied; `run` and `plan` use the target-aware pipeline/result contracts.
- CLI: `starskill relationship INPUT --output CSV --metadata JSON --cache-dir PATH` accepts either `task_type: "astronomical_relationship"` or legacy `task_type: "solar_system_relationship"`.
- MCP: `StarSkillMcpService.calculate_astronomical_relationship(task: dict[str, Any]) -> dict[str, Any]` writes v2 `relationship.csv`/`relationship.json` under its service-owned run directory.
- MCP: `StarSkillMcpService.resolve_astronomy_target(target: dict[str, Any]) -> dict[str, Any]` resolves all three `TargetRef` kinds while the existing string-only `resolve_target` method remains the SIMBAD-compatible wrapper.
- MCP legacy wrapper retains `calculate_moon_jupiter_relationship(task)` and returns the same summary keys.

- [ ] **Step 1: Write failing CLI and MCP contract tests.**

```python
def test_relationship_cli_accepts_generic_coordinate_pair(tmp_path: Path) -> None:
    input_path = write_json(tmp_path / "task.json", generic_coordinate_task())
    exit_code = main(["relationship", str(input_path), "--output", str(tmp_path / "relationship.csv"), "--metadata", str(tmp_path / "relationship.json")])
    metadata = json.loads((tmp_path / "relationship.json").read_text())
    assert exit_code == 0
    assert metadata["settings"]["schema_version"] == "2.0"

def test_cli_resolve_target_and_ephemeris_accept_dynamic_and_direct_references(tmp_path: Path) -> None:
    reference_path = write_json(tmp_path / "mars.json", {"kind": "solar_system", "body": "mars"})
    task_path = write_json(tmp_path / "coordinate-observation.json", observation_task_for({"kind": "coordinates", "label": "A", "ra_deg": 10, "dec_deg": 20}))
    assert main(["resolve-target", str(reference_path), "--output", str(tmp_path / "mars-resolved.json")]) == 0
    assert main(["ephemeris", str(task_path), "--output", str(tmp_path / "ephemeris.csv"), "--metadata", str(tmp_path / "ephemeris.json")]) == 0
    assert json.loads((tmp_path / "mars-resolved.json").read_text())["motion"] == "dynamic"

def test_mcp_generic_relationship_publishes_only_run_resources(service: StarSkillMcpService) -> None:
    result = service.calculate_astronomical_relationship(generic_coordinate_task())
    assert result["ok"] is True
    assert result["resources"]["relationship"].startswith("starskill://runs/")
    assert "output_dir" not in result

def test_mcp_generic_target_resolution_does_not_query_simbad_for_coordinates(service: StarSkillMcpService) -> None:
    result = service.resolve_astronomy_target({"kind": "coordinates", "label": "A", "ra_deg": 10, "dec_deg": 20})
    assert result["ok"] is True
    assert result["target"]["source"]["provider"] == "user_coordinates"
```

- [ ] **Step 2: Run transport tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_cli.py tests/test_mcp_server.py -q`

Expected: FAIL because the CLI only validates `SolarSystemRelationshipTask`, no `resolve-target` command exists, and the generic MCP methods do not exist.

- [ ] **Step 3: Dispatch both input versions through the shared core.**

```python
relationship_task_adapter = TypeAdapter(AstronomicalRelationshipTask | SolarSystemRelationshipTask)
validated_task = relationship_task_adapter.validate_python(load_json_object(args.input_path))
if isinstance(validated_task, SolarSystemRelationshipTask):
    result = calculate_solar_system_relationship(validated_task)
    write_relationship_csv(result, args.output)
else:
    result = calculate_astronomical_relationship(validated_task, target_backend=SimbadBackend(), cache_dir=args.cache_dir)
    write_astronomical_relationship_csv(result, args.output)
write_relationship_json(result, args.metadata)
```

Add `resolve-target` with JSON `TargetRef` input, `--cache-dir` defaulting to `Path("cache/targets")`, and an optional JSON `--output`; retain the current `resolve TARGET` command for legacy SIMBAD-name callers. Make the `ephemeris` command's `--target-file` optional: when absent, validate `ObservationTask`, resolve `task.target`, and calculate directly; when present, use the existing legacy `ResolvedTarget` file parser. In `validate`, select the task adapter from the discriminator rather than forcing `ObservationTask`, preserving current validation output. In MCP, validate only `AstronomicalRelationshipTask` for the new relationship method, create a `relationship` run with `_new_run`, and catch `TargetResolutionError` plus `UnsupportedSolarSystemBodyError` through `_run_failure`. Implement `resolve_astronomy_target` by `TypeAdapter(TargetRef).validate_python` and `resolve_target_ref`; never allocate a run directory for this pure resolution operation. Keep all output paths server-owned and expose only the existing resource URI allowlist.

- [ ] **Step 4: Run CLI/MCP regression tests.**

Run: `.venv/bin/python -m pytest tests/test_cli.py tests/test_mcp_server.py tests/test_solar_system_relationship.py tests/test_astronomical_relationship.py -q`

Expected: PASS. Existing Moon-Jupiter CLI and MCP tests retain v1 JSON/CSV fields.

- [ ] **Step 5: Commit the transport contract.**

```bash
git add src/starskill/cli.py src/starskill/mcp_server.py tests/test_cli.py tests/test_mcp_server.py examples/relationships
git commit -m "feat: expose generalized relationship workflows"
```

### Task 6: Update Contracts, Acceptance Fixtures, and Documentation

**Files:**
- Modify: `README.md`
- Modify: `skills/run-starskill/SKILL.md`
- Modify: `skills/run-starskill/references/cli-contract.md`
- Modify: `scripts/evaluate_starskill.py`
- Modify: `tests/fixtures/evaluation/replay_fixtures.py`
- Modify: `tests/test_evaluation_cases.py`
- Modify: `tests/test_evaluation_replay.py`
- Modify: `docs/starskill-evaluation/acceptance-2026-07-23.md`

**Interfaces:**
- Adds recorded relationship cases `generic-mars-saturn`, `generic-mars-m31`, `generic-m31-coordinate`, and `generic-coordinate-coordinate` without changing the existing core/variant case IDs.
- Documents `relationship` v2, the semantic scope of apparent angular separation, target kinds, legacy compatibility, and structured unsupported-body errors.

- [ ] **Step 1: Write failing recorded-case assertions.**

```python
def test_generic_relationship_case_records_v2_artifacts() -> None:
    case = load_case("generic-mars-m31")
    execution = execute_case(case, runs_root=tmp_path / "runs")
    metadata = json.loads((execution.run_dir / "relationship.json").read_text())
    assert execution.return_code == 0
    assert metadata["settings"]["schema_version"] == "2.0"
    assert "primary_altitude_deg" in (execution.run_dir / "relationship.csv").read_text().splitlines()[0]
```

- [ ] **Step 2: Run recorded-case tests and verify they fail.**

Run: `.venv/bin/python -m pytest tests/test_evaluation_cases.py tests/test_evaluation_replay.py -q`

Expected: FAIL because the generic relationship fixtures and case definitions are absent.

- [ ] **Step 3: Add fixed, offline fixtures and concise user-facing contracts.**

Add four JSON fixtures with explicit timezone offsets and direct coordinates where required. Record `argv`, exit code, stdout/stderr, CSV, JSON, and SHA-256 through the existing script-owned runner. Update every user-facing document to say that solar-system targets are dynamic apparent positions, SIMBAD/direct coordinates are fixed ICRS positions, angular separation is not physical distance, and unsupported bodies fail explicitly rather than falling back to SIMBAD.

- [ ] **Step 4: Run the complete local regression and recorded acceptance.**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS.

Run: `.venv/bin/python scripts/evaluate_starskill.py acceptance --output-dir evaluation-runs/generalized-targets`

Expected: exit `0`; the manifest records the existing nine core/variant runs plus the four generic relationship cases with replayable hashes.

- [ ] **Step 5: Commit documentation and acceptance evidence.**

```bash
git add README.md skills/run-starskill scripts/evaluate_starskill.py tests/fixtures/evaluation tests/test_evaluation_cases.py tests/test_evaluation_replay.py docs/starskill-evaluation
git commit -m "docs: document generalized astronomy target contracts"
```
