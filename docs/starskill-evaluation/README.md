# StarSkill Agent Evaluation Documentation

This folder is the consolidated, user-facing documentation for the StarSkill astronomy Agent evaluation work.

## Contents

- `design/`: product requirements, evaluation model, case matrix, scoring rules, acceptance thresholds, and the implementation plan.
- `fix-briefs/`: review-driven repair requirements issued to implementation Agents. The numbered versions are successive review waves; later versions supersede earlier ones where they overlap.
- `review-history/`: whole-branch review packages, recheck reports, and implementation reports. These record why fixes were requested and how they were verified.

## Runtime boundary

可执行评测实现仍位于 `src/starskill/evaluation/` 和 `scripts/evaluate_starskill.py`。固定案例、
Worker/Reviewer 提示词和报告指南仍位于 `evaluation/`，因为 CLI 和测试将这些路径视为契约。
Phase 3 的 persona 任务生成和 Phase 4 的 provider-neutral self-play 数据导出也复用该实现，
详细用法见 [`../persona-evaluation.md`](../persona-evaluation.md)。

The internal SDD progress ledger and per-task working artifacts remain in `.superpowers/sdd/`; they are process records rather than product documentation.

## Reading order

1. Read the design document in `design/`.
2. Read the implementation plan in `design/` if you need the task breakdown.
3. Read the latest v6 recheck in `review-history/` for the final quality verdict.
4. Use the runtime files under `evaluation/` and `src/starskill/evaluation/` to run or extend the evaluator.
