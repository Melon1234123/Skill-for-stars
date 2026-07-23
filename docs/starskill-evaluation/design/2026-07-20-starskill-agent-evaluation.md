# Superseded Evaluation Implementation Plan

The 2026-07-20 implementation plan relied on repeated external Workers, Worker-authored `tool_calls.jsonl`, and mandatory reviewer orchestration. It is retained only as a historical pointer and must not be used as the current evaluation protocol.

Use [Recorded Runtime Acceptance](2026-07-23-recorded-runtime-acceptance.md), [`evaluation/README.md`](../../../evaluation/README.md), and the `acceptance` command instead. The active protocol records real repository-script subprocess execution in `execution.json` and requires one run for every core and variant case.
