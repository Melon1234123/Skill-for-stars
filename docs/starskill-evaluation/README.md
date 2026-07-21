# StarSkill Agent Evaluation Documentation

This folder is the consolidated, user-facing documentation for the StarSkill astronomy Agent evaluation work.

## Contents

- `design/`: product requirements, evaluation model, case matrix, scoring rules, acceptance thresholds, and the implementation plan.
- `fix-briefs/`: review-driven repair requirements issued to implementation Agents. The numbered versions are successive review waves; later versions supersede earlier ones where they overlap.
- `review-history/`: whole-branch review packages, recheck reports, and implementation reports. These record why fixes were requested and how they were verified.

## Runtime boundary

The executable evaluation implementation remains in `src/starskill/evaluation/` and `scripts/evaluate_starskill.py`. Canonical cases, Worker/Reviewer prompts, and report guidance remain in `evaluation/`. They stay at their current paths because the CLI and tests use those paths as part of their contract.

The internal SDD progress ledger and per-task working artifacts remain in `.superpowers/sdd/`; they are process records rather than product documentation.

## Reading order

1. Read the design document in `design/`.
2. Read the implementation plan in `design/` if you need the task breakdown.
3. Read the latest v6 recheck in `review-history/` for the final quality verdict.
4. Use the runtime files under `evaluation/` and `src/starskill/evaluation/` to run or extend the evaluator.
