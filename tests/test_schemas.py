from copy import deepcopy
from datetime import datetime

import pytest
from pydantic import ValidationError

from starskill.schemas import ObservationTask


@pytest.fixture
def valid_payload() -> dict:
    return {
        "task_type": "observation_plan",
        "target": "M42",
        "observer": {
            "location_name": "Beijing",
            "longitude": 116.4074,
            "latitude": 39.9042,
            "timezone": "Asia/Shanghai",
        },
        "time_range": {
            "start": "2026-01-10 18:00:00",
            "end": "2026-01-11 02:00:00",
        },
    }


def test_valid_observation_task_uses_documented_defaults(valid_payload: dict) -> None:
    task = ObservationTask.model_validate(valid_payload)

    assert task.target == "M42"
    assert task.interval_minutes == 10
    assert task.time_range.start == datetime(2026, 1, 10, 18, 0)
    assert task.output.language == "zh-CN"
    assert task.output.formats == ["json", "csv", "png", "md"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("longitude", 181),
        ("longitude", -181),
        ("latitude", 91),
        ("latitude", -91),
    ],
)
def test_observer_rejects_coordinates_outside_earth_bounds(
    valid_payload: dict, field: str, value: float
) -> None:
    payload = deepcopy(valid_payload)
    payload["observer"][field] = value

    with pytest.raises(ValidationError):
        ObservationTask.model_validate(payload)


def test_observer_rejects_unknown_timezone(valid_payload: dict) -> None:
    payload = deepcopy(valid_payload)
    payload["observer"]["timezone"] = "Mars/Olympus_Mons"

    with pytest.raises(ValidationError, match="timezone"):
        ObservationTask.model_validate(payload)


def test_time_range_requires_end_after_start(valid_payload: dict) -> None:
    payload = deepcopy(valid_payload)
    payload["time_range"]["end"] = payload["time_range"]["start"]

    with pytest.raises(ValidationError, match="end"):
        ObservationTask.model_validate(payload)


def test_target_must_not_be_blank(valid_payload: dict) -> None:
    payload = deepcopy(valid_payload)
    payload["target"] = "   "

    with pytest.raises(ValidationError, match="target"):
        ObservationTask.model_validate(payload)


def test_task_type_only_accepts_observation_plan(valid_payload: dict) -> None:
    payload = deepcopy(valid_payload)
    payload["task_type"] = "horoscope"

    with pytest.raises(ValidationError, match="task_type"):
        ObservationTask.model_validate(payload)


@pytest.mark.parametrize("interval", [0, 121])
def test_interval_must_stay_within_supported_range(
    valid_payload: dict, interval: int
) -> None:
    payload = deepcopy(valid_payload)
    payload["interval_minutes"] = interval

    with pytest.raises(ValidationError, match="interval_minutes"):
        ObservationTask.model_validate(payload)


def test_unknown_input_fields_are_rejected(valid_payload: dict) -> None:
    payload = deepcopy(valid_payload)
    payload["targte"] = "M51"

    with pytest.raises(ValidationError, match="targte"):
        ObservationTask.model_validate(payload)
