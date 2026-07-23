# Superseded External-Agent Evaluation Proposal

The original external-Agent, three-repeat proposal dated 2026-07-20 has been retired because it required Worker-authored tool logs, repeated runs without a practical release benefit, and mandatory cross-review before a runtime result could pass.

The active design is [Recorded Runtime Acceptance](2026-07-23-recorded-runtime-acceptance.md). It uses script-generated `execution.json` records, one fresh run per core and variant case, deterministic replay, and optional rather than mandatory human review.
