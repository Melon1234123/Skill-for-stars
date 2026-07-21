# Final Review Fix v3 Report

## Scope

Implemented both required final-review v3 fixes in the current workspace. The project was not initialized as Git and no commit was created.

## Changed files

- `src/starskill/evaluation/reporting.py`
  - Bonus evidence now fails closed on missing, unreadable, empty, escaping, unlinked, prose-only, malformed, non-finite, or non-passing records.
  - Each nonzero bonus category requires its baseline, comparison, and verification paths to be included in `evidence_paths`.
  - Baseline and comparison must be separate, strict `starskill_bonus_measurement` JSON records with the same non-empty metric and unit and different finite numeric values.
  - Verification must be a strict `starskill_bonus_verification` JSON record with a non-empty command, `exit_code: 0`, and `passed: true`.
- `evaluation/README.md`
  - Documented the deterministic bonus evidence protocol and its repository/run-directory boundaries.
- `evaluation/cases/variants/variant-moon-jupiter-location-time.json`
  - Replaced the Shanghai values with the Guangzhou task values: Moon altitude `31.635` degrees and angular separation `73.765` degrees, both with `0.002` absolute tolerance.
- `tests/test_evaluation_final_review.py`
  - Added deterministic regression coverage for valid bonus evidence, zero-byte files, prose-only records, missing files, escaping references, and unlinked baseline/comparison/verification references.
  - Added a Guangzhou location/time regression that validates task metadata, accepts the Guangzhou CSV, and rejects the Shanghai CSV values.
- `tests/test_evaluation_cli.py`
  - Updated the replay bonus fixture to use valid structured measurement and verification evidence.

## Decisions

The bonus protocol intentionally accepts only JSON records with exact keys. This makes the comparison and verification content deterministic and prevents descriptions or arbitrary text files from being treated as evidence. All declared files are still resolved through the existing run-directory or explicit `repo:` repository-local boundary. Existing category caps and the total ten-point cap remain enforced by `score_case`.

The interval Moon-Jupiter variant was not changed. Its assertions remain tied to its own task; only the Guangzhou location/time manifest was corrected.

## Test-first evidence

Before implementation, the focused final-review test run failed as intended:

```text
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v3-red
2 failed, 8 passed
```

The failures showed that placeholder bonus evidence was accepted and that the manifest still expected Shanghai values. After implementation, the same focused final-review test file passed with `10 passed`.

## Verification

```text
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v3-focused
83 passed

.venv\\Scripts\\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v3-full
162 passed

.venv\\Scripts\\python.exe -m compileall src tests scripts
exit 0

.venv\\Scripts\\python.exe -m pip check
No broken requirements found.

.venv\\Scripts\\python.exe scripts/evaluate_starskill.py --help
exit 0; replay and aggregate help displayed.
```

## Concerns

No implementation concerns identified. The external 9+ Agent evaluation was not run and is not claimed by this report.
