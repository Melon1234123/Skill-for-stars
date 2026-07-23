from datetime import datetime, timezone
from pathlib import Path

from starskill.schemas import Observer


FIXTURE = Path(__file__).parent / "fixtures" / "black_marble_snapshot.json"


def fixed_clock() -> datetime:
    return datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def make_observer(longitude: float = 116.4, latitude: float = 39.9) -> Observer:
    return Observer(
        location_name="Beijing",
        longitude=longitude,
        latitude=latitude,
        timezone="Asia/Shanghai",
    )


def test_black_marble_provider_uses_the_nearest_snapshot_cell() -> None:
    from starskill.light_pollution import BlackMarbleLightPollutionProvider

    result = BlackMarbleLightPollutionProvider(
        snapshot_path=FIXTURE, clock=fixed_clock
    ).lookup(make_observer(116.4, 39.9))

    assert (result.radiance, result.dataset_id, result.interpolation) == (
        18.5,
        "VNP46A4",
        "nearest_snapshot_cell",
    )
    assert result.source.provider == "NASA Black Marble"
    assert result.source.source_url == "https://blackmarble.gsfc.nasa.gov/"
    assert result.source.accessed_at == fixed_clock()
    assert result.source.from_cache is False
    assert result.source.availability == "fresh"


def test_missing_snapshot_is_unavailable(tmp_path: Path) -> None:
    from starskill.light_pollution import BlackMarbleLightPollutionProvider

    result = BlackMarbleLightPollutionProvider(
        snapshot_path=tmp_path / "missing.json", clock=fixed_clock
    ).lookup(make_observer())

    assert result.radiance is None
    assert result.source.provider == "NASA Black Marble"
    assert result.source.source_url == "https://blackmarble.gsfc.nasa.gov/"
    assert result.source.accessed_at == fixed_clock()
    assert result.source.from_cache is False
    assert result.source.availability == "unavailable"
    assert result.source.issue_code == "light_pollution_snapshot_unavailable"


def test_malformed_snapshot_is_unavailable(tmp_path: Path) -> None:
    from starskill.light_pollution import BlackMarbleLightPollutionProvider

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")

    result = BlackMarbleLightPollutionProvider(
        snapshot_path=snapshot, clock=fixed_clock
    ).lookup(make_observer())

    assert result.radiance is None
    assert result.source.availability == "unavailable"
    assert result.source.issue_code == "light_pollution_snapshot_invalid"
