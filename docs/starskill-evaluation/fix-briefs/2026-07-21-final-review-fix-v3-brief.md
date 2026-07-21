# Final Review Fix v3 Brief

Read first:

- `docs/starskill-evaluation/review-history/2026-07-21-final-review-v2-recheck.md`;
- `docs/starskill-evaluation/fix-briefs/2026-07-21-final-review-fix-v2-brief.md`;
- current implementation and tests.

The project is not a Git worktree. Do not initialize Git or create commits. Work in the current workspace.

## Required fixes

### 1. Bonus evidence must be content-verifiable

The current `validate_bonus_evidence()` only checks that references resolve to files. Make bonus claims fail closed unless:

- every declared evidence, baseline, comparison, and verification reference resolves within the permitted evidence boundary and is readable and non-empty;
- the baseline and comparison references identify actual evidence content, not only arbitrary descriptions, and are not the same empty/placeholder record; require a deterministic minimal recorded comparison format or otherwise validate that the referenced content includes a concrete baseline/comparison value or measurement;
- verification references contain a concrete recorded test/verification result, not only prose metadata;
- the claim's `evidence_paths` are linked to the same evidence files and the claim remains within category and total caps.

Choose a strict, documented local schema compatible with the existing evaluation protocol and update fixtures/tests to use valid evidence. Add tests proving zero-byte files, arbitrary prose-only files, missing referenced files, escaping references, and unlinked baseline/comparison/verification are rejected, while a valid deterministic evidence bundle passes. Do not make a bonus pass merely because a file exists.

### 2. Correct Moon-Jupiter Guangzhou variant assertions

`evaluation/tasks/variant-moon-jupiter-location-time.json` declares Guangzhou (`113.2644`, `23.1291`) at `2026-03-21 18:30:00`. The current manifest incorrectly expects Shanghai core values. Replace its deterministic CSV assertions with the offline repository workflow values for that exact task: first-row Moon altitude `31.635` degrees and apparent angular separation `73.765` degrees, with explicit tolerances suitable for the existing deterministic calculator. Keep the interval variant's assertions tied to its own declared task. Add a regression test that checks the location/time manifest values match the Guangzhou reference and that a correct Guangzhou CSV passes while Shanghai values fail.

## Verification

Write/update `docs/starskill-evaluation/review-history/2026-07-21-final-review-fix-v3-report.md` with changed files, decisions, exact test commands/results, and concerns. Run:

```powershell
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v3-focused
.venv\\Scripts\\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v3-full
.venv\\Scripts\\python.exe -m compileall src tests scripts
.venv\\Scripts\\python.exe -m pip check
.venv\\Scripts\\python.exe scripts/evaluate_starskill.py --help
```

Do not claim external 9+ Agent evaluation; it remains unrun.
