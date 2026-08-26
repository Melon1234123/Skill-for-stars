# StarSkill CLI Contract

After following the Skill's preparation commands, run commands from the
repository root through that virtual environment:

```text
.venv/bin/python -m starskill <command> ...
```

## Uniform Response Envelope

Every command prints one JSON envelope: success and degraded envelopes go to
stdout, failure envelopes go to stderr. Each envelope carries these keys:

- `envelope_version`: currently `"1.0"`.
- `status`: `success`, `degraded`, or `failed`.
- `workflow`: the command name, or `sky-chart-catalog` for `--download-catalog`.
- `summary`: the principal numerical or state facts for the workflow.
- `artifacts`: one record per written file with `path`, `bytes`, and `sha256`.
- `sources`: provenance for external data used by the run, including
  availability and cache state.
- `human_review`: unresolved checks that stay with the human user.

Failure envelopes replace `summary`/`artifacts`/`sources`/`human_review` with
`error` plus `message` or `details`. Historical per-command keys such as
`resolved`, `valid`, `planned`, `calculated`, and `downloaded` remain present
for backward compatibility; new consumers should read the envelope keys.

## Local Visual Sky Chart

The Python-only local chart synopsis is exactly:

```text
.venv/bin/starskill sky-chart [-h] [--port PORT] [--open] [--download-catalog]
                               [--catalog-cache-dir CATALOG_CACHE_DIR]
```

`--port` defaults to `8000` and accepts only 1024--65535. The server hard-binds
to `127.0.0.1`; use `http://127.0.0.1:8000/` manually, or use `--open` to open
that loopback URL after health is available. `--catalog-cache-dir` defaults to
`cache/sky-chart`.

Catalog modes in render requests are `auto`, `bundled`, and `full`. `auto`
uses a validated local HYG v4.1 cache when present and otherwise returns the
bundled catalog with degraded status; `bundled` always stays packaged; `full`
requires that verified cache. Only the explicit human-run command below may
contact the one fixed HYG source:

```text
.venv/bin/starskill sky-chart --download-catalog [--catalog-cache-dir CACHE_DIR]
```

Do not perform that download for a user. The command exits `0` and prints its
catalog summary on successful verified publication, exits `1` with
`catalog_download_failed` for a download/cache failure, and exits `2` for CLI
syntax or port validation errors. Normal server startup exits `0` only when the
server returns cleanly; a startup failure exits `1` with
`web_server_start_failed`.

A render response exposes one opaque render ID and same-origin paired PNG/JSON
URLs. The JSON export carries `render.png_sha256` for the linked PNG bytes.
This workflow requires only the stated Python setup and no external browser
renderer. It is loopback-only with no CORS, uploads, or browser location
permission; it does not guarantee weather, visibility, or safety.

## Complete Observation Bundle

```text
.venv/bin/python -m starskill run <task.json> --output-dir <directory> [--cache-dir <directory>] [--min-target-altitude-deg 30] [--max-sun-altitude-deg -12]
```

Expected bundle: `input.json`, `run.json`, `result.json`, `report.md`, `review_checklist.md`, target and ephemeris intermediates, `visibility.csv`, and a visibility PNG. Read `run.json` as the authoritative status and artifact manifest.

This command may query SIMBAD unless a validated target cache entry is available.

## Generalized Relationship

```text
.venv/bin/python -m starskill relationship <task.json> --output <relationship.csv> --metadata <relationship.json> [--cache-dir <directory>]
```

Relationship v2 uses `task_type: astronomical_relationship` with `primary` and `secondary` typed target references. Supported kinds are `solar_system` (`body`), `simbad` (`name`), `coordinates` (`label`, `ra_deg`, `dec_deg`), and the opt-in `horizons` (`body`) described below. Solar-system targets are dynamic apparent positions calculated at every sample through Astropy's built-in ephemeris. SIMBAD and direct-coordinate targets are fixed ICRS positions; SIMBAD may query the service unless a validated cache entry exists, while direct coordinates remain offline.

The CSV contains generic primary/secondary AltAz fields, horizon flags, and `angular_separation_deg`; metadata uses `settings.schema_version: "2.0"` and records resolved target motion and provenance. Angular separation is an apparent angle on the observer's sky, not physical distance. Supported built-in bodies are Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, and Neptune. Any other `solar_system` body exits `2` with structured `error: "unsupported_solar_system_body"`; it never falls back to SIMBAD or JPL Horizons.

### Opt-in JPL Horizons minor bodies

Comets, asteroids, and other minor bodies are available only through the
explicit relationship target kind `horizons` (`body`). Choosing that kind is
the network opt-in: the command then queries the JPL Horizons API
(`https://ssd.jpl.nasa.gov/api/horizons.api`) once per target with a
small-body lookup, sampling apparent airless azimuth and elevation at every
relationship time step. `horizons` targets are valid only inside
`relationship` tasks; `validate` accepts them, while `resolve-target`,
`ephemeris`, and `run` do not.

Metadata records the resolved target with `source.provider: "jpl_horizons"`
and a `horizons_query` object holding the endpoint, the exact query
parameters, `accessed_at`, and `from_cache`. The query enforces a 30-second
timeout and a 2,000,000-byte response limit, and successful responses are
cached under `<cache-dir>/horizons` for 24 hours; a validated unexpired cache
entry keeps a repeated query offline and is reported with
`from_cache: true`.

Failures stay structured and never produce invented positions: an unknown
body exits `3` with `horizons_body_not_found`, an ambiguous designation exits
`2` with `horizons_ambiguous_body` (retry with a unique designation such as
`1 Ceres` or `1P/Halley`), and a service, network, or malformed-response
failure exits `4` with `horizons_service_error` or
`horizons_invalid_response`. The offline default above is unchanged: an
unsupported `solar_system` body is never retried through Horizons
automatically.

Legacy compatibility is retained: `task_type: solar_system_relationship` still requires `targets: ["moon", "jupiter"]` and writes the existing v1 Moon/Jupiter CSV and JSON fields.

## SDSS Image Cutout

```text
.venv/bin/python -m starskill fetch-image <request.json> --output-dir <directory> [--cache-dir <directory>]
```

The request accepts `target_name` (default `M51`), `ra_deg`, `dec_deg`,
`scale_arcsec_per_pixel`, `width`, and `height`, so any named target with known
ICRS coordinates can use the same bounded workflow; resolve coordinates first
with `resolve` or `resolve-target` when they are not known. Output filenames
derive from a lowercase slug of `target_name`: `data/<slug>_sdss.jpg`,
`figures/<slug>_display.png`, and `image_metadata.json`. The default M51
request keeps the historical `data/m51_sdss.jpg` and `figures/m51_display.png`
paths. The command may query the SDSS DR18 image cutout endpoint. It enforces a
request timeout, byte limit, MIME/JPEG validation, dimensions, and a validated
cache.

## External Evidence Commands

```text
.venv/bin/python -m starskill conditions <request.json> --output <conditions.json> [--cache-dir <directory>]
.venv/bin/python -m starskill recommend <task.json> --output-dir <directory> [--cache-dir <directory>] [--weather-cache-dir <directory>] [--light-pollution-snapshot <snapshot.json>] [threshold options]
.venv/bin/python -m starskill apod [--date YYYY-MM-DD] --output <nasa_feature.json> [--cache-dir <directory>]
.venv/bin/python -m starskill stellarium-sync <request.json> --output <stellarium_sync.json> [--base-url http://127.0.0.1:8090]
```

- `conditions` validates an observer/time-range request and fetches a bounded
  Open-Meteo hourly forecast with a 30-minute cache. It exits `0` when the
  evidence is fresh or cached and `5` (degraded) when the provider is
  unavailable; a degraded run still writes the structured unavailable record
  and never fabricates samples.
- `recommend` runs the complete observation pipeline into the output
  directory, then combines the geometric result with the Open-Meteo forecast
  and the local Black Marble light-pollution snapshot into
  `recommendation.json` plus `conditions.json`. Grades stay conservative rule
  outputs with reasons, provenance, and mandatory human-review items. Exit `0`
  requires a successful pipeline and available weather evidence; any degraded
  input exits `5`. Target-resolution failures keep exit codes `2`, `3`, and
  `4`.
- `apod` fetches NASA APOD metadata using the `STARSKILL_NASA_API_KEY`
  environment variable. The key never appears in outputs. A missing key or an
  unavailable service exits `5` with a structured unavailable record; an
  invalid `--date` exits `2`.
- `stellarium-sync` performs only the fixed status/location/time/focus
  operations against a local Stellarium RemoteControl endpoint (loopback port
  8090 unless `STARSKILL_STELLARIUM_BASE_URL` or `--base-url` overrides it,
  and non-loopback URLs are rejected). A connection failure writes the partial
  operation record and exits `10`.

Weather forecasts, light-pollution radiance, and APOD metadata are planning
evidence, never a go/no-go safety decision. Availability, cache state, and
issue codes are recorded in each envelope's `sources`.

## Partial Commands

```text
.venv/bin/python -m starskill validate <task.json>
.venv/bin/python -m starskill resolve <target> [--cache-dir <directory>] [--output <target.json>]
.venv/bin/python -m starskill resolve-target <target-ref.json> [--cache-dir <directory>] [--output <target.json>]
.venv/bin/python -m starskill ephemeris <task.json> [--target-file <target.json>] [--cache-dir <directory>] --output <ephemeris.csv> --metadata <ephemeris.json>
.venv/bin/python -m starskill plan <ephemeris.json> --output <visibility.csv> --metadata <result.json> --figure <plot.png> [threshold options]
```

## Exit Codes

| Code | Meaning |
| ---: | --- |
| 0 | Successful command |
| 2 | Input, target-name, or threshold validation failure |
| 3 | Target not found |
| 4 | SIMBAD or JPL Horizons service failure |
| 5 | Degraded result: a non-data artifact such as plotting failed, or external evidence (weather, light pollution, APOD) is unavailable |
| 6 | Public image not found or no data |
| 7 | Public data service failure |
| 8 | Public response exceeds the configured byte limit |
| 9 | Public response fails MIME, JPEG, dimension, or content validation |
| 10 | Local Stellarium RemoteControl is unreachable |

Malformed, unreadable, non-UTF-8, or non-object JSON input is a validation
failure: return exit code `2` and write `error=validation_error` JSON to stderr.
The command must not write workflow outputs before input parsing succeeds.

Errors are JSON on stderr. Never reinterpret a nonzero exit as success. A failed external query must not be replaced with invented data.

## Evaluation replay capture

When an external evaluation harness runs this CLI, it must preserve the actual evidence for replay:

- the exact command
- the assigned case manifest and input JSON
- the real exit code
- captured stdout
- captured stderr
- `response.md`
- `tool_calls.jsonl`
- every actual artifact written under the run directory

### `tool_calls.jsonl` execution-record schema

Each nonblank line is one strict JSON object with exactly these keys: `tool`, `command`, `case_id`, `case_kind`, `worker_role`, `task_path`, `workflow`, `run_dir`, `output_dir`, `return_code`, `stdout_file`, `stderr_file`, `response_file`, and `result`.

- The record must not include `arguments` or any other key. `tool` and `command` must both be `run-starskill`.
- `case_id`, `case_kind`, `worker_role`, `task_path`, and `workflow` must exactly match the assigned case manifest; `worker_role` must be the canonical role named by that manifest. `task_path` uses the manifest's absolute path representation.
- `run_dir` and `output_dir` are the same absolute path of the actual run directory. `stdout_file`, `stderr_file`, and `response_file` are absolute paths to captured files within that directory. `return_code` is the observed process exit code.
- `result` is a nested `result` object with exactly `return_code`, `output_dir`, `stdout_file`, `stderr_file`, and `response_file`, and each value must repeat its linked top-level value.

The harness does not create child Agents inside this repository and does not call an LLM API through this CLI contract. It must inspect actual files and exit codes rather than trusting natural-language summaries. Do not fabricate coordinates, image outputs, provenance, cache behavior, success states, or missing files. Preserve structured failures and degraded states exactly as produced.

### Script-owned engineering capture

`python scripts/evaluate_starskill.py execute --case <case.json> --run-dir <new-directory>`
records one real CLI process in `execution.json`. The record contains copied case/task inputs,
argv, exit code, stdout/stderr paths, and SHA-256 hashes for every captured artifact. Replay
accepts this evidence without an Agent response only when all record identities, paths, command
shape, copied inputs, exit code, and hashes validate. New records use schema v2 and preserve only
safe source-environment evidence: `source_path` plus an `environment` object whose sole key is
`PYTHONPATH`. Replay requires both `source_path` and the first `PYTHONPATH` component to be
absolute paths that resolve to the trusted repository `src` directory. Legacy schema v1 records
remain replayable using their original field set; replay does not fabricate source-environment
evidence that v1 never captured.
`acceptance --output-dir <new-root>` derives
`runs`, `scores`, and `reports` below that root and writes `reports/acceptance.json`; the legacy
explicit `--run-root`, `--score-root`, and `--output-dir` layout remains accepted. Acceptance
repeats every core case three times and every variant once; the current matrix has 19 runs. It is
an engineering gate, not external Worker or reviewer evidence.
Its score bundles use `evidence_mode: script_owned_engineering` and include only machine-check
dimensions. Reviewer, escalation, and bonus evidence are invalid for this mode.

## Review Checklist

- Confirm local date, timezone, longitude, and latitude.
- Treat candidate windows as geometric calculations, not weather forecasts.
- Review clouds, horizon, equipment, supervision, and observing safety.
- Preserve database attribution, access metadata, and processing steps.
- Explain angular separation as an apparent sky relationship, not physical distance.
