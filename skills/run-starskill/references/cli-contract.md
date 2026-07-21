# StarSkill CLI Contract

Run commands from the repository root with the active project environment:

```text
python -m starskill <command> ...
```

## Complete Observation Bundle

```text
python -m starskill run <task.json> --output-dir <directory> [--cache-dir <directory>] [--min-target-altitude-deg 30] [--max-sun-altitude-deg -12]
```

Expected bundle: `input.json`, `run.json`, `result.json`, `report.md`, `review_checklist.md`, target and ephemeris intermediates, `visibility.csv`, and a visibility PNG. Read `run.json` as the authoritative status and artifact manifest.

This command may query SIMBAD unless a validated target cache entry is available.

## Moon-Jupiter Relationship

```text
python -m starskill relationship <task.json> --output <relationship.csv> --metadata <relationship.json>
```

The supported task requires `targets` to be Moon and Jupiter. It uses Astropy's built-in solar-system ephemeris and does not require a live network query.

## SDSS M51 Image

```text
python -m starskill fetch-image <request.json> --output-dir <directory> [--cache-dir <directory>]
```

Expected files: `data/m51_sdss.jpg`, `figures/m51_display.png`, and `image_metadata.json`. The command may query the SDSS DR18 image cutout endpoint. It enforces a request timeout, byte limit, MIME/JPEG validation, dimensions, and a validated cache.

## Partial Commands

```text
python -m starskill validate <task.json>
python -m starskill resolve <target> [--cache-dir <directory>] [--output <target.json>]
python -m starskill ephemeris <task.json> --target-file <target.json> --output <ephemeris.csv> --metadata <ephemeris.json>
python -m starskill plan <ephemeris.json> --output <visibility.csv> --metadata <result.json> --figure <plot.png> [threshold options]
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

## Review Checklist

- Confirm local date, timezone, longitude, and latitude.
- Treat candidate windows as geometric calculations, not weather forecasts.
- Review clouds, horizon, equipment, supervision, and observing safety.
- Preserve database attribution, access metadata, and processing steps.
- Explain angular separation as an apparent sky relationship, not physical distance.
