# Task 2 Report: Resolve Dynamic and Fixed Targets Through One Core Service

## Status

Implemented the typed core target resolver and migrated sky-chart coordinate and
supported solar-system target handling to it. No relationship calculation,
observation pipeline, CLI, MCP, image, or plan-document behavior was changed.

## Files Changed

- `src/starskill/target_references.py`
  - Added the immutable built-in ephemeris whitelist, explicit unsupported-body
    error, and `resolve_target_ref` for dynamic solar-system, fixed coordinate,
    and cached SIMBAD targets.
- `src/starskill/sky_chart_targets.py`
  - Removed the duplicate solar-system mapping and direct user-coordinate
    construction. Both paths now create a `TargetRef` and call an injectable
    core resolver while retaining `ResolvedSkyTarget` output.
- `tests/test_target_references.py`
  - Added fake-SIMBAD coverage for motion/provenance and explicit Pluto failure.
- `tests/test_sky_chart_targets.py`
  - Added coverage that coordinate input reaches the injected typed resolver.

## RED Evidence

Command:

```bash
.venv/bin/python -m pytest tests/test_target_references.py -q
```

Result: failed during collection as intended with
`ModuleNotFoundError: No module named 'starskill.target_references'` before the
core resolver existed.

## GREEN Evidence

Command:

```bash
.venv/bin/python -m pytest tests/test_target_resolver.py tests/test_target_references.py tests/test_sky_chart_targets.py -q
```

Result: `40 passed`.

The full suite was also run before commit:

```bash
.venv/bin/python -m pytest -q
```

Result: passed. The only output beyond progress was an existing third-party
FastAPI/Starlette deprecation warning about `httpx` and `TestClient`.

## Behavioral Boundaries

- Only `sun`, `moon`, and `mercury` through `neptune` resolve as dynamic
  Astropy built-in ephemeris targets.
- `pluto` and every other unsupported `SolarSystemTargetRef` raise
  `UnsupportedSolarSystemBodyError` with code
  `unsupported_solar_system_body`; no SIMBAD fallback occurs.
- Direct coordinates return fixed ICRS provenance from `user_coordinates` and
  do not invoke the SIMBAD backend.
- SIMBAD resolution continues through the existing cache-aware resolver and
  carries its catalog record forward.

## Commit

`5a885ec feat: resolve generalized astronomy targets`

## Concerns

None for this task. The full test suite reports the unrelated third-party
deprecation warning noted above.

## Follow-up Review Fix: Sky Chart Pluto Boundary

### RED Evidence

Command:

```bash
.venv/bin/python -m pytest tests/test_sky_chart_targets.py -q
```

Result: `1 failed, 9 passed`. The new Pluto regression test failed because
`SkyChartTargetResolver.resolve()` called the injected legacy external resolver
with `"Pluto"`, raising its deliberate assertion.

### GREEN Evidence

Command:

```bash
.venv/bin/python -m pytest tests/test_target_references.py tests/test_sky_chart_targets.py -q
```

Result: passed (`26 passed`). The chart now recognizes only the static built-in
solar-system names plus `pluto`, delegates Pluto to `resolve_target_ref`, and
preserves the core resolver's explicit `unsupported_solar_system_body` error
without touching the external resolver.

## Follow-up Review Fix: Generalized Unsupported Solar-System Names

### RED Evidence

Command:

```bash
.venv/bin/python -m pytest tests/test_sky_chart_targets.py -q
```

Result: `1 failed, 10 passed`. The new Ceres parameter of the unsupported-body
regression failed as intended because `SkyChartTargetResolver.resolve()` passed
`"Ceres"` to the injected legacy external resolver instead of constructing a
`SolarSystemTargetRef`.

### GREEN Evidence

Command:

```bash
.venv/bin/python -m pytest tests/test_target_references.py tests/test_sky_chart_targets.py -q
```

Result: `27 passed`.

The deterministic chart alias registry now includes `pluto`, `ceres`, `haumea`,
`makemake`, `eris`, `pallas`, `juno`, and `vesta`. Each routes through the core
resolver, which retains `unsupported_solar_system_body` and never invokes the
injected external/SIMBAD resolver. Existing unrecognized names continue to use
the external resolver.
