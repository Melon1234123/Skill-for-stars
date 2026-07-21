# Final Review Fix v5 Report

## Status

Implemented all three fixes from `docs/starskill-evaluation/fix-briefs/2026-07-21-final-review-fix-v5-brief.md`. The project was not initialized as a Git repository and no commit was created.

## Decisions

1. Aggregate identity now binds `ScoreBundle.run_id` to `Path(bundle.run_dir).resolve().name`. This check occurs while validating bundle references, before a bundle can contribute to matrix counts.
2. Aggregation deduplicates `(case_id, resolved_run_dir)` rather than the mutable `(case_id, run_id)` pair. Consequently, the same run ID remains permitted for distinct physical run directories while one physical directory cannot count twice for a case.
3. `_read_bonus()` now catches `ValueError` from `json.loads()`, including CPython's oversized-integer digit-limit exception, and returns the existing structured `invalid_json` `ReportError` path.
4. The public execution-record protocol documents the validator's current strict schema rather than adding an `arguments` field. A `tool_calls.jsonl` record has exactly 14 top-level keys, omits `arguments`, uses absolute captured-path values, and has a linked five-key nested `result` object.

## Changed Files

- `src/starskill/evaluation/reporting.py`
- `scripts/evaluate_starskill.py`
- `tests/test_evaluation_final_review.py`
- `tests/test_evaluation_cli.py`
- `tests/test_evaluation_cases.py`
- `tests/test_evaluation_reporting.py`
- `evaluation/prompts/workers/teacher.md`
- `evaluation/prompts/workers/outreach.md`
- `evaluation/prompts/workers/research.md`
- `skills/run-starskill/references/cli-contract.md`
- `evaluation/README.md`

## Focused Regressions

- Copied one valid core bundle three times, changed each copied `score.json` and `machine_checks.json` run ID, and confirmed collection rejects the changed ID because it does not match the shared physical run directory.
- Confirmed a 10,000-digit top-level bonus `awarded` value returns structured JSON with `error: invalid_json` instead of propagating a raw `ValueError`.
- Confirmed every published worker/CLI/README protocol document contains the exact validator field names and required linkage language.
- Confirmed matching run IDs remain valid when the resolved run directories are distinct.

## Verification

All commands below were run from `F:\Skill-for-stars` and exited with status 0 unless noted.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_final_review.py::test_aggregate_rejects_synchronized_run_ids_for_copied_physical_run tests/test_evaluation_cli.py::test_replay_returns_structured_error_for_oversized_top_level_bonus_json tests/test_evaluation_cases.py::test_execution_record_protocol_docs_match_validator_schema -q --basetemp .pytest-tmp/final-review-v5-red
```

Result: expected pre-fix RED run; 3 failures covering physical-run identity, top-level oversized bonus JSON, and protocol documentation.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_final_review.py::test_aggregate_rejects_synchronized_run_ids_for_copied_physical_run tests/test_evaluation_cli.py::test_replay_returns_structured_error_for_oversized_top_level_bonus_json tests/test_evaluation_cases.py::test_execution_record_protocol_docs_match_validator_schema -q --basetemp .pytest-tmp/final-review-v5-green
```

Result: `3 passed`.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v5-closeout
```

Result: bounded closeout regression suite passed.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v5-focused
```

Result: passed.

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v5-full
```

Result: passed.

```powershell
.venv\Scripts\python.exe -m compileall src tests scripts
```

Result: passed; compiled changed test modules without errors.

```powershell
.venv\Scripts\python.exe -m pip check
```

Result: `No broken requirements found.`

```powershell
.venv\Scripts\python.exe scripts/evaluate_starskill.py --help
```

Result: passed; help lists the `replay` and `aggregate` commands.

## Concerns

The external 9+ Agent evaluation was not run and is not claimed by this report.
