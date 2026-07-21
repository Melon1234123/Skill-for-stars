# StarSkill Evaluation v4 Final Re-review

## Findings

### Important

1. **Aggregate can count one physical core run three times after synchronized `run_id` tampering.**

   Replay initially derives `run_id` from `run_dir.name` at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:119`, but aggregate never re-derives that identity. It uses the mutable `(bundle.case_id, bundle.run_id)` pair for duplicate detection at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:162` and only compares the mutable bundle ID with the mutable `machine_checks.json.run.run_id` at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:209`. Matrix completeness then counts bundles by case ID at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:580` without requiring distinct resolved run directories. A fresh offline diagnostic copied one valid M42 score bundle three times, assigned three different IDs in both `score.json` and each copied `machine_checks.json`, and left all three bundles pointing to the same physical `run_dir`. All three passed `_validate_bundle_against_evidence`, had unique pair IDs, and satisfied the three-run M42 matrix count. This bypasses the required three independent core runs and makes pair identity self-authenticating after synchronized tampering.

### Minor

2. **An oversized integer in the top-level `--bonus-file` still escapes the structured CLI error boundary.**

   The v4 change correctly catches `ValueError` while parsing referenced measurement/verification records at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:502`, but the bonus declaration itself is parsed separately by `json.loads()` at `F:\Skill-for-stars\scripts\evaluate_starskill.py:203`. Its handler at `F:\Skill-for-stars\scripts\evaluate_starskill.py:204` catches `JSONDecodeError` but not plain `ValueError`, while `main()` catches only `CaseManifestError` and `ReportError` at `F:\Skill-for-stars\scripts\evaluate_starskill.py:52`. A fresh valid-shaped bonus claim with a 10,000-digit `awarded` integer escaped as raw `ValueError` instead of returning structured JSON. The regression at `F:\Skill-for-stars\tests\test_evaluation_final_review.py:298` covers an oversized referenced measurement file, not the top-level bonus record required by the v4 brief's "any malformed/oversized bonus JSON" wording.

3. **The strict `tool_calls.jsonl` schema is not documented and conflicts with the Worker prompt contract.**

   The validator requires the exact private field set declared at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:41` and rejects any extra or missing field at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:332`. The Worker prompts instead require actual command arguments and an observed result summary at `F:\Skill-for-stars\evaluation\prompts\workers\teacher.md:15`, `F:\Skill-for-stars\evaluation\prompts\workers\outreach.md:15`, and `F:\Skill-for-stars\evaluation\prompts\workers\research.md:15`; an `arguments` field is rejected by the implementation. The CLI contract asks the harness to preserve the exact command at `F:\Skill-for-stars\skills\run-starskill\references\cli-contract.md:64` but does not specify the accepted JSONL keys, absolute-path representation, or nested result schema. A fresh documented-shape record was rejected as `invalid_execution_evidence`. The test fixture passes only because it encodes the implementation-private shape at `F:\Skill-for-stars\tests\fixtures\evaluation\replay_fixtures.py:195`.

## Assumptions And Evidence

- `F:\Skill-for-stars` is the authoritative filesystem and is intentionally not a Git worktree. No source, manifest, fixture, test, or documentation file was edited; only this requested report was added.
- The controller's successful v4 focused/full suites, `compileall`, `pip check`, and CLI help are treated as independently supplied evidence and are not claimed as fresh executions here.
- Fresh bounded regression verification passed 13 selected tests covering both v4 regressions, bonus content, finite JSON/CSV values, M51 normalization, Guangzhou assertions, and open-task scoring.
- Fresh role diagnostics rejected score-only, tool-call-only, and synchronized role tampering. The canonical checks are present at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:198` and `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:342`.
- Fresh execution diagnostics accepted the strict linked record and rejected wrong workflow, task, output directory, and nested result linkage. The linkage checks are implemented at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:332` through `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:352`.
- Fresh matrix/reviewer diagnostics rejected missing core and variant counts, duplicate pairs, wrong Worker/reviewer roles, and missing adjudication evidence; allowed cross-case run-ID reuse and valid critical-review adjudication. Finding 1 is the remaining synchronized identity/reused-directory bypass.
- Finite observed JSON and CSV values fail closed at `F:\Skill-for-stars\src\starskill\evaluation\checks.py:255` and `F:\Skill-for-stars\src\starskill\evaluation\checks.py:346`. Strict M51 legacy normalization is limited to `runs/day6_m51` at `F:\Skill-for-stars\src\starskill\evaluation\checks.py:996` and rejects unrelated prefixes.
- A fresh offline Astropy calculation for the Guangzhou task reproduced `31.635` degrees Moon altitude and `73.765` degrees apparent separation, matching `F:\Skill-for-stars\evaluation\cases\variants\variant-moon-jupiter-location-time.json:19`; Shanghai values were rejected by two critical CSV mismatches.
- Bonus evidence remains content-verifiable through strict linked measurement and passing-verification records at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:449` through `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:477`. Finding 2 concerns the earlier top-level declaration parser only.
- Open tasks are scaled independently at `F:\Skill-for-stars\src\starskill\evaluation\scoring.py:115`, excluded from fixed/core decisions at `F:\Skill-for-stars\src\starskill\evaluation\scoring.py:155`, and rendered in a separate `/ 20` section at `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:806`.
- The external 9+ Agent evaluation remains unrun and is not inferred from repository tests.

## Verdict

**FAIL - changes required.** The v4 canonical Worker-role and referenced oversized-measurement fixes are correct, and the other named prior fail-open paths remain closed in bounded diagnostics. Aggregate run identity can still be synchronized-tampered so one physical run counts as three independent runs, top-level oversized bonus JSON can still escape unstructured, and the strict execution-record schema remains inconsistent with its public harness documentation.
