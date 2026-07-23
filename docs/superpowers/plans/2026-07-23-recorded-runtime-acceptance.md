# Recorded Runtime Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace self-declared Agent tool-call evidence with script-recorded subprocess evidence and reduce acceptance to a competition-sized, reproducible runtime matrix.

**Architecture:** `scripts/evaluate_starskill.py execute` will load one immutable case manifest, run the exact `python -m starskill` command without a shell, and write `execution.json`, stdout, stderr, exit code, copied inputs, and output hashes inside a new run directory. `replay` will consume that generated record rather than command-line values or Worker-authored `tool_calls.jsonl`. Three role-aligned core cases and all six input variants are one-run machine acceptance cases; failure and open cases remain deterministic test coverage rather than a release gate.

**Tech Stack:** Python 3.11+, Pydantic, subprocess, Pytest.

## Global Constraints

- Do not execute a shell command built from external data.
- Do not manufacture CLI output, source metadata, or exit codes.
- Every acceptance run uses a fresh empty output directory.
- Keep external service health separate from cache-backed acceptance.
- Do not stage or commit unrelated user files.

---

### Task 1: Script-recorded execution evidence

**Files:**
- Create: `src/starskill/evaluation/runner.py`
- Modify: `scripts/evaluate_starskill.py`
- Test: `tests/test_evaluation_runner.py`

**Interfaces:**
- Produces: `execute_case(case_path: Path, run_dir: Path, python_executable: Path, target_cache_dir: Path, image_cache_dir: Path) -> ExecutionRecord`
- Produces: `execution.json`, `stdout.txt`, `stderr.txt`, `exit_code.txt`, `case.json`, `task.json` in `run_dir`.
- Consumes: immutable `EvaluationCase` manifests loaded by `load_case`.

- [x] **Step 1: Write the failing runner test**

```python
def test_execute_records_the_real_validate_process(tmp_path: Path) -> None:
    record = execute_case(
        PROJECT_ROOT / "evaluation/cases/failures/failure-invalid-timezone.json",
        tmp_path / "run",
        Path(sys.executable),
        tmp_path / "target-cache",
        tmp_path / "image-cache",
    )
    assert record.return_code == 2
    assert record.command_argv[-2:] == ["validate", str((tmp_path / "run/task.json").resolve())]
    assert (tmp_path / "run/execution.json").is_file()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest -q tests/test_evaluation_runner.py::test_execute_records_the_real_validate_process`

Expected: FAIL because `starskill.evaluation.runner` does not exist.

- [x] **Step 3: Implement the minimal runner and `execute` CLI command**

```python
completed = subprocess.run(command_argv, cwd=project_root, text=True, capture_output=True, check=False)
(run_dir / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
(run_dir / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
(run_dir / "exit_code.txt").write_text(f"{completed.returncode}\n", encoding="utf-8")
```

- [x] **Step 4: Run the focused runner tests**

Run: `./.venv/bin/pytest -q tests/test_evaluation_runner.py`

Expected: PASS.

### Task 2: Replay only generated execution evidence

**Files:**
- Modify: `src/starskill/evaluation/reporting.py`
- Modify: `scripts/evaluate_starskill.py`
- Modify: `tests/test_evaluation_replay.py`
- Modify: `tests/test_evaluation_cli.py`

**Interfaces:**
- Consumes: `execution.json` emitted by Task 1.
- Produces: replay reports that use the recorded command, exit code, stdout, and stderr.

- [x] **Step 1: Write a failing replay test**

```python
def test_replay_rejects_execution_record_with_a_tampered_command(tmp_path: Path) -> None:
    run_dir = _captured_invalid_timezone_run(tmp_path)
    payload = json.loads((run_dir / "execution.json").read_text())
    payload["command_argv"][3] = "run"
    (run_dir / "execution.json").write_text(json.dumps(payload))
    assert main(["replay", "--case", str(CASE), "--run-dir", str(run_dir), ...]) == 1
```

- [x] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/pytest -q tests/test_evaluation_replay.py::test_replay_rejects_execution_record_with_a_tampered_command`

Expected: FAIL because replay still reads `tool_calls.jsonl`.

- [x] **Step 3: Replace Worker evidence fields with a validated `execution_file` field**

```python
raw = load_execution_record(case, run_dir)
if raw.command_argv != build_case_command(case, run_dir, ...):
    raise ReportError("invalid_execution_evidence", "recorded command does not match the case")
```

- [x] **Step 4: Run runner and replay tests**

Run: `./.venv/bin/pytest -q tests/test_evaluation_runner.py tests/test_evaluation_replay.py tests/test_evaluation_cli.py`

Expected: PASS.

### Task 3: Competition-sized matrix and self-contained fixtures

**Files:**
- Modify: `src/starskill/evaluation/scoring.py`
- Modify: `src/starskill/evaluation/reporting.py`
- Modify: `tests/fixtures/evaluation/replay_fixtures.py`
- Modify: `tests/test_evaluation_scoring.py`
- Modify: `tests/test_evaluation_reporting.py`

**Interfaces:**
- Requires exactly one recorded run per core and variant case during aggregation.
- Allows a machine-only runtime score; optional human review may add usability and safety points but is not a pass prerequisite.
- Keeps failure/open cases out of the release matrix.

- [x] **Step 1: Write failing tests for one-run core acceptance and review-optional scoring**

```python
def test_machine_only_core_run_is_accepted() -> None:
    report = score_case(passing_machine("core-m42"), None, {})
    assert report.hard_gate_passed is True

def test_case_matrix_requires_one_core_run() -> None:
    assert collect_score_reports(score_root, cases_root=cases_root)
```

- [x] **Step 2: Run those tests to verify failure**

Run: `./.venv/bin/pytest -q tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py`

Expected: FAIL because review is mandatory and aggregation requires three core runs.

- [x] **Step 3: Implement machine-only runtime scoring and one-run matrix validation**

```python
if review is None:
    reviewer_safety = 0.0
    role_usability = 0.0
else:
    reviewer_safety = review.safety_review_points
    role_usability = review.role_usability_points
```

- [x] **Step 4: Replace ignored historical run dependencies in fixture helpers with generated deterministic fixture content**

```python
def write_core_m42_bundle(run_dir: Path) -> None:
    # Write only values and artifact hashes required by the case contract.
```

- [x] **Step 5: Run the affected tests**

Run: `./.venv/bin/pytest -q tests/test_evaluation_scoring.py tests/test_evaluation_reporting.py tests/test_cli.py tests/test_observation_planner.py`

Expected: PASS.

### Task 4: Publishable documentation and live acceptance evidence

**Files:**
- Modify: `evaluation/README.md`
- Modify: `skills/run-starskill/SKILL.md`
- Modify: `skills/run-starskill/references/cli-contract.md`
- Modify: `docs/starskill-evaluation/design/2026-07-20-starskill-agent-evaluation-design.md`
- Modify: `README.md`
- Create: `evaluation/reports/acceptance-2026-07-23.md`

**Interfaces:**
- Documents `execute`, `replay`, and `aggregate` commands.
- States that `execution.json` is script-generated process evidence, while Codex-native tool history remains external platform evidence.

- [x] **Step 1: Update docs to remove Worker-authored `tool_calls.jsonl`**

```text
python scripts/evaluate_starskill.py execute --case <case.json> --run-dir <fresh-dir>
python scripts/evaluate_starskill.py replay --case <case.json> --run-dir <fresh-dir> --output-dir <score-dir>
```

- [x] **Step 2: Execute the three core and six variant cases into a fresh ignored directory**

Run: `python scripts/evaluate_starskill.py execute ...` once for each required manifest, followed by `replay` and `aggregate`.

Expected: recorded `execution.json` files and an aggregate report with all required cases passing.

- [x] **Step 3: Write the dated acceptance note from the observed aggregate results**

Run: `./.venv/bin/python -m pytest -q`

Expected: full suite passes before commit.

- [x] **Step 4: Commit and push only evaluation implementation, fixtures, docs, and tests**

Completed with a 9/9 recorded runtime pass on 2026-07-23. The final evidence is ignored under `evaluation-runs/acceptance-2026-07-23-final/`; the tracked summary is `evaluation/reports/acceptance-2026-07-23.md`.

Run: `git add ... && git commit -m "feat: automate recorded runtime acceptance" && git push origin main`

Expected: remote `main` contains the verified acceptance update.
