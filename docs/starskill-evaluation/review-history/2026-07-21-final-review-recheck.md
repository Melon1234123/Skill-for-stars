# StarSkill Evaluation Fix Final Re-review

## Findings

### Critical

1. **Replay does not prove that StarSkill or the declared CLI workflow actually ran.**

   `scripts/evaluate_starskill.py:192-218` accepts `tool_calls.jsonl` when it contains any non-empty JSON-object record. It does not validate a command, tool identity, case task, workflow, arguments, output directory, or linkage to captured artifacts. The repository's own fixture uses only `{"tool": "run-starskill"}` (`tests/test_evaluation_cli.py:9-14`), which is prose-like evidence rather than a verified invocation. A temporary diagnostic confirmed that `{"anything": 1}` is accepted. Artifact checks establish that files exist, but they do not establish that the declared external Skill/CLI execution produced them. This leaves the central execution-evidence outcome fail-open.

2. **Scientific numeric checks accept non-finite values as passing evidence.**

   `src/starskill/evaluation/checks.py:323-345` converts CSV values with `float()` and checks only `abs(value - expected) > tolerance`. For `NaN`, that comparison is false, so the assertion passes. The analogous JSON path at `src/starskill/evaluation/checks.py:243-264` has the same issue for a parsed non-finite float. A temporary diagnostic supplied `NaN` for the Moon-Jupiter separation and produced `hard_gate_passed=True` with no issue. Scientific assertions must reject non-finite observed values before tolerance comparison.

### Important

3. **Canonical manifest enforcement can be bypassed by invoking aggregate outside the repository root.**

   `scripts/evaluate_starskill.py:109-113` passes the relative path `evaluation/cases`. `src/starskill/evaluation/cases.py:69-76` treats a missing root as an empty case set rather than an error. `src/starskill/evaluation/reporting.py:137-156` then skips evidence rederivation and matrix validation when that canonical map is empty. A temporary diagnostic from another working directory loaded zero canonical cases. The CLI contract asks callers to run from the root, but the required outcome is enforcement, not a caller convention; the path must be anchored to the project/script location and an empty canonical set must fail closed.

4. **Replay can emit a passing score with a wrong case/reviewer identity; reviewer protocol is enforced only later and adjudication cannot represent the documented escalation.**

   `src/starskill/evaluation/scoring.py:51-82` does not compare `review.case_id` or reviewer role to the case, and `scripts/evaluate_starskill.py:67-92` writes the resulting score without a rotation check. Rotation is checked only during canonical aggregation at `src/starskill/evaluation/reporting.py:255-281`. A temporary replay diagnostic used a `teacher` reviewer for a teacher-role case and returned success. In addition, `src/starskill/evaluation/reporting.py:267-274` permits an adjudicator only when the machine report already has a critical issue; the documented path also allows escalation after a normal reviewer reports a critical issue or conflicts with machine checks, but the bundle preserves no prior normal-review evidence with which to prove that path.

5. **Bonus claims are schema-shaped, not evidence-backed.**

   `src/starskill/evaluation/scoring.py:42-49` requires only non-empty strings for evidence paths, baseline, and verification. Neither replay nor aggregation resolves the paths, confines them to the run, checks that they exist, hashes their contents, or validates a baseline/comparison and test record (`src/starskill/evaluation/scoring.py:82-132`, `src/starskill/evaluation/reporting.py:205-211`). A temporary diagnostic awarded bonus points using `does-not-exist.txt` and arbitrary prose. This does not satisfy the requirement to reject unsupported or unverifiable bonus claims.

6. **Part of `machine_checks.json` can be tampered without detection.**

   The machine report writer embeds raw inputs under `machine_checks.json.run` (`src/starskill/evaluation/reporting.py:91-101`), but aggregation checks only that object's `run_id` and `run_dir` (`src/starskill/evaluation/reporting.py:183-204`). It rederives from the separate `score.json.raw_inputs`, never comparing the remaining captured machine-run fields. A temporary diagnostic changed `machine_checks.json.run.stdout`; `_validate_bundle_against_evidence` still accepted the bundle. Required tamper rejection therefore does not cover the complete referenced machine report.

7. **Malformed over-cap bonus input leaks an unstructured exception.**

   `score_case()` raises `ValueError` for a category over its cap (`src/starskill/evaluation/scoring.py:123-131`). The CLI catches `ValueError` together with Pydantic `ValidationError` and unconditionally calls `exc.errors()` (`scripts/evaluate_starskill.py:70-77`). A temporary diagnostic with a `3.1` standardization award raised `AttributeError: 'ValueError' object has no attribute 'errors'` instead of returning structured JSON.

8. **Legacy M51 metadata normalization can silently rebind an unrelated project-relative reference by basename.**

   `src/starskill/evaluation/checks.py:935-953` first tries `run_dir / candidate`, then searches the entire run by `candidate.name` and accepts the sole match. Thus an incorrect project-relative `source_path` can be treated as the expected artifact merely because one file under the run has the same basename. The production writer correctly emits run-relative paths (`src/starskill/public_data_fetcher.py:236-248`), but replay should normalize the known legacy run prefix or reject ambiguous/incorrect references, not discard all parent components.

9. **Relevant Moon-Jupiter variants still have no deterministic scientific assertions.**

   The core manifest now asserts two CSV values, but `evaluation/cases/variants/variant-moon-jupiter-interval.json:17` and `evaluation/cases/variants/variant-moon-jupiter-location-time.json:17` retain empty `numeric_assertions` and define no `csv_assertions`. Those are the relevant scientific variants named by the brief, so they can pass with any non-empty relationship CSV and the expected task-type metadata.

10. **Several explicitly required regression tests are absent.**

   The focused files contain no tests for missing core runs, duplicate `(case_id, run_id)`, missing variants, allowed cross-case run-ID reuse, wrong declared worker role, tampered stdout/stderr/tool-call contents, or full machine-run tampering. `tests/test_evaluation_final_review.py:152-181` covers nested score tampering and one aggregate rotation mismatch only. There is also no test that bonus evidence paths/verification records exist or that open-task aggregate Markdown is separated. The fresh focused run passed all 71 tests, demonstrating that the confirmed fail-open paths are outside current coverage.

### Minor

11. **Aggregate Markdown does not fully separate open-task reporting or associate every critical failure with its evidence source.**

   `src/starskill/evaluation/reporting.py:483-527` never renders `summary.open_task_scores`; open results appear only in the all-runs table. Critical paths are emitted as a detached unique list, and reviewer-caused hard-gate failures have no review evidence path because `score_case()` carries only machine issues (`src/starskill/evaluation/scoring.py:70-79`). The JSON keeps open scores separate, but the human-facing aggregate does not fully meet the reporting contract.

## Assumptions And Evidence

- The current filesystem is authoritative because the project has no Git metadata. No source, manifest, documentation, or test file was edited during this review.
- The user supplied prior evidence that the 150-test full suite and static verification passed. I did not rerun the full suite.
- Fresh focused verification: `.venv\Scripts\python.exe -m pytest tests/test_evaluation_cases.py tests/test_evaluation_checks.py tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_evaluation_cli.py tests/test_evaluation_replay.py tests/test_evaluation_final_review.py -q --basetemp .pytest-tmp/final-review-recheck` passed all 71 tests.
- Small temporary-directory diagnostics confirmed findings 1-7 without modifying repository files.
- Core matrix counting and `(case_id, run_id)` duplicate identity are implemented at `src/starskill/evaluation/reporting.py:135-156` and `src/starskill/evaluation/reporting.py:285-296`; cross-case run-ID reuse is allowed by the pair key. These paths remain vulnerable to finding 3 and lack the required direct regression coverage.
- Fixed scoring remains 100 base plus at most 10 bonus, and open tasks are scaled to 20 and excluded from the fixed-case decision (`src/starskill/evaluation/scoring.py:107-142`, `src/starskill/evaluation/scoring.py:145-195`). Bonus evidence integrity remains unresolved per finding 5.
- The external 9+ Agent evaluation was not executed as part of this review and must not be inferred from repository test results.

## Verdict

**FAIL - changes required.** The branch does not yet meet the final-review fix brief because actual execution evidence, scientific finite-value validation, canonical aggregation enforcement, replay identity/rotation, bonus evidence verification, complete tamper detection, and structured malformed-input handling still have confirmed fail-open paths.
