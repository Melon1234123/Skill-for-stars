# Final Review Fix v2 Brief

## Inputs

Read these files first:

- `.superpowers/sdd/2026-07-21-final-review-fix-report.md` if present;
- `docs/starskill-evaluation/review-history/2026-07-21-final-review-recheck.md`;
- `docs/starskill-evaluation/fix-briefs/2026-07-21-final-review-fix-brief.md`;
- the current implementation and tests.

The project root is not a Git worktree. Do not initialize Git or create commits. Work in the current workspace and preserve unrelated changes.

## Objective

Resolve every Critical and Important finding in the final re-review, plus the Minor aggregate-report finding. The evaluation layer must fail closed when execution identity, scientific evidence, reviewer identity, bonus evidence, or canonical case completeness cannot be proved.

## Required fixes

1. **Verify real execution evidence, not just JSON-shaped filler.**

   Extend `tool_calls.jsonl` validation so each record proves a declared `run-starskill`/repository CLI invocation: command/tool identity, the declared case task/workflow, run/output directory linkage, and captured result/output linkage. Use a strict deterministic schema appropriate to the existing worker protocol. Reject `{ "anything": 1 }` and the current prose-like fixture. Validate captured response, stdout, stderr, exit code, tool calls, and output directory as one linked evidence set. Add tests for a fake tool record and mismatched task/workflow/output directory.

2. **Reject non-finite numeric evidence.**

   JSON numeric assertions and CSV numeric assertions must reject NaN, positive infinity, and negative infinity before tolerance comparison, with a critical issue. Add regression tests for both JSON and CSV.

3. **Canonical case loading must be anchored and fail closed.**

   Aggregate must resolve `evaluation/cases` from the repository/project location, not the caller's current working directory. A missing or empty canonical cases root must be a structured error. Preserve the exact canonical matrix checks: all three core cases exactly three runs each, all six variants present, and unique `(case_id, run_id)` while allowing the same run ID under different cases. Add tests running aggregate from another working directory and for missing/empty canonical roots.

4. **Enforce identity and reviewer rotation at replay time.**

   Replay must validate the review's `case_id`, declared case kind/role, and required reviewer rotation before writing a passing bundle. The normal mapping is teacher case -> outreach reviewer, outreach case -> research reviewer, research case -> teacher reviewer. Adjudicator is permitted only with a documented escalation containing the normal reviewer evidence and either a normal-review critical issue or a conflict with machine checks. Extend the bundle schema/CLI inputs as needed to preserve and validate that escalation evidence. Add tests for wrong case ID, wrong reviewer role, wrong worker role, and valid/invalid adjudication.

5. **Make bonus evidence genuinely verifiable.**

   Bonus claims must include awarded value, evidence paths, baseline/comparison, and verification/test record. Resolve every evidence path inside the run directory (or explicitly documented repository-local evidence boundary), require existing readable files, and ensure baseline/comparison and verification identify actual evidence or recorded test output. Reject nonexistent, escaping, or bare-prose claims. Keep category caps and the total 10-point cap. Add tests for valid evidence and nonexistent/escaping evidence.

6. **Detect complete machine report tampering.**

   When aggregating, compare every captured `machine_checks.json.run` field against the score bundle raw inputs and the actual evidence files, not only run ID and directory. Tampering stdout/stderr/paths/return code/tool-call/response metadata must fail closed. Add a regression test for each relevant raw field or a parameterized equivalent.

7. **Keep malformed replay input structured.**

   Do not call `exc.errors()` on a plain `ValueError`. Over-cap bonus claims and all malformed bonus/review/case inputs must return structured JSON errors from the CLI. Add a test for an over-cap bonus.

8. **Make M51 legacy normalization strict.**

   Do not rebind arbitrary project-relative metadata by basename. Normalize only the known legacy M51 output prefix (for example `runs/day6_m51/...`) to the declared run-relative artifact path, or reject references whose normalized path is not an expected artifact. Reject unrelated/ambiguous basename references. Preserve the real-shaped legacy regression test.

9. **Add scientific assertions to the Moon-Jupiter variants.**

   Add deterministic CSV/numeric assertions with explicit tolerances to both `variant-moon-jupiter-interval.json` and `variant-moon-jupiter-location-time.json`, using existing reference workflow values and matching each task's parameters. Wrong values must produce critical issues. Keep tests offline.

10. **Add the missing regression coverage.**

   Tests must cover missing core repeat, duplicate pair, missing variant, allowed cross-case run-ID reuse, wrong declared worker role, tampered stdout/stderr/tool-call contents, complete machine-run tampering, bonus evidence failures, and open-task aggregate reporting. Keep all tests deterministic and network-free.

11. **Complete aggregate reporting.**

   Aggregate Markdown must explicitly show open-task scores as an independent 20-point section, per-case completeness counts, thresholds, standard deviations, final decisions, and critical-failure evidence paths including reviewer evidence when the reviewer caused the failure. Do not fold open scores into the fixed-case table or pass decision.

## Verification contract

Write a report to `docs/starskill-evaluation/review-history/2026-07-21-final-review-fix-v2-report.md` containing changed files, decisions, and exact command output summaries. Run:

```powershell
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-v2-focused
.venv\\Scripts\\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-v2-full
.venv\\Scripts\\python.exe -m compileall src tests scripts
.venv\\Scripts\\python.exe -m pip check
.venv\\Scripts\\python.exe scripts/evaluate_starskill.py --help
```

Do not claim the external 9+ Agent evaluation ran; it has not been run unless the report contains fresh evidence from that execution.
