"""The Python-TypeScript contract, Python side (test-plan B-09: CT-01, CT-02, CT-04, CT-06).

tests/fixtures/contract/synth2099 is a synthetic storm written by the real exporter (tests/fixtures/make_app_fixture.py,
importable here because tests/conftest.py puts tests/fixtures on sys.path). It is regenerated into tmp_path and must be
byte-identical to the committed copy, so a change to what the pipeline writes shows up as a reviewed diff of the
fixture, and app/src/data/contract.test.ts parses the same committed bytes.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import make_app_fixture as fixture
import pytest

from blackout import export

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "tests/fixtures/contract"
FOLDER = CONTRACT / fixture.STORM.id
APP_FIXTURES = REPO / "app/src/__fixtures__"
TOY = REPO / "tests/fixtures/exposure_toy.json"
SCHEMA = json.loads((REPO / "schema/export.schema.json").read_text(encoding="utf-8"))
CASES = json.loads((CONTRACT / "cases.json").read_text(encoding="utf-8"))["cases"]
REGENERATE = "regenerate with: uv run python -I tests/fixtures/make_app_fixture.py"
MAX_BYTES = 300_000  # commit-sized


def read_strict(path: Path):
    """A browser's JSON.parse rejects a bare NaN or Infinity, so this reader does too."""
    def refuse(token: str):
        raise ValueError(f"{path.name} holds a bare {token}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=refuse)


def validate(kind: str, instance) -> None:
    schema = {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{kind}"}
    jsonschema.Draft202012Validator(schema).validate(instance)


def by_night(nights: dict) -> dict[str, dict[str, dict]]:
    return {fips: {entry["night"]: entry for entry in entries} for fips, entries in nights.items()}


# --- CT-02: the committed fixture is what the exporter writes today -------------------------------------------------

def test_fixture_export_is_current(tmp_path):
    fresh = fixture.generate(tmp_path / "contract")

    assert fresh == tmp_path / "contract" / fixture.STORM.id
    assert fixture.differences(CONTRACT, tmp_path / "contract") == [], REGENERATE


def test_fixture_builder_is_deterministic(tmp_path):
    fixture.generate(tmp_path / "first")
    fixture.generate(tmp_path / "second")

    assert fixture.differences(tmp_path / "first", tmp_path / "second") == []
    assert sorted(fixture.fixture_files(tmp_path / "first")) == [
        "index.json", *(f"{fixture.STORM.id}/{name}" for name in sorted([*export.STORM_FILES, fixture.EXPECTED_FILE]))]


def test_fixture_check_mode_reports_a_stale_copy(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixture, "OUT", CONTRACT)
    assert fixture.main(["--check"]) == 0
    stale = tmp_path / "stale"
    fixture.generate(stale)
    (stale / fixture.STORM.id / "claims.json").write_text("[]\n", encoding="utf-8")
    monkeypatch.setattr(fixture, "OUT", stale)
    assert fixture.main(["--check"]) == 1
    assert "claims.json" in capsys.readouterr().err


# --- CT-01: every fixture validates against the schema -----------------------------------------------------------

def test_contract_fixture_validates_and_verifies():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    for name, kind in export.STORM_FILES.items():
        validate(kind, read_strict(FOLDER / name))
    validate("index", read_strict(CONTRACT / "index.json"))

    counts = export.verify_export(FOLDER)

    assert counts["counties"] == 6 and counts["nights"] == 10 and counts["county_nights"] == 60
    # 38 seen county-nights (Alpha 10, Bravo 8, Echo 10, Foxtrot 10) less the one night the fit left blank
    assert counts["estimates"] == 37 and counts["unseen"] == 22 and counts["claims"] == 200
    assert sum(len(data) for data in fixture.fixture_files(CONTRACT).values()) < MAX_BYTES


def test_app_unit_fixtures_validate_against_the_schema():
    """app/src/__fixtures__ is hand-written for the loader tests; it must still be a document the pipeline could write."""
    validate("index", read_strict(APP_FIXTURES / "index.json"))
    folders = [path for path in APP_FIXTURES.iterdir() if path.is_dir()]
    assert folders
    for folder in folders:
        for name, kind in export.STORM_FILES.items():
            validate(kind, read_strict(folder / name))


def test_committed_sample_export_verifies():
    """The committed Ian sample under app/public/data is what a fresh clone demos and what the browser tests serve;
    it must read back whole. The eleven full-storm exports beside it take about 10 s to validate and are checked by
    `blackout export` itself (write_export verifies what it writes), so they stay out of the unit suite."""
    folder = export.APP_DATA / export.SAMPLE_ID
    assert folder.is_dir(), f"{folder} is committed (test-plan D-9); restore it with git"

    counts = export.verify_export(folder)

    assert counts["counties"] == 3 and counts["claims"] > 0
    assert counts["estimates"] > 0 and counts["estimates"] + counts["unseen"] <= counts["county_nights"]


def test_fixture_covers_every_status_and_the_allowed_nulls():
    """The fixture is only worth pinning if it exercises the contract's edges; this keeps a regeneration honest."""
    meta = read_strict(FOLDER / "meta.json")
    nights = by_night(read_strict(FOLDER / "nights.json"))
    restoration = read_strict(FOLDER / "restoration.json")
    exposure = read_strict(FOLDER / "exposure.json")
    counties = {f["properties"]["fips"]: f for f in read_strict(FOLDER / "counties.geojson")["features"]}
    states = read_strict(FOLDER / "states.geojson")["features"]
    scorecard = read_strict(FOLDER / "scorecard.json")

    assert meta["id"] == "synth2099" and meta["generated"] == "2099-09-20T00:00:00+00:00"
    assert {e["status"] for c in nights.values() for e in c.values()} == set(export.STATUSES)
    blank = nights["99003"]["2099-09-14"]
    assert blank["status"] == "ok" and blank["est"] is None  # a visible night the fit left blank
    assert nights["99011"]["2099-09-13"]["official"] is None  # EAGLE-I gap
    assert nights["99003"]["2099-09-10"]["official"] is None  # over-count, shown as null
    assert nights["99003"]["2099-09-11"]["official"] == 1.0  # slightly above 100%, clipped by the rule
    folded = nights["99001"]["2099-09-12"]
    assert folded["lo"] == folded["est"] == 0.4 < folded["hi"]  # the range was above its point; the point is folded in
    assert all(e["est"] is None for e in nights["99007"].values())  # never seen
    assert counties["99005"]["properties"]["customers"] is None
    assert counties["99011"]["geometry"]["type"] == "MultiPolygon"
    assert sorted(f["properties"]["state"] for f in states) == ["ZA", "ZB"]
    assert {f["properties"]["state"]: f["geometry"]["type"] for f in states}["ZB"] == "MultiPolygon"
    assert restoration["99011"]["est_hi"] is None and restoration["99011"]["est_lo"] == 7.0  # never back
    assert restoration["99011"]["official_day"] is None
    assert restoration["99005"] == {"est_lo": None, "est_hi": None, "official_day": None}
    assert restoration["99009"] == {"est_lo": 0.0, "est_hi": 0.0, "official_day": 0.0}  # never out
    assert exposure["99005"]["at"] == exposure["99007"]["at"] == {"24": None, "48": None, "72": None}
    assert exposure["99001"]["at"]["24"] == [0.01, 0.85]
    assert sorted(scorecard["methods"]) == ["hybrid", "isotonic", "nothing", "wind_only", "wind_timing"]
    assert scorecard["methods"]["nothing"]["false_alarm_50"] is None and scorecard["methods"]["hybrid"]["mae_pp"] == 9.0
    claims = read_strict(FOLDER / "claims.json")
    assert {c["fips"] for c in claims} == {"99001", "99003", "99007"}  # only where EAGLE-I showed an outage


# --- CT-06: the exposure twins ---------------------------------------------------------------------------------------

def test_fixture_exposure_matches_the_python_twin():
    exposure = read_strict(FOLDER / "exposure.json")
    expected = read_strict(FOLDER / fixture.EXPECTED_FILE)

    assert sorted(expected) == ["24", "48", "72"]
    for hours in export.WAITING_PERIODS:
        assert export.expected_policies_out(exposure, hours) == pytest.approx(expected[str(hours)])
    blind = sum(exposure[f]["home"] + exposure[f]["business"] for f in ("99005", "99007"))
    assert expected["72"]["unknown_policies"] == blind > 0  # can't see is unknown, never zero


def test_exposure_toy_matches_the_python_twin():
    toy = read_strict(TOY)
    validate("exposure", toy["exposure"])
    for hours in export.WAITING_PERIODS:
        assert export.expected_policies_out(toy["exposure"], hours) == pytest.approx(toy["expected"][str(hours)])


# --- CT-04: documents both validators read ----------------------------------------------------------------------------

def test_shared_cases_are_well_formed():
    ids = [case["id"] for case in CASES]
    assert len(set(ids)) == len(ids)
    for case in CASES:
        assert case["kind"] in {*export.STORM_FILES.values(), "index"}, case["id"]
        verdict = case.get("ts", "same")
        assert verdict in {"same", "lenient", "stricter"}, case["id"]
        if verdict == "lenient":
            assert not case["valid"], f"{case['id']}: lenient means the parser accepts what the schema rejects"
        if verdict == "stricter":
            assert case["valid"], f"{case['id']}: stricter means the parser rejects what the schema accepts"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_schema_verdict_on_shared_case(case):
    if case["valid"]:
        export.check_file(case["kind"], case["document"], case["id"])
    else:
        with pytest.raises(ValueError, match="schema"):
            export.check_file(case["kind"], case["document"], case["id"])


def test_a_range_that_excludes_its_point_is_caught_after_writing():
    """Neither validator reads across fields; verify_export does, so the case the schema accepts still never ships."""
    case = next(c for c in CASES if c["id"] == "nights-range-excludes-point")
    with pytest.raises(export.ExportIntegrityError, match="outside"):
        export.check_nights(case["id"], case["document"], ["2099-09-10"])
