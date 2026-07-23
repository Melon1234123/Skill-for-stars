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

The repository does not create child Agents and does not call an LLM API through this CLI contract. `scripts/evaluate_starskill.py execute` invokes this CLI using a script-owned `subprocess.run(..., shell=False)` process and writes `execution.json`; a role prompt or Worker must not write `tool_calls.jsonl` or execution evidence.

The script captures the assigned manifest and task copies, exact command, real exit code, stdout, stderr, and every artifact that existed when the process completed. `replay` validates the record and files rather than trusting natural-language summaries.

### `execution.json` execution-record schema

The strict script-generated object has exactly these fields: `recorder`, `schema_version`, `case_id`, `case_kind`, `role`, `workflow`, `task_path`, `run_dir`, `working_directory`, `command_argv`, `return_code`, `started_at`, `completed_at`, `stdout_file`, `stderr_file`, `exit_code_file`, and `artifact_sha256`.

- `recorder` is `starskill.evaluation.runner`, and `schema_version` is `1`.
- The case identity, role, workflow, copied `task_path`, run directory, and working directory must match the manifest and script contract.
- `command_argv` is the actual absolute interpreter command; replay accepts only the command shape generated for that workflow.
- `return_code` must equal the numeric value in `exit_code_file`; `stdout_file` and `stderr_file` must remain in the run directory.
- `artifact_sha256` binds every pre-record file to its SHA-256 digest. Codex-native tool history, when available, is external platform evidence and is not substituted for this script record.

Do not fabricate coordinates, image outputs, provenance, cache behavior, success states, or missing files. Preserve structured failures and degraded states exactly as produced.

## Review Checklist

- Confirm local date, timezone, longitude, and latitude.
- Treat candidate windows as geometric calculations, not weather forecasts.
- Review clouds, horizon, equipment, supervision, and observing safety.
- Preserve database attribution, access metadata, and processing steps.
- Explain angular separation as an apparent sky relationship, not physical distance.
