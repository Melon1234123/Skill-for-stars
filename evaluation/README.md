# StarSkill recorded runtime acceptance

This repository accepts a release through a small, reproducible runtime matrix. The evaluation script runs the real StarSkill CLI, records the resulting process evidence, replays deterministic checks, and aggregates the score reports. It does not create child Agents and does not call an LLM API.

The release matrix contains one fresh recorded run for each of the three core cases and six canonical variants. Failure and open cases are retained as deterministic test coverage, rather than being release-matrix runs. A human review is optional supplementary evidence for presentation or role usability; it is not required for machine runtime acceptance.

The aggregate requires a 1.0 core hard-gate rate, a 1.0 variant hard-gate rate, and a core average base score at least 80/100. A one-run standard deviation is reported descriptively as `0.0`; it is not an acceptance gate.

## Acceptance sequence

1. Load every canonical core and variant manifest.
2. Create one fresh run directory per case.
3. Execute the real CLI through `evaluate_starskill.py acceptance` or `execute`.
4. Let the script write `execution.json`, captured stdout/stderr, exit code, input copies, and artifact hashes.
5. Replay deterministic artifact, value, provenance, image, and exit-code checks.
6. Aggregate the nine score reports and require every core and variant hard gate to pass.

Run a full acceptance matrix from the repository root:

```bash
./.venv/bin/python scripts/evaluate_starskill.py acceptance \
  --run-root evaluation-runs/2026-07-23/agents \
  --score-root evaluation-runs/2026-07-23/scores \
  --output-dir evaluation-runs/2026-07-23/aggregate \
  --python-executable .venv/bin/python \
  --target-cache-dir cache/targets \
  --image-cache-dir cache/sdss
```

All three output directories must be new or empty. The command exits nonzero when a required case or aggregate threshold fails.

For one case, use the two stages separately:

```bash
./.venv/bin/python scripts/evaluate_starskill.py execute \
  --case evaluation/cases/core/core-m42-beijing.json \
  --run-dir evaluation-runs/manual/core-m42-beijing

./.venv/bin/python scripts/evaluate_starskill.py replay \
  --case evaluation/cases/core/core-m42-beijing.json \
  --run-dir evaluation-runs/manual/core-m42-beijing \
  --output-dir evaluation-runs/manual-scores/core-m42-beijing
```

`replay` reads its exit code, stdout, and stderr only from `execution.json`; it does not accept a Worker-provided result as process evidence.

## Script-recorded evidence

`execute` runs `python -m starskill ...` with `subprocess.run(..., shell=False)` and writes the following files into the new run directory:

- `case.json` and `task.json`: immutable copies used by the executed process.
- `stdout.txt`, `stderr.txt`, and `exit_code.txt`: observed process outputs.
- `execution.json`: the script-generated execution record.
- Product artifacts at their actual CLI output paths.

The strict `execution.json` schema contains `recorder`, `schema_version`, `case_id`, `case_kind`, `role`, `workflow`, `task_path`, `run_dir`, `working_directory`, `command_argv`, `return_code`, `started_at`, `completed_at`, `stdout_file`, `stderr_file`, `exit_code_file`, and `artifact_sha256`.

The replay validator checks the recorded case identity, copied task path, exact command shape, captured paths, exit-code file, and hashes of every file that existed when execution completed. A later optional review or bonus sidecar may be added without changing the recorded process artifact set.

This script can prove its own subprocess execution. It cannot extract Codex Desktop's native tool-event trace. When such a platform trace is available, attach it as external provenance; `execution.json` remains the repository's authoritative runtime evidence.

## Optional Review

An optional human reviewer may contribute the presentation and usability portions of a score report after machine acceptance. The retained rotation is fixed:

- teacher reviewer reviews outreach Worker output
- outreach reviewer reviews research Worker output
- research reviewer reviews teacher Worker output

Do not use a review to overwrite a machine result. A reviewer critical issue still makes that reviewed score fail.

## Exit Codes And Boundaries

| Code | Meaning |
| ---: | --- |
| 0 | successful command |
| 2 | input validation failure |
| 4 | SIMBAD service failure |
| 5 | complete run degraded because optional visualization failed |
| 7 | public data service failure |
| 9 | public response validation failure |

Candidate observation windows are geometric calculations, not a weather, site, equipment, supervision, or safety guarantee. Moon-Jupiter angular separation is an apparent sky relationship, not a three-dimensional physical distance. SDSS attribution and processing metadata must remain in the resulting artifacts.

## Live Smoke

A live smoke run may report current external-service health, but it does not replace cache-backed acceptance evidence or loosen the nine-case runtime matrix.
