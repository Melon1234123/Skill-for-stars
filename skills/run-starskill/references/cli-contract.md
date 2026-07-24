# StarSkill CLI Contract

After following the Skill's preparation commands, run commands from the
repository root through that virtual environment:

```text
.venv/bin/python -m starskill <command> ...
```

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

## Moon-Jupiter Relationship

```text
.venv/bin/python -m starskill relationship <task.json> --output <relationship.csv> --metadata <relationship.json>
```

The supported task requires `targets` to be Moon and Jupiter. It uses Astropy's built-in solar-system ephemeris and does not require a live network query.

## SDSS M51 Image

```text
.venv/bin/python -m starskill fetch-image <request.json> --output-dir <directory> [--cache-dir <directory>]
```

Expected files: `data/m51_sdss.jpg`, `figures/m51_display.png`, and `image_metadata.json`. The command may query the SDSS DR18 image cutout endpoint. It enforces a request timeout, byte limit, MIME/JPEG validation, dimensions, and a validated cache.

## Partial Commands

```text
.venv/bin/python -m starskill validate <task.json>
.venv/bin/python -m starskill resolve <target> [--cache-dir <directory>] [--output <target.json>]
.venv/bin/python -m starskill ephemeris <task.json> --target-file <target.json> --output <ephemeris.csv> --metadata <ephemeris.json>
.venv/bin/python -m starskill plan <ephemeris.json> --output <visibility.csv> --metadata <result.json> --figure <plot.png> [threshold options]
```

## Exit Codes

| Code | Meaning |
| ---: | --- |
| 0 | Successful command |
| 2 | Input, target-name, or threshold validation failure |
| 3 | Target not found |
| 4 | SIMBAD service failure |
| 5 | Complete run degraded because a non-data artifact such as plotting failed |
| 6 | Public image not found or no data |
| 7 | Public data service failure |
| 8 | Public response exceeds the configured byte limit |
| 9 | Public response fails MIME, JPEG, dimension, or content validation |

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
shape, copied inputs, exit code, and hashes validate. `acceptance` repeats every core case three
times and every variant once; it is an engineering gate, not external Worker or reviewer evidence.
Its score bundles use `evidence_mode: script_owned_engineering` and include only machine-check
dimensions. Reviewer, escalation, and bonus evidence are invalid for this mode.

## Review Checklist

- Confirm local date, timezone, longitude, and latitude.
- Treat candidate windows as geometric calculations, not weather forecasts.
- Review clouds, horizon, equipment, supervision, and observing safety.
- Preserve database attribution, access metadata, and processing steps.
- Explain angular separation as an apparent sky relationship, not physical distance.
