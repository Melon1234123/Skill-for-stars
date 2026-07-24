# Recorded Runtime Acceptance: 2026-07-23

## Baseline Result

The 2026-07-23 script-owned baseline passed all three core cases and six original variants. The generalized-target extension retains those case IDs and the established three executions per core case.

## Generalized Contract

Relationship v2 adds four deterministic, offline variants: `generic-mars-saturn`, `generic-mars-m31`, `generic-m31-coordinate`, and `generic-coordinate-coordinate`. Their timestamps carry explicit UTC offsets, and typed SIMBAD M31 is resolved from a deterministic cache so the recorded gate does not depend on live SIMBAD availability.

Solar-system targets are dynamic apparent positions evaluated at every timestamp. SIMBAD and direct-coordinate targets are fixed ICRS positions. `angular_separation_deg` is an apparent sky angle, not physical distance. An unsupported solar-system name produces the structured `unsupported_solar_system_body` error and is not retried through SIMBAD. The legacy Moon-Jupiter task and v1 artifacts remain part of the matrix.

## Recorded Command

```bash
.venv/bin/python scripts/evaluate_starskill.py acceptance \
  --output-dir evaluation-runs/generalized-targets
```

This 19-run gate executes each of the three core cases three times and each of the ten variants once. Every run has a runner-owned `execution.json` containing the exact argv, observed exit code, stdout/stderr paths, copied inputs, and SHA-256 hashes. `reports/acceptance.json` indexes those records and hashes. This is script-owned engineering evidence, not external Worker, Reviewer, publication, or global Skill synchronization evidence.

## Verified Generalized Result

The local generalized acceptance rerun on 2026-07-24 exited `0`. All 19 subprocesses returned `0`, all 19 replays returned `0`, the overall/core/variant hard-gate pass rates were `1.0`, the core average base score was `89.0`, and there were no critical failures. M42 and M51 used evaluator-owned deterministic target/image cache fixtures; production target resolution and image retrieval behavior was not changed. Generated evidence remains ignored under `evaluation-runs/generalized-targets/`.

This result is local repository acceptance only. No live publication, fresh-clone verification, or synchronization to the globally installed `run-starskill` Skill was performed in this task.
