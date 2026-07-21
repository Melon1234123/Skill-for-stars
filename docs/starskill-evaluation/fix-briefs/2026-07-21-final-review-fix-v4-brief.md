# Final Review Fix v4 Brief

Read first: `docs/starskill-evaluation/review-history/2026-07-21-final-review-v3-recheck.md` and the current evaluation implementation.

The project is not a Git worktree. Do not initialize Git or create commits.

## Required fixes

1. **Canonical worker-role enforcement during aggregate revalidation**

   In `src/starskill/evaluation/reporting.py`, when validating an existing score bundle against canonical case evidence, require the captured Worker role from the strict `tool_calls.jsonl` record and the bundle's `worker_role` to equal `case.role`. Do not rely only on the mutable bundle role or merely check that it is one of the valid role strings. Tampering both `score.json.worker_role` and `tool_calls.jsonl.worker_role` to a different valid role must fail closed. Preserve replay-time role checks and add a regression test that targets aggregate-time revalidation.

2. **Structured error for oversized JSON bonus records**

   Any malformed/oversized bonus JSON, including CPython's integer-string digit-limit `ValueError` from `json.loads`, must return the documented structured CLI error rather than a raw exception. Catch the relevant `ValueError` at the bonus parse/validation boundary or at the top-level CLI without swallowing unrelated errors. Add a regression test with a valid-shaped bonus evidence record containing an oversized integer and assert a JSON error response with a nonzero exit code.

## Verification

Write `docs/starskill-evaluation/review-history/2026-07-21-final-review-fix-v4-report.md` with changed files, exact commands/results, and concerns. Run:

```powershell
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v4-focused
.venv\\Scripts\\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v4-full
.venv\\Scripts\\python.exe -m compileall src tests scripts
.venv\\Scripts\\python.exe -m pip check
.venv\\Scripts\\python.exe scripts/evaluate_starskill.py --help
```

The external 9+ Agent evaluation remains unrun and must not be claimed.
