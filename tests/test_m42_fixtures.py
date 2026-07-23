from starskill.schemas import EphemerisResult, ResolvedTarget
from tests.fixtures.m42 import make_m42_ephemeris, write_m42_target


def test_m42_fixture_writes_a_valid_target_and_builds_its_ephemeris(tmp_path) -> None:
    target_path = tmp_path / "target_resolved.json"

    write_m42_target(target_path)
    ephemeris = make_m42_ephemeris()

    target = ResolvedTarget.model_validate_json(target_path.read_text(encoding="utf-8"))
    assert target.canonical_name == "M 42"
    assert len(EphemerisResult.model_validate(ephemeris.model_dump(mode="json")).samples) == 49
