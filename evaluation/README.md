# StarSkill external Agent evaluation protocol

This repository ships prompts, manifests, replay tooling, and scoring logic for an external evaluation harness. It 不创建 Agent, does not create child Agents inside the repository, and does not call an LLM API. Worker and reviewer orchestration must happen outside the repo.

## Script-owned Engineering Acceptance

`python scripts/evaluate_starskill.py acceptance` is a separate release gate. It runs the
three core cases three times each and the ten variants once, then records the actual CLI argv,
copied inputs, stdout, stderr, exit code, and artifact hashes in `execution.json`. Its output
declares `mode: script_owned_engineering_acceptance`.

Script-owned engineering acceptance does not replace external Worker or Reviewer evidence. It
does not create Agents, call an LLM, write `response.md`, or write `tool_calls.jsonl`; a formal
Agent score still requires the external sequence below. Its score bundles set
`evidence_mode: script_owned_engineering`, accept only `execution.json`, and calculate only
machine-check dimensions; reviewer, escalation, and bonus evidence are rejected in this mode.

New script-owned records use execution-record schema v2. They record only the safe
environment evidence needed for replay: `source_path` and an `environment` object containing
only `PYTHONPATH`. Replay requires both `source_path` and the first `PYTHONPATH` component to
resolve to the evaluator's trusted repository `src` directory. Legacy schema v1 records remain
replayable with their original field set; because v1 did not capture source-environment evidence,
replay does not invent or attribute that evidence during compatibility validation.

## Required sequence

1. Load one case manifest.
2. Create a new Worker Agent with only its role prompt and case input.
3. Capture its response, tool calls, stdout, stderr, exit code, and output directory.
4. Repeat the Worker three times for each fixed core case.
5. Run the replay CLI for machine checks.
6. Create one rotating reviewer Agent after all Workers finish.
7. Run replay again with the reviewer JSON.
8. Aggregate score reports and write the summary.

The reviewer rotation is exact and directed:

- teacher reviewer reviews outreach Worker output
- outreach reviewer reviews research Worker output
- research reviewer reviews teacher Worker output

Do not substitute a different reviewer-role mapping. Use the adjudicator prompt only when a normal reviewer reports a critical issue or conflicts with machine checks.

## Directory layout

`evaluation-runs/` is the recommended capture root for external orchestration:

```text
evaluation-runs/
  agents/
    <case-id>/
      <worker-run-id>/
        case.json
        task.json
        response.md
        tool_calls.jsonl
        stdout.txt
        stderr.txt
        exit_code.txt
        ...actual StarSkill output files...
  reviews/
    <case-id>.json
    <case-id>-adjudicator.json
  scores/
    <case-id>/
      <worker-run-id>/
        machine_checks.json
        score.json
        summary.md
  reports/
    aggregate_summary.json
    aggregate_summary.md
```

Each Worker run must use a fresh output directory. Never overwrite a previous run when capturing evidence for replay.

## Worker capture contract

Each Worker receives only:

- the assigned role prompt from `evaluation/prompts/workers/`
- one case manifest
- that case manifest's referenced input JSON
- the shared `skills/run-starskill/references/cli-contract.md`

Every run must preserve real evidence:

- `response.md`
- `tool_calls.jsonl`
- `stdout.txt`
- `stderr.txt`
- `exit_code.txt`
- every actual artifact written by the StarSkill CLI

Do not fabricate coordinates, images, files, provenance, tool traces, success states, or review outcomes. The replay harness inspects actual files and the real exit code.

### `tool_calls.jsonl` execution-record schema

Every nonblank line must be one JSON object with exactly these keys: `tool`, `command`, `case_id`, `case_kind`, `worker_role`, `task_path`, `workflow`, `run_dir`, `output_dir`, `return_code`, `stdout_file`, `stderr_file`, `response_file`, and `result`.

- The record must not include `arguments` or any other key. Set `tool` and `command` to `run-starskill`.
- `case_id`, `case_kind`, `worker_role`, `task_path`, and `workflow` must exactly match the assigned case manifest. `worker_role` is the manifest's canonical role, and `task_path` uses the manifest's absolute path representation.
- `run_dir` and `output_dir` are the same absolute path of the actual run directory. `stdout_file`, `stderr_file`, and `response_file` are absolute paths inside that directory, and `return_code` is the observed exit code.
- `result` is a nested `result` object with exactly `return_code`, `output_dir`, `stdout_file`, `stderr_file`, and `response_file`, repeating the linked top-level values.

## Replay commands

Use the existing CLI exactly as implemented:

```powershell
python scripts/evaluate_starskill.py replay --case evaluation/cases/core/core-m42-beijing.json --run-dir evaluation-runs/agents/core-m42-beijing/teacher-01 --return-code 0 --stdout-file evaluation-runs/agents/core-m42-beijing/teacher-01/stdout.txt --stderr-file evaluation-runs/agents/core-m42-beijing/teacher-01/stderr.txt --review-file evaluation-runs/reviews/core-m42-beijing.json --output-dir evaluation-runs/scores/core-m42-beijing/teacher-01
python scripts/evaluate_starskill.py aggregate --score-root evaluation-runs/scores --output-dir evaluation-runs/reports
```

Run `evaluate_starskill.py replay` once per Worker run. First replay may omit `--review-file` if the rotating reviewer has not run yet. After reviewer JSON exists, run replay again for that same Worker bundle with the reviewer JSON included. Then aggregate all score reports.

## Bonus evidence protocol

A nonzero bonus claim must keep all evidence inside the Worker run directory, unless a `repo:` path explicitly identifies a repository-local file. Every declared path must be readable and non-empty. `evidence_paths` must include the three referenced records below.

- `baseline` and `comparison` each point to a JSON object with exactly `record_type`, `metric`, `unit`, and `value`. `record_type` is `starskill_bonus_measurement`; `metric` and `unit` are non-empty strings; and `value` is a finite number. The records must use the same metric and unit but different values.
- `verification` points to a JSON object with exactly `record_type`, `command`, `exit_code`, and `passed`. `record_type` is `starskill_bonus_verification`; `command` is non-empty; `exit_code` is `0`; and `passed` is `true`.

Descriptions explain a claim but are not evidence. Bare prose, empty files, or unrelated files cannot support bonus points.

## Failure-case exit-code table

The six failure manifests and their expected CLI exit behavior are:

| Case ID | Workflow | Expected exit code | Meaning |
| --- | --- | ---: | --- |
| `failure-invalid-observation-input` | `validate` | 2 | input validation failure |
| `failure-invalid-timezone` | `validate` | 2 | input validation failure |
| `failure-target-service` | `run` | 4 | SIMBAD service failure |
| `failure-no-observation-window` | `run` | 0 | successful run with a no-window result |
| `failure-sdss-service` | `fetch-image` | 7 | public data service failure |
| `failure-sdss-invalid-response` | `fetch-image` | 9 | public response validation failure |

Preserve the structured stderr and the observed exit code exactly. Nonzero exits are not success, and exit code `0` in `failure-no-observation-window` still requires checking the produced status and artifacts.

## Cache mode vs live mode

- Cache or fixture-backed replay mode is the normal acceptance path for deterministic evaluation and scoring.
- Live smoke checks are separate health checks for current SIMBAD or SDSS availability and must not be merged into the deterministic acceptance score.
- A live smoke result may be useful to report operational status, but it does not override replay evidence and does not change whether the Skill passes its repository evaluation threshold.

## Acceptance line

The acceptance line for fixed-case evaluation is:

- 9 independent core Worker runs total: three runs each for the three fixed core cases.
- core average base score at least 80/100.
- per-case population standard deviation at most 5 for each fixed case's three runs.
- variant hard-gate pass rate at least 90%; with ten current variant cases, that means at least 9/10.
- hard-gate failures cannot be repaired by reviewer generosity or bonus points.

Open-task scores are reported separately and do not decide the fixed-case pass line.

## Reviewer and adjudicator contract

Normal reviewers run only after all Worker runs for the assigned case finish. They must emit exactly one `ReviewReport` JSON object, must not override machine evidence, and must flag prohibited claims such as:

- fabricated coordinates, images, provenance, files, or tool calls
- claiming success against the real exit code or missing artifacts
- treating candidate observation windows as weather, site, equipment, or safety guarantees
- treating apparent Moon-Jupiter angular separation as physical distance
- replacing external-provider failures with invented success

Use the adjudicator prompt only when a normal reviewer reports a critical issue or conflicts with machine checks.
