"""Integrity of the recorded opening (test plan §0.3: LB-36, LB-37, LB-40, LB-41, LB-43, LB-44).

The lockbox was opened once; these tests check that the record of that run is what it claims to be. They read the
locked tables and the recorded result, which is allowed after the opening, and never fit anything or write under
data/ or docs/. A failed check is disclosed in the decision log (D-20) and in the scorecard's S1a block; the lockbox is
never rerun to replace the record (D-12).
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from blackout import final
from blackout.storms import load_storms
from blackout.table import SCORES_FINAL_FILE, drop_check

pytestmark = [pytest.mark.realdata, pytest.mark.lockbox]

REPO = Path(__file__).resolve().parents[2]
PROCESSED = REPO / "data/processed"
FROZEN_RESULT = REPO / "docs/lockbox_result.json"
PASS_BAR_COMMIT, MODEL_CHOICE_COMMIT, OPENING_COMMIT, RECORD_COMMIT = "2f534f9", "2187e37", "7fd2732", "50d572e"
PREDICTIONS_WINDOW = pd.Timedelta(minutes=30)
CODE_FILES = ("model.py", "hybrid.py", "ranges.py", "evaluate.py", "final.py")
TWO_DECIMALS = 0.0051  # the JSON rounds to two decimals; the parquet keeps the full float


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mtime(path: Path) -> pd.Timestamp:
    return pd.Timestamp(datetime.fromtimestamp(path.stat().st_mtime, tz=UTC))


def test_lockbox_inputs_are_recorded(record: dict, recorded: dict) -> None:
    """LB-44: every table the run read hashes as recorded, and none was rebuilt after the run."""
    run_at = pd.Timestamp(recorded["provenance"]["run_at_utc"])
    assert record["run_at_utc"] == recorded["provenance"]["run_at_utc"]
    assert record["git_head"] == recorded["provenance"]["git_head"]
    roles = pd.Series([t["role"] for t in record["tables"]]).value_counts().to_dict()
    assert roles == {"main": 8, "lockbox": 2, "stress": 1}
    for entry in [*record["tables"], *record["cross_check_tables"]]:
        path = PROCESSED / entry["table"]
        assert sha256(path) == entry["sha256"], f"{entry['table']} changed since the record was written"
        assert mtime(path) < run_at and entry["newer_than_run"] is False, f"{entry['table']} is newer than the run"
    assert record["rebuilt_after_run"] is False
    assert record["uv_lock_sha256"] == sha256(REPO / "uv.lock")
    assert record["result_sha256"] == sha256(FROZEN_RESULT)
    versions = {"python": sys.version.split()[0],
                **{lib: importlib.metadata.version(lib) for lib in ("numpy", "pandas", "scikit-learn", "scipy", "pyarrow")}}
    assert record["environment"] == versions


def test_recorded_run_provenance(recorded: dict, git) -> None:
    """LB-41: the training tables are the eight main storms, every predictions file was written at the run, and a dirty
    tree is disclosed. Then, where the development history is present: the recorded commit descends from the pass bar
    and the model choice, the hashed code is that commit's, and the run falls between the opening commit and the record
    commit. That half is about the recorded commit, not about HEAD: it runs wherever those commits can be read."""
    prov = recorded["provenance"]
    head = prov["git_head"]
    storms = load_storms()
    main = [s for s in storms if s.role == "main"]
    assert [t["storm_id"] for t in prov["training_tables"]] == [s.id for s in main]
    assert {(t["table"], t["satellite"]) for t in prov["training_tables"] if t["storm_id"] == "beryl2024"} == \
        {("county_nights_beryl2024.parquet", "VJ146A2")}
    run_at = pd.Timestamp(prov["run_at_utc"])
    for storm in storms:
        written = mtime(PROCESSED / f"predictions_{storm.id}.parquet")
        assert abs(written - run_at) <= PREDICTIONS_WINDOW, f"{storm.id}: predictions written at {written}"
    if prov["working_tree_dirty"]:
        log = (REPO / "docs/decision-log.md").read_text()
        assert "D-20" in log and "working_tree_dirty" in log.split("D-20", 1)[1], \
            "a dirty tree at the run must be disclosed in D-20"
    try:
        for commit in (PASS_BAR_COMMIT, MODEL_CHOICE_COMMIT, OPENING_COMMIT, RECORD_COMMIT, head):
            git("cat-file", "-e", f"{commit}^{{commit}}")
    except subprocess.CalledProcessError:
        pytest.skip("this checkout does not have the development history (a shallow clone, or the public repository, "
                    "which starts from one commit): the commits named in the test plan are absent")
    for commit in (PASS_BAR_COMMIT, MODEL_CHOICE_COMMIT, OPENING_COMMIT):
        ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", commit, head], cwd=REPO, check=False)
        assert ancestry.returncode == 0, f"{head[:7]} does not descend from {commit}"
    for name in CODE_FILES:
        blob = subprocess.run(["git", "show", f"{head}:src/blackout/{name}"], cwd=REPO, capture_output=True, check=True)
        assert prov["code_sha256_16"][name] == hashlib.sha256(blob.stdout).hexdigest()[:16], name
    opened_at = pd.Timestamp(int(git("log", "-1", "--format=%ct", OPENING_COMMIT)), unit="s", tz="UTC")
    recorded_at = pd.Timestamp(int(git("log", "-1", "--format=%ct", RECORD_COMMIT)), unit="s", tz="UTC")
    assert opened_at < run_at < recorded_at


def test_pass_bar_holds_the_curve_and_hybrid_the_hybrid(recorded: dict, locked_storms) -> None:
    """LB-36: `pass_bar` carries the isotonic curve's numbers and `hybrid` the hybrid's; both match the final
    scorecard's rows for the same method at ±60, on the same scored rows."""
    scores = pd.read_parquet(PROCESSED / SCORES_FINAL_FILE)
    at60 = scores[scores["window"] == 60].set_index(["method", "storm_id"])
    for storm in locked_storms:
        curve, hybrid = recorded["pass_bar"][storm.id]["60"], recorded["hybrid"][storm.id]["60"]
        assert curve["mae_pp_curve"] != hybrid["mae_pp_curve"], f"{storm.id}: the two sections hold the same model"
        assert curve["mae_pp_curve"] == pytest.approx(at60.loc[("isotonic", storm.id), "mae_pp"], abs=TWO_DECIMALS)
        assert hybrid["mae_pp_curve"] == pytest.approx(at60.loc[("hybrid", storm.id), "mae_pp"], abs=TWO_DECIMALS)
        wind = at60.loc[("wind_only", storm.id), "mae_pp"]
        assert curve["mae_pp_wind_only"] == hybrid["mae_pp_wind_only"] == pytest.approx(wind, abs=TWO_DECIMALS)
        assert curve["rows_scored"] == hybrid["rows_scored"] == int(at60.loc[("isotonic", storm.id), "rows_scored"])


def test_satellite_test_recomputes_from_the_recorded_rows(recorded: dict, locked_storms) -> None:
    """LB-37: the hybrid's pre-registered test, recomputed from the recorded increment rows under the edge rules."""
    verdict, per_storm, _ = final.satellite_test(recorded["satellite_increment"], sorted(s.id for s in locked_storms))
    assert verdict == recorded["satellite_test"]["verdict"]
    assert per_storm == recorded["satellite_test"]["per_storm"]


def test_recorded_verdict_follows_the_committed_rule(recorded: dict, record: dict, locked_storms,
                                                     locked_tables) -> None:
    """LB-40: the recorded code applied no drop rule; the verdict under the committed rule, with `table.drop_check`
    on each locked table, must equal the recorded string, or D-20 names the difference."""
    drops = {s.id: drop_check(locked_tables[s.id], s) for s in locked_storms}
    assert final.verdict(recorded["pass_bar"], drops) == recorded["verdict"]
    assert record["drop_rule"] == drops, "the record's drop-rule facts differ from the tables"


def test_locked_truth_uses_the_repaired_customers(locked_storms, locked_tables, record: dict) -> None:
    """LB-43: each locked table's customers equal the repaired counts from load_counties, county for county."""
    from blackout.counties import CENSUS, load_counties

    if not CENSUS.exists():
        pytest.skip(f"{CENSUS.relative_to(REPO)} is absent: load_counties needs the Census files")
    assert record["customers_check"]["available"] is True
    for storm in locked_storms:
        per_fips = locked_tables[storm.id].groupby("fips")["customers"].agg(["nunique", "first"])
        assert (per_fips["nunique"] == 1).all(), f"{storm.id}: a county's customers change between nights"
        repaired = load_counties(storm.states).set_index("fips")["customers"].astype(float)
        assert set(per_fips.index) == set(repaired.index)
        table_values = per_fips["first"].to_numpy(dtype=float)
        differ = per_fips.index[~np.isclose(table_values, repaired.reindex(per_fips.index).to_numpy(dtype=float))]
        assert len(differ) == 0, \
            f"{storm.id}: {len(differ)} counties differ from the repaired customers: {list(differ)[:10]}"
        assert record["customers_check"]["per_storm"][storm.id]["match"] is True


def test_every_offline_integrity_check_passes_on_the_record(recorded: dict, record: dict) -> None:
    """The checks the scorecard's S1a block recomputes from the two committed files all pass here."""
    checks = final.integrity_checks(recorded, record)
    failed = [c for c in checks if c["passed"] is False]
    assert failed == [], failed
    text = "\n".join(final.render_integrity(record, checks))
    assert "S1a" in text and "| fail |" not in text
