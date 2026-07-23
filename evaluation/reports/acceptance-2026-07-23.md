# Recorded Runtime Acceptance: 2026-07-23

## Result

- Decision: `passed`
- Required runs: `9` (three core cases and six variants, one fresh run each)
- Hard-gate pass rate: `1.0`
- Core hard-gate pass rate: `1.0`
- Variant hard-gate pass rate: `1.0`
- Core average base score: `89.0` (threshold `80.0`)
- Critical failures: `0`
- Human reviews and bonus claims: not used for this machine acceptance run

## Recorded Command

```bash
./.venv/bin/python scripts/evaluate_starskill.py acceptance \
  --run-root evaluation-runs/acceptance-2026-07-23-final/agents \
  --score-root evaluation-runs/acceptance-2026-07-23-final/scores \
  --output-dir evaluation-runs/acceptance-2026-07-23-final/aggregate \
  --python-executable .venv/bin/python \
  --target-cache-dir cache/targets \
  --image-cache-dir cache/sdss
```

## Evidence

Each of the following script-generated runs returned `0`, passed replay, and has an `execution.json` record with the invoked argv, captured stdout/stderr, exit-code file, copied input, and pre-record artifact hashes:

- `core-m42-beijing`
- `core-m51-sdss`
- `core-moon-jupiter-shanghai`
- `variant-m42-location-time`
- `variant-m42-no-window`
- `variant-m51-cache-reuse`
- `variant-m51-request-parameters`
- `variant-moon-jupiter-interval`
- `variant-moon-jupiter-location-time`

All three M51 runs used validated local cache data, including the previously cached `768x640` request-parameter variant. The no-window M42 variant returned a successful run with an empty `windows` list, matching the product contract.

The complete, ignored runtime evidence is at `evaluation-runs/acceptance-2026-07-23-final/`. Its generated aggregate JSON reported one run per case and a descriptive standard deviation of `0.0`; this is not a claim of multi-run statistical stability.
