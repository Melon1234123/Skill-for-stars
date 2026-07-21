# Final Review Fix v4 Report

## Changed Files

- `src/starskill/evaluation/reporting.py`
  - Aggregate revalidation now requires both `ScoreBundle.worker_role` and each strict `tool_calls.jsonl` worker role to match the canonical case role.
  - Bonus JSON parsing converts `ValueError`, including CPython's oversized-integer digit-limit error, into `ReportError("invalid_bonus_evidence", ...)`.
- `tests/test_evaluation_final_review.py`
  - Added an aggregate-time regression that changes both `score.json.worker_role` and `tool_calls.jsonl.worker_role` to the other valid role and expects rejection.
  - Added a CLI regression with a valid-shaped bonus measurement containing a 10,000-digit integer and asserts a nonzero structured `invalid_bonus_evidence` response.

## Test-First Evidence

Command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_final_review.py -q -k "oversized_bonus_measurement_json or tampered_canonical_worker_roles" --basetemp .pytest-tmp/final-review-v4-red
```

Result: expected red state, exit code `1`. The oversized record escaped as raw `ValueError`; synchronized role tampering reached the incomplete matrix check rather than being rejected during evidence revalidation.

Command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_final_review.py -q -k "oversized_bonus_measurement_json or tampered_canonical_worker_roles" --basetemp .pytest-tmp/final-review-v4-green
```

Result: exit code `0`; both regressions passed.

## Required Verification

Command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v4-focused
```

Result: exit code `0`; focused suite completed without failures.

Command:

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v4-full
```

Result: exit code `0`; full suite completed without failures.

Command:

```powershell
.venv\Scripts\python.exe -m compileall src tests scripts
```

Result: exit code `0`; compilation completed successfully.

Command:

```powershell
.venv\Scripts\python.exe -m pip check
```

Result: exit code `0`; `No broken requirements found.`

Command:

```powershell
.venv\Scripts\python.exe scripts/evaluate_starskill.py --help
```

Result: exit code `0`; replay and aggregate command help rendered.

## Concerns

- The external 9+ Agent evaluation remains unrun and is not claimed by this report.
- The workspace is intentionally not a Git worktree. No Git repository was initialized and no commit was created.
