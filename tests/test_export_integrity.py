"""The sample is genuine and current, and an export is checked whole after it is written (test-plan B-08: PX-01,
PX-02, RD-35).

The toy world comes from tests/test_export.py (its builders are imported, that file is not changed). The sample tests
read only committed files under data/sample; the two that need data/processed skip where it is absent and are
registered under no marker, so a fresh clone runs the rest.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest
from test_export import STORM, install, read_strict, stand_ins, toy_world

from blackout import export

REPO = Path(__file__).resolve().parents[1]
SAMPLE_TABLE = REPO / "data/sample/county_nights_ian_sample.parquet"
SAMPLE_PREDICTIONS = REPO / "data/sample/predictions_ian_sample.parquet"
SAMPLE_METADATA = REPO / "data/sample/predictions_ian_sample.json"
SOURCE_PREDICTIONS = REPO / "data/processed/predictions_ian2022.parquet"
LOCKBOX_RESULT = REPO / "data/processed/lockbox_result.json"
SCRIPT = REPO / "scripts/make_sample_predictions.py"
SAMPLE_COUNTIES = ["12015", "12021", "12071"]  # Charlotte, Collier, Lee
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_HEAD = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture
def world(tmp_path, monkeypatch):
    toy = toy_world(tmp_path, monkeypatch)
    install(monkeypatch, stand_ins(toy.calls))
    return toy


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite(path: Path, change) -> None:
    """Apply `change` to a written JSON file; the export is then verified again as the app would read it."""
    payload = read_strict(path)
    path.write_text(json.dumps(change(payload)), encoding="utf-8")


def with_est(nights: dict, fips: str, night: str, est: float, lo: float, hi: float) -> dict:
    entries = [dict(e, est=est, lo=lo, hi=hi) if e["night"] == night else e for e in nights[fips]]
    return {**nights, fips: entries}


# --- PX-02: verify_export --------------------------------------------------------------------------------------------

def test_verify_export_counts_a_sound_export(world):
    folder = export.export_storm(STORM.id, out=world.out)

    counts = export.verify_export(folder)

    # 5 counties x 7 exported nights; 12001 and 13005 are seen on all 7, 12003 on 5, the two GA counties never
    assert counts == {"files": 9, "counties": 5, "nights": 7, "county_nights": 35, "estimates": 19, "unseen": 16,
                      "policies": 100_000, "claims": 200}


@pytest.mark.parametrize("name, change", [
    ("nights.json", lambda n: {f: e for f, e in n.items() if f != "12001"}),  # a county without nights
    ("nights.json", lambda n: with_est(n, "12001", "2099-09-12", 0.9, 0.3, 0.5)),  # est above hi
    ("nights.json", lambda n: with_est(n, "12001", "2099-09-12", 0.2, 0.3, 0.5)),  # est below lo
    ("nights.json", lambda n: with_est(n, "12001", "2099-09-12", None, 0.3, 0.5)),  # a range without a point
    ("nights.json", lambda n: with_est(n, "12001", "2099-09-12", None, None, 0.5)),  # half a range, no point
    ("nights.json", lambda n: {**n, "12001": list(reversed(n["12001"]))}),  # nights out of meta's order
    ("nights.json", lambda n: {**n, "12001": n["12001"][1:]}),  # a night missing
    ("restoration.json", lambda r: {**r, "12001": {**r["12001"], "official_day": math.nan}}),  # a bare NaN
    ("exposure.json", lambda x: {**x, "12001": {**x["12001"], "home": x["12001"]["home"] + 1}}),  # not the book
    ("exposure.json", lambda x: {f: e for f, e in x.items() if f != "13005"}),  # a county without exposure
    ("claims.json", lambda c: [{**c[0], "policy_id": "P999999"}, *c[1:]]),  # a policy not in the book
    ("claims.json", lambda c: [{**c[0], "claim_id": c[1]["claim_id"]}, *c[1:]]),  # a repeated claim id
    ("claims.json", lambda c: [{**c[0], "fips": "13005"}, *c[1:]]),  # a county EAGLE-I never showed out
    ("scorecard.json", lambda s: {**s, "storm_id": "zeta2100"}),  # another storm's card
    ("meta.json", lambda m: {**m, "name": "Renamed"}),  # no longer what index.json lists
])
def test_verify_export_refuses_a_broken_file(world, name, change):
    folder = export.export_storm(STORM.id, out=world.out)
    rewrite(folder / name, change)

    with pytest.raises(export.ExportIntegrityError, match=name):
        export.verify_export(folder)


def test_verify_export_refuses_a_missing_file_or_an_index_without_the_storm(world):
    folder = export.export_storm(STORM.id, out=world.out)
    (world.out / "index.json").write_text(json.dumps({"storms": []}), encoding="utf-8")
    with pytest.raises(export.ExportIntegrityError, match="index.json"):
        export.verify_export(folder)

    export.export_storm(STORM.id, out=world.out)  # restores the index
    (folder / "claims.json").unlink()
    with pytest.raises(export.ExportIntegrityError, match="claims.json"):
        export.verify_export(folder)


def test_verify_export_wraps_a_schema_break(world):
    folder = export.export_storm(STORM.id, out=world.out)
    rewrite(folder / "nights.json", lambda n: with_est(n, "12003", "2099-09-10", 0.0, 0.0, 0.0))  # cant_see with 0

    with pytest.raises(export.ExportIntegrityError, match=r"nights\.json.*schema"):
        export.verify_export(folder)


def test_export_verifies_what_it_wrote_and_fails_loudly(world, monkeypatch):
    seen = []
    real = export.verify_export
    monkeypatch.setattr(export, "verify_export", lambda folder: seen.append(folder) or real(folder))
    folder = export.export_storm(STORM.id, out=world.out)
    assert seen == [folder]

    def broken(folder):
        raise export.ExportIntegrityError("broken on purpose")

    monkeypatch.setattr(export, "verify_export", broken)
    with pytest.raises(export.ExportIntegrityError, match="broken on purpose"):
        export.export_storm(STORM.id, out=world.out)


def test_generated_follows_source_date_epoch(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(int(datetime(2099, 9, 1, tzinfo=UTC).timestamp())))
    assert export.generated_stamp() == "2099-09-01T00:00:00+00:00"
    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", export.generated_stamp())
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "yesterday")
    with pytest.raises(ValueError):
        export.generated_stamp()


# --- PX-01: the committed sample -------------------------------------------------------------------------------------

def test_committed_sample_exports_a_usable_demo(tmp_path):
    """The real ranges.py, evaluate.py and model.py on the committed sample: estimates, brackets and claims appear."""
    folder = export.export_sample(out=tmp_path / "data")

    counts = export.verify_export(folder)
    nights = read_strict(folder / "nights.json")
    exposure = read_strict(folder / "exposure.json")

    assert counts["counties"] == 3 and counts["estimates"] > 0 and counts["claims"] > 0
    lee = [e for e in nights["12071"] if e["night"] >= "2022-09-28" and e["est"] is not None]
    assert lee, "Lee has no estimate on any night from landfall on"
    assert any(county["at"]["72"] is not None for county in exposure.values())


def test_sample_predictions_cover_the_sample_table():
    table = pd.read_parquet(SAMPLE_TABLE)
    sample = pd.read_parquet(SAMPLE_PREDICTIONS)

    assert set(zip(sample["fips"], sample["night"])) == set(zip(table["fips"], table["night"]))
    assert sorted(set(sample["fips"])) == SAMPLE_COUNTIES
    assert set(sample["status"]) <= set(export.STATUSES)
    unseen = sample["status"] != "ok"
    assert sample.loc[unseen, ["est", "lo", "hi"]].isna().all().all()  # can't see is never a number
    assert (sample["status"] == "ok").any()


def test_sample_metadata_describes_the_committed_parquet():
    assert SAMPLE_METADATA.exists(), "regenerate the sample locally with scripts/make_sample_predictions.py"
    meta = json.loads(SAMPLE_METADATA.read_text(encoding="utf-8"))
    sample = pd.read_parquet(SAMPLE_PREDICTIONS)

    assert meta["source"] == "data/processed/predictions_ian2022.parquet"
    assert meta["sample"] == "data/sample/predictions_ian_sample.parquet"
    assert SHA256.match(meta["source_sha256"]) and GIT_HEAD.match(meta["lockbox_git_head"])
    assert meta["sample_sha256"] == sha256(SAMPLE_PREDICTIONS)
    assert meta["counties"] == SAMPLE_COUNTIES
    assert meta["rows"] == len(sample)
    assert meta["rows_with_estimate"] == int(sample["est"].notna().sum())
    assert meta["rows_by_status"] == {k: int(v) for k, v in sample["status"].value_counts().sort_index().items()}
    assert meta["lockbox_run_at_utc"].startswith("20")


@pytest.mark.skipif(not SOURCE_PREDICTIONS.exists(), reason="data/processed/predictions_ian2022.parquet is local")
def test_sample_is_cut_from_the_current_processed_predictions():
    """RD-35, local only: the committed rows are exactly the three counties' rows of the final fit's Ian file."""
    meta = json.loads(SAMPLE_METADATA.read_text(encoding="utf-8"))
    source = pd.read_parquet(SOURCE_PREDICTIONS)
    cut = source[source["fips"].isin(SAMPLE_COUNTIES)].reset_index(drop=True)

    assert meta["source_sha256"] == sha256(SOURCE_PREDICTIONS), "stale sample: rerun scripts/make_sample_predictions.py"
    pd.testing.assert_frame_equal(pd.read_parquet(SAMPLE_PREDICTIONS), cut)


@pytest.mark.skipif(not LOCKBOX_RESULT.exists(), reason="data/processed/lockbox_result.json is local")
def test_sample_metadata_names_the_lockbox_run():
    meta = json.loads(SAMPLE_METADATA.read_text(encoding="utf-8"))
    provenance = json.loads(LOCKBOX_RESULT.read_text(encoding="utf-8"))["provenance"]

    assert meta["lockbox_git_head"] == provenance["git_head"]
    assert meta["lockbox_run_at_utc"] == provenance["run_at_utc"]


# --- the script ----------------------------------------------------------------------------------------------------

def load_script():
    spec = importlib.util.spec_from_file_location("make_sample_predictions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_predictions(counties: list[str], nights: list[date]) -> pd.DataFrame:
    rows = [{"storm_id": "ian2022", "fips": f, "night": n, "status": "ok" if k % 2 else "cant_see",
             "est": 0.5 if k % 2 else math.nan, "lo": 0.4 if k % 2 else math.nan, "hi": 0.6 if k % 2 else math.nan}
            for k, (f, n) in enumerate((f, n) for f in counties for n in nights)]
    return pd.DataFrame(rows)


def test_make_sample_predictions_writes_rows_and_metadata(tmp_path):
    script = load_script()
    nights = [date(2022, 9, 26), date(2022, 9, 27), date(2022, 9, 28)]
    repo = tmp_path
    (repo / "data/processed").mkdir(parents=True)
    (repo / "data/sample").mkdir()
    source = repo / "data/processed/predictions_ian2022.parquet"
    fake_predictions([*SAMPLE_COUNTIES, "12001"], nights).to_parquet(source, index=False)
    table = repo / "data/sample/county_nights_ian_sample.parquet"
    fake_predictions(SAMPLE_COUNTIES, nights)[["fips", "night"]].to_parquet(table, index=False)
    lockbox = repo / "data/processed/lockbox_result.json"
    lockbox.write_text(json.dumps({"provenance": {"git_head": "a" * 40, "run_at_utc": "2026-11-09T07:55:07+00:00"}}))
    target = repo / "data/sample/predictions_ian_sample.parquet"

    meta = script.write_sample(source, table, target, lockbox, repo)

    written = pd.read_parquet(target)
    assert sorted(set(written["fips"])) == SAMPLE_COUNTIES and len(written) == 9
    assert meta == json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["source_sha256"] == sha256(source) and meta["sample_sha256"] == sha256(target)
    assert (meta["rows"], meta["rows_with_estimate"], meta["rows_by_status"]) == (9, 4, {"cant_see": 5, "ok": 4})
    assert (meta["lockbox_git_head"], meta["lockbox_run_at_utc"]) == ("a" * 40, "2026-11-09T07:55:07+00:00")
    assert (meta["source"], meta["sample"]) == ("data/processed/predictions_ian2022.parquet",
                                                "data/sample/predictions_ian_sample.parquet")
    # a rerun that changes no row leaves the committed parquet's bytes alone
    before = target.read_bytes()
    script.write_sample(source, table, target, lockbox, repo)
    assert target.read_bytes() == before


def test_make_sample_predictions_refuses_gaps_and_a_missing_lockbox(tmp_path):
    script = load_script()
    nights = [date(2022, 9, 26), date(2022, 9, 27)]
    source, table = tmp_path / "source.parquet", tmp_path / "table.parquet"
    fake_predictions(SAMPLE_COUNTIES[:2], nights).to_parquet(source, index=False)  # Lee has no prediction rows
    fake_predictions(SAMPLE_COUNTIES, nights)[["fips", "night"]].to_parquet(table, index=False)
    lockbox = tmp_path / "lockbox_result.json"
    lockbox.write_text(json.dumps({"provenance": {"git_head": "b" * 40, "run_at_utc": "2026-11-09T00:00:00+00:00"}}))

    with pytest.raises(ValueError, match="county-nights"):
        script.write_sample(source, table, tmp_path / "out.parquet", lockbox, tmp_path)
    assert not (tmp_path / "out.parquet").exists()

    fake_predictions(SAMPLE_COUNTIES, nights).to_parquet(source, index=False)
    with pytest.raises(FileNotFoundError, match="lockbox"):
        script.write_sample(source, table, tmp_path / "out.parquet", tmp_path / "missing.json", tmp_path)
