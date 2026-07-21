# Evaluation reports

Store fresh replay aggregate outputs and acceptance notes for Task 6 under this directory.

- Put replay aggregates under run-specific subdirectories instead of overwriting prior evidence.
- Keep live smoke outputs under `evaluation-runs/live/`.
- Keep agent replay outputs under `evaluation-runs/scores/` and summaries here only after a fresh run.
- Do not commit large transient `evaluation-runs/` trees unless a small deterministic fixture is intentionally copied into `tests/fixtures/evaluation/`.
