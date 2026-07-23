# Recorded Runtime Acceptance

Date: 2026-07-23

This design replaces the earlier external-Agent, three-repeat acceptance proposal. It keeps the astronomy workflows and deterministic artifact checks, while making release acceptance small enough to run, inspect, and reproduce from the repository.

## Decision

- Execute one fresh recorded run for each of three core cases and six input variants.
- Use script-owned subprocess evidence as the runtime source of truth.
- Keep failure and open cases in deterministic unit/replay coverage, outside the release matrix.
- Permit optional human review for presentation and usability evidence, but do not make it a prerequisite for a machine runtime pass.
- Report one-run standard deviation descriptively only; do not claim statistical repeatability from a single run.

## Evidence Boundary

`scripts/evaluate_starskill.py execute` copies the manifest and input into a new run directory, invokes the exact `python -m starskill` argv with `shell=False`, and writes `execution.json`, stdout, stderr, exit code, and SHA-256 hashes.

`replay` derives its command, return code, stdout, and stderr from that record. It rejects a wrong case identity, task path, command shape, captured path, exit-code mismatch, or changed recorded artifact. The role prompt must not author `tool_calls.jsonl` or `execution.json`.

The record proves repository-script subprocess execution. It cannot recover Codex Desktop's native tool-event trace; attach a platform trace separately when it is available.

## Release Command

```bash
./.venv/bin/python scripts/evaluate_starskill.py acceptance \
  --run-root evaluation-runs/<date>/agents \
  --score-root evaluation-runs/<date>/scores \
  --output-dir evaluation-runs/<date>/aggregate \
  --python-executable .venv/bin/python \
  --target-cache-dir cache/targets \
  --image-cache-dir cache/sdss
```

Acceptance requires every core and variant hard gate to pass and the core average base score to be at least 80. Live external-service smoke results are operational information, not a replacement for recorded acceptance evidence.
