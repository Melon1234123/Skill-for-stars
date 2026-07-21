# StarSkill Evaluation v3 Final Re-review

## Findings

### Important

1. **Aggregate revalidation does not anchor the captured Worker role to the canonical case role.**

   `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:330` checks only that a tool record's `worker_role` is one of the three valid role strings, and `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:332` compares it only with the mutable `ScoreBundle.worker_role`. Unlike replay (`F:\Skill-for-stars\scripts\evaluate_starskill.py:228`), aggregate evidence revalidation never compares either value with `case.role`. A fresh offline diagnostic replayed a valid teacher case, changed both `score.json.worker_role` and `tool_calls.jsonl.worker_role` to `research`, and called the same canonical evidence validator used by aggregation; it returned successfully as `ACCEPTED_WRONG_CANONICAL_WORKER_ROLE`. The machine report, review, score, and all on-disk artifacts remained otherwise unchanged. This leaves declared role identity tamperable after replay, contrary to the whole-branch requirement that aggregation fail closed against canonical case/role identity.

### Minor

2. **A JSON-valid oversized bonus measurement escapes the structured-error boundary.**

   `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:492` calls `json.loads()` for a structured bonus record, but `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:493` catches only decoding exceptions. CPython raises plain `ValueError` when an integer exceeds its configured digit limit. The top-level CLI catches only `CaseManifestError` and `ReportError` at `F:\Skill-for-stars\scripts\evaluate_starskill.py:52`. A fresh replay diagnostic supplied an otherwise valid `starskill_bonus_measurement` record with a 10,000-digit integer and raised raw `ValueError: Exceeds the limit (4300 digits) for integer string conversion` instead of returning the documented JSON error object. Normal malformed bonus/review/case tests pass, but this valid JSON edge remains outside the structured error contract.

## Assumptions And Evidence

- `F:\Skill-for-stars` is the authoritative filesystem. It is intentionally not a Git worktree; no Git repository was initialized. No source, manifest, test, fixture, prompt, or documentation file was edited. Only this requested report was added.
- The two v3 former gaps are fixed. Bonus references are linked at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:432`, read and required non-empty at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:468`, parsed as strict finite measurement records at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:504`, and required to contain a passing verification at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:529`. Fresh diagnostics accepted the valid bundle and rejected empty, prose-only, non-passing, and unlinked records with `invalid_bonus_evidence`; source and existing tests also cover missing and escaping references.
- The Guangzhou task identifies the location at `F:\Skill-for-stars\evaluation\tasks\variant-moon-jupiter-location-time.json:5`, declares longitude `113.2644` at `F:\Skill-for-stars\evaluation\tasks\variant-moon-jupiter-location-time.json:6` and latitude `23.1291` at `F:\Skill-for-stars\evaluation\tasks\variant-moon-jupiter-location-time.json:7`, and starts at `2026-03-21 18:30:00` at `F:\Skill-for-stars\evaluation\tasks\variant-moon-jupiter-location-time.json:11`; its manifest expects `31.635` and `73.765` at `F:\Skill-for-stars\evaluation\cases\variants\variant-moon-jupiter-location-time.json:19`. A fresh offline Astropy workflow produced exactly those rounded first-row values; the correct CSV passed and Shanghai `5.226`/`87.917` values produced two critical `csv_assertion_mismatch` issues. The interval manifest remains tied to its own Shanghai task.
- Fresh samples confirmed the prior fail-open fixes: strict linked `run-starskill` tool/task/workflow/output evidence; finite JSON/CSV rejection; repository-anchored canonical loading; complete core/variant matrix checks; duplicate pair rejection with cross-case run-ID reuse; replay Worker/reviewer identity and valid adjudication; rejection of tampering in every captured machine-run field; strict known-prefix M51 normalization; and independent open-task 20-point scoring/reporting. Finding 1 is specifically the aggregate-time role check missing after otherwise successful replay identity validation.
- Fresh command: `.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v3-recheck` exited `0`. The controller independently reports `83` focused and `162` full tests plus successful `compileall`, `pip check`, and CLI help; those controller results are not presented as my own fresh executions.
- The external 9+ Agent evaluation remains unrun and is not inferred from repository tests.

## Verdict

**FAIL - changes required.** The two final-review v3 target fixes are correct, but aggregate-time canonical Worker-role identity remains fail-open and oversized structured bonus JSON can still bypass the CLI's structured error response.
