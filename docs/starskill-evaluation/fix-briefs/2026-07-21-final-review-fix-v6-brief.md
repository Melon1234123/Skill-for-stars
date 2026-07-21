# Final Review Fix v6 Brief

Read first: `docs/starskill-evaluation/review-history/2026-07-21-final-review-v5-recheck.md` and the current source/docs/tests.

The project is not a Git worktree. Do not initialize Git or create commits.

## Required fixes

1. **Unify cross-review rotation with the published protocol and user decision.**

   The intended mapping is reviewer role -> Worker case role:

   - teacher reviewer reviews outreach Worker output;
   - outreach reviewer reviews research Worker output;
   - research reviewer reviews teacher Worker output.

   Therefore, for a case whose Worker `case.role` is `teacher`, the expected normal `reviewer_role` is `research`; for `outreach`, expected reviewer is `teacher`; for `research`, expected reviewer is `outreach`. Update replay and aggregate validators, adjudicator escalation's retained normal review, and all affected tests/fixtures to use this one mapping. Keep the public README/prompts/CLI documentation consistent and add a test that directly compares the documented mapping with both validators.

2. **Make every evaluation JSON boundary structured-error safe for oversized values.**

   Catch plain `ValueError` from `json.loads()` at all remaining evaluation JSON loaders, not just bonus loaders: reviewer JSON, escalation JSON, case manifests, score bundles, machine/evidence JSON helpers, and any other parser found by searching the evaluation/CLI code. Convert it to the existing structured `CaseManifestError` or `ReportError` path with a nonzero CLI response. Add regression coverage for a 10,000-digit integer in a case manifest, reviewer file, escalation file, and score.json (parameterized where reasonable). Do not swallow unrelated exceptions or alter normal malformed JSON behavior.

## Verification

Write `docs/starskill-evaluation/review-history/2026-07-21-final-review-fix-v6-report.md` with changed files, decisions, exact commands/results, and concerns. Run:

```powershell
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v6-focused
.venv\\Scripts\\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v6-full
.venv\\Scripts\\python.exe -m compileall src tests scripts
.venv\\Scripts\\python.exe -m pip check
.venv\\Scripts\\python.exe scripts/evaluate_starskill.py --help
```

The external 9+ Agent evaluation remains unrun and must not be claimed.
