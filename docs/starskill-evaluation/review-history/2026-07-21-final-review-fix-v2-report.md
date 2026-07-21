# Final Review Fix v2 Implementation Report

## Status

`DONE_WITH_CONCERNS`. The bounded implementation introduced fail-closed validation for canonical case roots, finite scientific evidence, execution-record schema checking, replay worker/reviewer identity, adjudicator escalation data, bonus-evidence structure and path resolution, complete machine-run comparison, anchored canonical aggregation, stricter M51 normalization, Moon-Jupiter variant assertions, and expanded aggregate Markdown sections.

The external 9+ Agent evaluation was not run. No claim is made that it ran.

## Changed Files

- `src/starskill/evaluation/cases.py`: missing and empty canonical case roots now raise `CaseManifestError`.
- `src/starskill/evaluation/checks.py`: rejects non-finite JSON/CSV values; restricts legacy M51 normalization to `runs/day6_m51`; adds metadata artifact path validation.
- `src/starskill/evaluation/scoring.py`: bonus claims now require evidence paths plus structured baseline, comparison, and verification references.
- `src/starskill/evaluation/reporting.py`: adds a strict execution-record contract, preserves worker role/escalation evidence, resolves bonus files under the run or explicit `repo:` boundary, compares complete machine-run raw inputs, and renders independent open-task reporting and reviewer evidence paths.
- `scripts/evaluate_starskill.py`: anchors canonical cases to the repository, validates worker/review identity during replay, supports `--escalation-file`, returns structured `ValueError` details, and validates execution/bonus evidence before scoring.
- `evaluation/cases/variants/variant-moon-jupiter-interval.json`: adds deterministic CSV assertions.
- `evaluation/cases/variants/variant-moon-jupiter-location-time.json`: adds deterministic CSV assertions.
- `tests/fixtures/evaluation/replay_fixtures.py`: records strict linked worker invocation evidence.
- `tests/test_evaluation_cases.py`, `tests/test_evaluation_checks.py`, `tests/test_evaluation_cli.py`, `tests/test_evaluation_final_review.py`, `tests/test_evaluation_scoring.py`: adds/updates deterministic regression coverage.

## Decisions

- The worker contract accepts only JSONL records declaring `run-starskill`, the exact case/task/workflow/role, run/output directory, exit code, and the exact captured stdout/stderr/response paths. The nested result repeats and links that evidence.
- Normal review rotation is enforced at replay. Adjudication requires a saved escalation object containing the normal review and either its critical issue or a recorded machine-check conflict.
- Bonus claims use structured file references. Run-local references cannot escape the run directory; repository references require the explicit `repo:` boundary.
- Aggregate uses the script's repository root for `evaluation/cases`, independent of caller working directory.

## Verification

1. Baseline focused command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v2-focused-baseline
```

Result: PASS, 71 tests before the v2 regressions were added.

2. Required focused command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v2-focused
```

Result: FAIL. Initial bounded run reported six failures; after the follow-up default-role adjustment, the remaining categories match the full-suite failures below. The focused command was not rerun after that last adjustment.

3. Required full command:

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v2-full
```

Result: FAIL, 3 failures:

- `tests/test_evaluation_cli.py::test_replay_command_writes_machine_and_score_reports`: fixture passes `stderr.json`, while its strict tool record names `stderr.txt`; the fixture must record the selected captured stderr file.
- `tests/test_evaluation_final_review.py::test_replay_rejects_missing_worker_execution_evidence`: expected error code needs alignment after text is read before execution-evidence validation.
- `tests/test_evaluation_final_review.py::test_m51_metadata_does_not_rebind_unrelated_basename`: the new strict metadata check is not reached by the existing reproducibility coverage path; this requires one additional focused correction.

4. Required compilation command:

```powershell
.venv\Scripts\python.exe -m compileall src tests scripts
```

Result: PASS, exit code 0.

5. Required dependency command:

```powershell
.venv\Scripts\python.exe -m pip check
```

Result: PASS, `No broken requirements found.`

6. Required CLI command:

```powershell
.venv\Scripts\python.exe scripts/evaluate_starskill.py --help
```

Result: PASS, exit code 0; printed replay and aggregate command help.

## Unresolved Concerns

- The three failing tests above mean the required focused and full verification contracts are not yet green.
- The v2 brief requests broader matrix, complete machine-tampering, adjudication, bonus-escape, and open-report regression coverage. The implementation adds core support, but this bounded pass did not complete every requested test case.
- Moon-Jupiter location/time assertions currently use the existing Shanghai reference values; matching Guangzhou reference values should be regenerated offline before treating that variant as scientifically finalized.

## Follow-up: Three Focused Failures Resolved

The requested follow-up corrected the three concrete focused-suite failures.

- `tests/test_evaluation_cli.py` now writes the selected custom stderr path into the strict tool-call record. This preserves the evidence linkage for `--stderr-file` and keeps the separate non-UTF-8 test meaningful.
- `scripts/evaluate_starskill.py` now validates the required execution evidence before reading stdout/stderr. Missing worker files therefore produce structured `invalid_execution_evidence`; a missing case still reaches `_require_file` first and produces `input_not_found`.
- `src/starskill/evaluation/checks.py` now validates fetch-image `source_path` and `display_path` independently of `run.json` coverage. Unrelated project-relative metadata produces the critical `invalid_metadata_artifact_path` issue even when the manifest lists every expected artifact.

Fresh targeted regression command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_cli.py::test_replay_command_writes_machine_and_score_reports tests/test_evaluation_final_review.py::test_replay_rejects_missing_worker_execution_evidence tests/test_evaluation_final_review.py::test_m51_metadata_does_not_rebind_unrelated_basename -q --basetemp .pytest-tmp/final-review-v2-three
```

Result: PASS, 3 tests.

Fresh required focused command:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v2-focused-final
```

Result: PASS, 81 tests.

Remaining concern: the full suite was not rerun after this narrow follow-up; its previously recorded failures were all in the focused suite and are now covered by the fresh focused result. The external 9+ Agent evaluation remains unrun.
