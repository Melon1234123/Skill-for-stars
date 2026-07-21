# Final Review Fix Brief: StarSkill Agent Evaluation

## Context

The StarSkill evaluation implementation has completed Tasks 1-6 and a whole-branch review. The review package is at `docs/starskill-evaluation/review-history/final-review-package.md`. The project root is not a Git worktree; do not initialize Git or create commits. Work in the current workspace and preserve unrelated user changes.

## Objective

Fix every Critical/Important issue from the whole-branch review in one coherent change. The resulting replay and aggregation layer must only pass evidence that is tied to the declared case, role, run, and actual on-disk artifacts. It must preserve the product requirement: evaluate whether an AI Agent closes a concrete astronomy task loop, with hard gates plus quantified scoring, while keeping open tasks on an independent 20-point scale.

## Required outcomes

1. **Path and evidence integrity**

   - Fix production metadata/replay path handling, especially the real M51 bundle where metadata currently stores a project-relative path and replay can prepend `run_dir` twice. Normalize or validate all artifact references consistently as run-relative paths; add a regression test using the real-shaped M51 metadata.
   - Replay must machine-verify actual external Skill/CLI execution evidence: captured return code, stdout/stderr, `tool_calls.jsonl` when required by the worker contract, and captured output files. Do not accept a score merely because `score.json` says it passed.
   - Make malformed case manifests and malformed input files return structured `ReportError`/JSON CLI errors rather than leaking `JSONDecodeError`, `ValidationError`, or other unstructured exceptions.

2. **Case matrix and identity enforcement**

   - Load the canonical case manifests from `evaluation/cases` and enforce in aggregation: all three core case IDs are present, each core case has exactly three independent runs, all six variant case IDs are present, and no duplicate `(case_id, run_id)` exists. Do not require run IDs to be globally unique across different cases.
   - Validate wrapper and nested `case_id`, `case_kind`, declared role, reviewer role, and reviewer rotation. The three normal reviewer mappings are: teacher case reviewed by outreach, outreach case reviewed by research, research case reviewed by teacher. Adjudicator is allowed only for the documented escalation path. Add tests that a wrong role or wrong rotation cannot pass.
   - Ensure score reports cannot be trusted as self-authenticating input: aggregation/replay must re-derive or cross-check machine checks, review data, score fields, and referenced report paths against the current case/run evidence. Tampering with `score.json`, `machine_checks.json`, or review data must fail closed.

3. **Scientific assertions**

   - Add meaningful deterministic numeric/CSV assertions to the core and relevant variant manifests. At minimum cover the Moon-Jupiter apparent angular separation/relationship values from the existing reference workflow and M51 request/cache metadata (including a machine-checkable cache reuse indicator or equivalent captured evidence). Keep tolerances explicit and use existing deterministic reference values; no live network access in tests.
   - Ensure the replay checker validates CSV structure and the declared scientific values, not only that files exist and are non-empty. Wrong Moon-Jupiter numbers or a cache miss in the cache-reuse case must produce a critical machine issue.

4. **Scoring contract**

   - Preserve the fixed-case 100-point base score and up to 10 engineering bonus points, but make each bonus evidence-backed. A bonus entry must include its awarded value, evidence path(s), baseline/comparison, and test or verification record. Reject unsupported or unverifiable bonus claims instead of accepting bare numeric values.
   - Score open tasks on their own 20-point scale and report them separately. Open-task values must not enter the fixed-case 100+10 aggregation or core pass boolean.

5. **Reports and documentation**

   - Make aggregate Markdown include the acceptance thresholds, standard deviations, per-case completeness counts, final decision, and critical-failure evidence paths. Make case summaries expose the captured execution evidence and bonus evidence paths.
   - Update relevant evaluation README/Skill/CLI contract text if the enforced fields or reviewer protocol changed. Do not change the existing StarSkill command syntax or workflow selection rules.

## Tests required

Add or update focused tests for each outcome above, including:

- real-shaped M51 relative metadata path replay;
- malformed case manifest structured error;
- missing/tampered stdout, stderr, `tool_calls.jsonl`, or captured execution evidence;
- aggregate missing core/duplicate repeat/missing variant and allowed cross-case run ID reuse;
- wrong role and wrong reviewer rotation;
- tampered machine/review/score report rejection;
- Moon-Jupiter numeric/CSV mismatch and M51 cache-reuse mismatch;
- bonus evidence schema and open-task 20-point scoring;
- aggregate Markdown threshold/completeness/critical-evidence content.

Run at minimum with the workspace interpreter:

```powershell
.venv\\Scripts\\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py -q --basetemp .pytest-tmp/final-review-focused
.venv\\Scripts\\python.exe -m pytest -q --basetemp .pytest-tmp/final-review-full
.venv\\Scripts\\python.exe -m compileall src tests scripts
.venv\\Scripts\\python.exe -m pip check
.venv\\Scripts\\python.exe scripts/evaluate_starskill.py --help
```

Do not claim that the external 9+ Agent evaluation has been executed unless it is actually run. Report any remaining live/external-evaluation gap clearly.

## Implementer report

Write the implementation report to `.superpowers/sdd/2026-07-21-final-review-fix-report.md`. Include changed files, behavior decisions, every test command and result, and any unresolved concern. Return only a short status plus the report path after editing.
