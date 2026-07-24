# Recorded Acceptance Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore reproducible, script-owned CLI capture and a 15-run release acceptance matrix without representing it as external Worker or reviewer evidence.

**Architecture:** A runner invokes the installed CLI with an argv list and writes an immutable execution record, captured inputs, stdout, stderr, exit code, and hashes. Replay accepts either this script-owned record or the existing external Worker evidence. The release command repeats every core case three times and every variant once, then uses replay and aggregation. External Agent orchestration remains outside the repository.

**Tech Stack:** Python 3.11+, Pydantic, pytest, subprocess, existing StarSkill CLI.

## Global Constraints

- Use `subprocess.run` with an argv list and `shell=False` behavior.
- Every recorded run directory must be new and empty before capture.
- Preserve the existing external Worker `tool_calls.jsonl` plus `response.md` contract.
- Script-owned records are not Worker responses and do not create Agents or call an LLM API.
- The release matrix contains 3 repetitions of each core case and 1 execution of each variant case: 15 runs total.
- Keep all generated evidence outside tracked source paths.

---

### Task 1: Record one actual CLI run

**Files:**
- Create: `src/starskill/evaluation/runner.py`
- Modify: `src/starskill/evaluation/models.py`
- Modify: `src/starskill/evaluation/reporting.py`
- Create: `tests/test_evaluation_runner.py`

- [ ] Write a failing test that executes `failure-invalid-timezone` and asserts copied case/task inputs, exit code `2`, captured stderr, argv, and `execution.json` hashes.
- [ ] Run `pytest tests/test_evaluation_runner.py -q` and confirm collection fails because `starskill.evaluation.runner` is absent.
- [ ] Add `ExecutionRecord`, a safe `execute_case` runner, and replay validation for its copied inputs, paths, argv, exit code, stdout/stderr, and hashes.
- [ ] Re-run `pytest tests/test_evaluation_runner.py -q` and the existing replay tests.

### Task 2: Expose recording and the release matrix

**Files:**
- Modify: `scripts/evaluate_starskill.py`
- Modify: `tests/test_evaluation_cli.py`

- [ ] Write failing tests for `execute` and `acceptance`; assert every core case is executed three times with distinct run directories, each variant once, and overlapping/non-empty output roots are rejected.
- [ ] Run the focused CLI tests and confirm the commands are absent.
- [ ] Add `execute` and `acceptance`. `acceptance` must replay all 15 recorded runs and aggregate the resulting score reports; it must output `mode: script_owned_engineering_acceptance`.
- [ ] Re-run the focused CLI tests and the full evaluation test group.

### Task 3: Document the two evidence modes

**Files:**
- Modify: `README.md`
- Modify: `evaluation/README.md`
- Modify: `skills/run-starskill/references/cli-contract.md`
- Test: `tests/test_cli.py`

- [ ] Write a failing documentation assertion requiring the 15-run command and prohibiting a claim that script-owned evidence is an external Worker/reviewer run.
- [ ] Run the documentation test and confirm it fails before the documentation change.
- [ ] Document the exact fresh-clone command, its artifact locations, and the remaining external Worker/reviewer requirements.
- [ ] Re-run the documentation test and all tests.

### Task 4: Release verification

- [ ] Run `python scripts/evaluate_starskill.py acceptance` in new temporary output roots with the project environment.
- [ ] Inspect all 15 `execution.json` files, aggregate report, and matrix counts.
- [ ] Run `python -m pytest -q`, `python -m compileall -q src scripts`, `python -m pip check`, and `git diff --check`.
- [ ] Commit and fast-forward publish the repaired branch to `origin/main`.
- [ ] Request a fresh, independent subagent acceptance using only a neutral re-clone-and-audit task statement.
