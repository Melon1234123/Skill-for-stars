# Evaluation reports

Store dated recorded-runtime aggregate notes under this directory.

- Put replay aggregates under run-specific subdirectories instead of overwriting prior evidence.
- Keep live smoke outputs under `evaluation-runs/live/`.
- Keep script-recorded replay outputs under `evaluation-runs/` and summaries here only after a fresh run.
- Do not commit large transient `evaluation-runs/` trees unless a small deterministic fixture is intentionally copied into `tests/fixtures/evaluation/`.
