import json
from pathlib import Path

from starskill.schemas import ObservationTask


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_m42_beijing_example_matches_input_schema() -> None:
    input_path = PROJECT_ROOT / "examples" / "observation_m42_beijing.json"
    assert input_path.exists(), "documented M42 example is missing"
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    task = ObservationTask.model_validate(payload)

    assert task.target == "M42"
    assert task.observer.timezone == "Asia/Shanghai"
