# Final Review Fix v5 Brief

Read first: `docs/starskill-evaluation/review-history/2026-07-21-final-review-v4-recheck.md` and current source/docs/tests.

The project is not a Git worktree. Do not initialize Git or create commits.

## Required fixes

1. **Bind aggregate run identity to the physical run directory.**

   During score-bundle validation, resolve `bundle.run_dir` and require `bundle.run_id` to equal the actual run directory name used when replay writes the bundle. Reject any bundle whose run ID is changed independently of its resolved run directory. Also reject duplicate physical `(case_id, resolved_run_dir)` entries in aggregation, so copying one run and synchronously editing score/machine IDs cannot satisfy three core repeats. Preserve allowed reuse of a run ID across different physical case run directories. Add a regression that copies one valid bundle three ways, mutates both score/machine IDs, and expects aggregation failure/incomplete independent runs.

2. **Catch oversized top-level bonus declarations.**

   `_read_bonus()` must convert any `ValueError` from `json.loads`, including CPython's oversized integer digit-limit error, into the documented structured `ReportError`/JSON error. Add a regression with a 10,000-digit `awarded` value in the top-level `--bonus-file`, and assert no raw exception escapes.

3. **Document and align the execution-record protocol.**

   Treat the strict `tool_calls.jsonl` schema as public evaluation protocol. Update `evaluation/prompts/workers/teacher.md`, `outreach.md`, `research.md`, `skills/run-starskill/references/cli-contract.md`, and any relevant evaluation README so they specify the exact accepted JSON object keys, absolute path representation, nested `result` object, worker role/case/task/workflow fields, and the linkage rules. Resolve the current conflict where prompts require command arguments/result summary but validator rejects an `arguments` field: either add a strictly validated `arguments` field to the schema and protocol or revise prompts to the exact accepted schema. Add documentation tests that assert the published schema names/fields match the validator. Do not weaken strict validation or change StarSkill command syntax.

## Verification

Write `docs/starskill-evaluation/review-history/2026-07-21-final-review-fix-v5-report.md` with changed files, decisions, exact commands/results, and concerns. Run:

```powershell
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v5-focused
.venv\\Scripts\\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v5-full
.venv\\Scripts\\python.exe -m compileall src tests scripts
.venv\\Scripts\\python.exe -m pip check
.venv\\Scripts\\python.exe scripts/evaluate_starskill.py --help
```

The external 9+ Agent evaluation remains unrun and must not be claimed.
