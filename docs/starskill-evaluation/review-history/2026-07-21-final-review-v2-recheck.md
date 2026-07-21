# StarSkill Evaluation v2 Final Re-review

## Findings

### Important

1. **Bonus evidence is path-checked but still not content-verified.**

   `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:431` resolves the declared evidence, baseline, comparison, and verification references, but `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:434` only requires each reference to be a file and `F:\Skill-for-stars\src\starskill\evaluation\reporting.py:437` merely calls `read_bytes()` without requiring non-empty or meaningful content. It does not establish that the baseline and comparison contain measurements, differ from one another, or that verification contains a recorded test result. A fresh temporary-directory diagnostic created four zero-byte files with arbitrary descriptions; `validate_bonus_evidence()` accepted the claim and printed `ACCEPTED_EMPTY_BONUS_EVIDENCE`. The normal CLI fixture also uses the same `stdout.txt` as evidence, baseline, comparison, and verification (`F:\Skill-for-stars\tests\test_evaluation_cli.py:73`). This remains fail-open against the v2 requirement to reject bare-prose claims and verify evidence content, baseline/comparison, and a test or verification record.

2. **The Moon-Jupiter location/time variant asserts the core Shanghai values rather than values for its Guangzhou task.**

   The variant task declares Guangzhou at longitude `113.2644`, latitude `23.1291`, starting `2026-03-21 18:30:00` (`F:\Skill-for-stars\evaluation\tasks\variant-moon-jupiter-location-time.json:5` and `F:\Skill-for-stars\evaluation\tasks\variant-moon-jupiter-location-time.json:11`). Its manifest nevertheless expects `5.226` degrees Moon altitude and `87.917` degrees separation (`F:\Skill-for-stars\evaluation\cases\variants\variant-moon-jupiter-location-time.json:19`), exactly the core Shanghai references. A fresh offline run of the repository relationship workflow for the declared Guangzhou task produced first-row values `31.635` and `73.765`. Therefore a scientifically correct run fails the hard-gate assertions while output copied from the different Shanghai task passes. The regression only checks that each variant has a non-empty assertion list, not that values match task parameters (`F:\Skill-for-stars\tests\test_evaluation_final_review.py:203`).

## Assumptions And Evidence

- The current filesystem is authoritative because `F:\Skill-for-stars` has no Git metadata. No project source, manifest, prompt, fixture, documentation, or test file was edited; only this requested review report was added.
- I inspected the current requirements, previous findings, v2 implementation report, evaluation source, CLI, canonical manifests/tasks, prompts/documentation, fixtures, and focused tests directly.
- The bonus and Moon-Jupiter diagnostics were deterministic, offline, and used temporary directories outside the project.
- The controller independently verified 160 full tests, `compileall`, `pip check`, and CLI help. I did not rerun or independently claim those suite/static results after the user's direction to conclude.
- No additional residual finding was identified in strict linked execution records, finite JSON/CSV rejection, anchored canonical loading and matrix/pair identity, replay worker/reviewer identity and adjudicator evidence, complete machine-run field comparison, strict M51 normalization, independent open-task reporting, or structured malformed-input handling.
- The external 9+ Agent evaluation has not been shown as freshly executed and is not inferred from repository tests.

## Verdict

**FAIL - changes required.** The v2 branch still has two Important correctness gaps: bonus points can be backed by empty/non-verifying files, and the location/time Moon-Jupiter variant enforces scientific values from the wrong task parameters.
