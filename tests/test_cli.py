import csv
import json
import os
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

import starskill.cli as cli
from starskill.cli import main
from tests.fixtures.m42 import write_m42_ephemeris, write_m42_target


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def source_checkout_environment() -> dict[str, str]:
    """Make the source package importable to the real child CLI process."""
    environment = os.environ.copy()
    source_path = str(PROJECT_ROOT / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, existing_pythonpath) if path
    )
    return environment


class CliSimbadBackend:
    service_url = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"

    def query_object(self, query_name: str) -> dict:
        return {
            "canonical_name": "M 42",
            "ra_deg": 83.822083,
            "dec_deg": -5.391111,
            "object_type": "HII",
            "aliases": ["M 42", "NGC 1976", "Orion Nebula"],
        }


class CliEmptySimbadBackend:
    service_url = CliSimbadBackend.service_url

    def query_object(self, query_name: str) -> None:
        return None


class CliFailingSimbadBackend:
    service_url = CliSimbadBackend.service_url

    def query_object(self, query_name: str) -> dict:
        raise TimeoutError("SIMBAD request timed out")


class CliImageBackend:
    def fetch(self, url: str, *, timeout_seconds: int, max_bytes: int) -> tuple[bytes, str]:
        image = Image.new("RGB", (512, 512), "#101820")
        draw = ImageDraw.Draw(image)
        draw.ellipse((100, 80, 410, 430), fill="#d9e5f2")
        output = BytesIO()
        image.save(output, format="JPEG", quality=90)
        return output.getvalue(), "image/jpeg"


def test_validate_command_prints_canonical_task(tmp_path, capsys) -> None:
    input_path = tmp_path / "task.json"
    input_path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )

    exit_code = main(["validate", str(input_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["valid"] is True
    assert output["task"]["target"] == "M42"
    assert output["task"]["interval_minutes"] == 10


def test_validate_command_returns_structured_validation_errors(
    tmp_path, capsys
) -> None:
    input_path = tmp_path / "invalid-task.json"
    input_path.write_text(
        json.dumps(
            {
                "task_type": "observation_plan",
                "target": "M42",
                "observer": {
                    "location_name": "Beijing",
                    "longitude": 116.4074,
                    "latitude": 39.9042,
                    "timezone": "Mars/Olympus_Mons",
                },
                "time_range": {
                    "start": "2026-01-10 18:00:00",
                    "end": "2026-01-11 02:00:00",
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["validate", str(input_path)])
    captured = capsys.readouterr()
    output = json.loads(captured.err)

    assert exit_code == 2
    assert output["valid"] is False
    assert output["error"] == "validation_error"
    assert output["details"][0]["location"] == ["observer", "timezone"]


def test_python_module_entrypoint_validates_documented_example() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "starskill",
            "validate",
            "examples/observation_m42_beijing.json",
        ],
        cwd=PROJECT_ROOT,
        env=source_checkout_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid"] is True


def test_module_help_lists_resolve_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "starskill", "--help"],
        cwd=PROJECT_ROOT,
        env=source_checkout_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "resolve" in result.stdout


def test_module_help_lists_ephemeris_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "starskill", "--help"],
        cwd=PROJECT_ROOT,
        env=source_checkout_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "ephemeris" in result.stdout


def test_ephemeris_command_writes_csv_and_json(tmp_path, capsys) -> None:
    csv_path = tmp_path / "day3" / "intermediate" / "ephemeris.csv"
    json_path = tmp_path / "day3" / "intermediate" / "ephemeris.json"
    target_path = tmp_path / "day2" / "intermediate" / "target_resolved.json"
    write_m42_target(target_path)

    exit_code = main(
        [
            "ephemeris",
            str(PROJECT_ROOT / "examples/observation_m42_beijing.json"),
            "--target-file",
            str(target_path),
            "--output",
            str(csv_path),
            "--metadata",
            str(json_path),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["calculated"] is True
    assert summary["sample_count"] == 49
    assert len(rows) == 49
    assert len(metadata["samples"]) == 49


def test_module_help_lists_plan_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "starskill", "--help"],
        cwd=PROJECT_ROOT,
        env=source_checkout_environment(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "plan" in result.stdout


def test_plan_command_writes_visibility_result_and_figure(tmp_path, capsys) -> None:
    csv_path = tmp_path / "day4" / "intermediate" / "visibility.csv"
    json_path = tmp_path / "day4" / "result.json"
    figure_path = tmp_path / "day4" / "figures" / "visibility_curve.png"
    ephemeris_path = tmp_path / "day3" / "intermediate" / "ephemeris.json"
    write_m42_ephemeris(ephemeris_path)

    exit_code = main(
        [
            "plan",
            str(ephemeris_path),
            "--output",
            str(csv_path),
            "--metadata",
            str(json_path),
            "--figure",
            str(figure_path),
            "--min-target-altitude-deg",
            "30",
            "--max-sun-altitude-deg",
            "-12",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    metadata = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["planned"] is True
    assert summary["sample_count"] == 49
    assert summary["window_count"] == 1
    assert csv_path.is_file()
    assert figure_path.is_file()
    assert len(metadata["windows"]) == 1


def test_plan_command_rejects_invalid_threshold_without_outputs(
    tmp_path, capsys
) -> None:
    csv_path = tmp_path / "visibility.csv"
    json_path = tmp_path / "result.json"
    figure_path = tmp_path / "visibility.png"
    ephemeris_path = tmp_path / "day3" / "intermediate" / "ephemeris.json"
    write_m42_ephemeris(ephemeris_path)

    try:
        exit_code = main(
            [
                "plan",
                str(ephemeris_path),
                "--output",
                str(csv_path),
                "--metadata",
                str(json_path),
                "--figure",
                str(figure_path),
                "--min-target-altitude-deg",
                "100",
            ]
        )
    except ValidationError:
        pytest.fail("plan command leaked a Pydantic ValidationError")

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert error["error"] == "validation_error"
    assert error["details"][0]["location"] == ["min_target_altitude_deg"]
    assert not csv_path.exists()
    assert not json_path.exists()
    assert not figure_path.exists()


def test_run_command_executes_complete_pipeline(tmp_path, capsys, monkeypatch) -> None:
    assert hasattr(cli, "run_pipeline"), "CLI pipeline runner is missing"
    monkeypatch.setattr(cli, "SimbadBackend", CliSimbadBackend)
    output_dir = tmp_path / "complete-run"

    exit_code = main(
        [
            "run",
            str(PROJECT_ROOT / "examples/observation_m42_beijing.json"),
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["status"] == "success"
    assert manifest["status"] == "success"
    assert (output_dir / "result.json").is_file()
    assert (output_dir / "report.md").is_file()
    assert (output_dir / "review_checklist.md").is_file()


def test_run_command_returns_service_error_and_failed_manifest(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "SimbadBackend", CliFailingSimbadBackend)
    output_dir = tmp_path / "failed-run"

    exit_code = main(
        [
            "run",
            str(PROJECT_ROOT / "examples/observation_m42_beijing.json"),
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )

    error = json.loads(capsys.readouterr().err)
    manifest = json.loads((output_dir / "run.json").read_text(encoding="utf-8"))
    assert exit_code == 4
    assert error["error"] == "target_service_error"
    assert manifest["status"] == "failed"
    assert not (output_dir / "result.json").exists()


def test_relationship_command_writes_csv_and_json(tmp_path, capsys) -> None:
    input_path = tmp_path / "relationship-task.json"
    input_path.write_text(
        json.dumps(
            {
                "task_type": "solar_system_relationship",
                "targets": ["moon", "jupiter"],
                "observer": {
                    "location_name": "Shanghai",
                    "longitude": 121.4737,
                    "latitude": 31.2304,
                    "timezone": "Asia/Shanghai",
                },
                "time_range": {
                    "start": "2026-03-20 19:00:00",
                    "end": "2026-03-20 23:00:00",
                },
                "interval_minutes": 20,
            }
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "relationship.csv"
    json_path = tmp_path / "relationship.json"

    exit_code = main(
        [
            "relationship",
            str(input_path),
            "--output",
            str(csv_path),
            "--metadata",
            str(json_path),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert summary["calculated"] is True
    assert summary["sample_count"] == 13
    assert summary["maximum_separation_deg"] > summary["minimum_separation_deg"]
    assert csv_path.is_file()
    assert len(payload["samples"]) == 13


def test_fetch_image_command_writes_source_display_and_metadata(
    tmp_path, capsys, monkeypatch
) -> None:
    assert hasattr(cli, "UrlImageBackend"), "CLI image backend is missing"
    monkeypatch.setattr(cli, "UrlImageBackend", CliImageBackend)
    request_path = tmp_path / "m51-request.json"
    request_path.write_text(
        json.dumps(
            {
                "target_name": "M51",
                "data_release": "DR18",
                "ra_deg": 202.4696,
                "dec_deg": 47.1952,
                "scale_arcsec_per_pixel": 0.396,
                "width": 512,
                "height": 512,
                "timeout_seconds": 30,
                "max_bytes": 5000000,
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "m51-run"

    exit_code = main(
        [
            "fetch-image",
            str(request_path),
            "--output-dir",
            str(output_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    metadata = json.loads(
        (output_dir / "image_metadata.json").read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert summary["downloaded"] is True
    assert summary["from_cache"] is False
    assert (output_dir / "data/m51_sdss.jpg").is_file()
    assert (output_dir / "figures/m51_display.png").is_file()
    assert metadata["source"]["database"] == "SDSS SkyServer"


def test_resolve_command_prints_structured_target(
    tmp_path, capsys, monkeypatch
) -> None:
    assert hasattr(cli, "SimbadBackend"), "CLI SIMBAD backend is missing"
    monkeypatch.setattr(cli, "SimbadBackend", CliSimbadBackend)
    output_path = tmp_path / "run" / "intermediate" / "target_resolved.json"

    try:
        exit_code = main(
            [
                "resolve",
                "猎户座大星云",
                "--cache-dir",
                str(tmp_path / "cache"),
                "--output",
                str(output_path),
            ]
        )
    except SystemExit:
        pytest.fail("resolve command does not accept --output")
    output = json.loads(capsys.readouterr().out)
    written = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output["resolved"] is True
    assert output["target"]["query_name"] == "M 42"
    assert output["target"]["canonical_name"] == "M 42"
    assert output["target"]["coordinate_frame"] == "ICRS"
    assert written["canonical_name"] == "M 42"
    assert written["source"]["database"] == "SIMBAD"


def test_resolve_command_returns_structured_not_found_error(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "SimbadBackend", CliEmptySimbadBackend)

    try:
        exit_code = main(
            ["resolve", "Unknown Object", "--cache-dir", str(tmp_path)]
        )
    except Exception as exc:
        pytest.fail(f"CLI leaked {type(exc).__name__} instead of structured JSON")
    output = json.loads(capsys.readouterr().err)

    assert exit_code == 3
    assert output["resolved"] is False
    assert output["error"] == "target_not_found"


def test_resolve_command_returns_structured_invalid_name_error(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "SimbadBackend", CliSimbadBackend)

    try:
        exit_code = main(
            ["resolve", "M42; SELECT *", "--cache-dir", str(tmp_path)]
        )
    except Exception as exc:
        pytest.fail(f"CLI leaked {type(exc).__name__} instead of structured JSON")
    output = json.loads(capsys.readouterr().err)

    assert exit_code == 2
    assert output["resolved"] is False
    assert output["error"] == "invalid_target_name"


def test_resolve_command_returns_structured_service_error(
    tmp_path, capsys, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "SimbadBackend", CliFailingSimbadBackend)

    try:
        exit_code = main(["resolve", "M42", "--cache-dir", str(tmp_path)])
    except Exception as exc:
        pytest.fail(f"CLI leaked {type(exc).__name__} instead of structured JSON")
    output = json.loads(capsys.readouterr().err)

    assert exit_code == 4
    assert output["resolved"] is False
    assert output["error"] == "target_service_error"
