"""Build the Python-TypeScript contract fixture: one small synthetic storm, exported by the real writer.

tests/fixtures/contract/synth2099/ holds the storm's eight files, written by export.export_storm with the storm list,
the Census shapes and the data folder replaced by synthetic stand-ins, plus expected_exposure.json, the Python twin's
expected_policies_out at each waiting period; tests/fixtures/contract/index.json lists the storm. pytest
(tests/test_contract.py) regenerates it in a temporary folder and asserts byte-equality, so a change to the contract
is deliberate and reviewed as the fixture's diff; vitest (app/src/data/contract.test.ts) parses the committed copy.

Run from the repo root: uv run python -I tests/fixtures/make_app_fixture.py [--check]
--check regenerates into a temporary folder and exits 1 when the committed copy differs.

Everything is invented: six square counties (one an island pair) in two made-up states, fips 99001-99011, thirteen
nights of which ten are exported, every status, an EAGLE-I over-count, a night the fit left blank, a county with no
customer count, one the satellite never sees, one never out and one never back. The clock is fixed through
SOURCE_DATE_EPOCH and the book and claims are seeded, so two runs write identical bytes.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from contextlib import ExitStack
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, box

from blackout import export
from blackout.storms import Storm
from blackout.table import TABLE_COLUMNS

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tests/fixtures/contract"
EXPECTED_FILE = "expected_exposure.json"
GENERATED = datetime(2099, 9, 20, tzinfo=UTC)
PASS_TIME = time(hour=7)  # night N's pass is about 07:00 UTC on calendar day N + 1
STORM = Storm(id="synth2099", name="Synthetic storm (contract fixture: every number invented)", atcf_id=None,
              landfall=date(2099, 9, 10), baseline_start=date(2099, 8, 8), baseline_end=date(2099, 9, 7),
              window_end=date(2099, 9, 17), role="main", states=("ZA", "ZB"),
              landfall_utc="2099-09-10T06:00:00+00:00")
NIGHTS = [date(2099, 9, 5) + timedelta(days=k) for k in range(13)]  # 09-05..09-07 sit in the baseline window
CLOUDY = {date(2099, 9, 10), date(2099, 9, 11)}  # Bravo's landfall nights
BLANK = date(2099, 9, 14)  # the fit left Bravo blank on a night the satellite saw
GAP = date(2099, 9, 13)  # EAGLE-I had no usable run at Foxtrot's pass
FOLDED = date(2099, 9, 12)  # Alpha's range sits above its own point here; the export folds the point in
CALM = 0.02
OUTAGE = {0: 0.85, 1: 0.6, 2: 0.4, 3: 0.2, 4: 0.08, 5: 0.04, 6: 0.02, 7: 0.01}  # Alpha's estimate by day after landfall
NEVER_BACK = {0: 0.9, 1: 0.8, 2: 0.7, 3: 0.6, 4: 0.5, 5: 0.45, 6: 0.4, 7: 0.35}
# fips, name, state, housing units, customers (None: no EAGLE-I count), shape
COUNTIES = [
    ("99001", "Alpha", "ZA", 120_000, 140_000, box(-82.0, 29.0, -81.5, 29.5)),
    ("99003", "Bravo", "ZA", 42_000, 50_000, box(-81.5, 29.0, -81.0, 29.5)),
    ("99005", "Charlie", "ZA", 15_000, None, box(-82.0, 29.5, -81.5, 30.0)),
    ("99007", "Delta", "ZB", 30_000, 36_000, box(-81.5, 29.5, -81.0, 30.0)),
    ("99009", "Echo", "ZB", 20_000, 24_000, box(-81.0, 29.5, -80.5, 30.0)),
    ("99011", "Foxtrot", "ZB", 8_000, 9_000,
     MultiPolygon([box(-80.5, 29.5, -80.25, 29.75), box(-80.5, 29.0, -80.25, 29.25)])),
]
# the fit's estimate and EAGLE-I's fraction out, by day after landfall, with the value on every other night
ESTIMATE = {
    "99001": (OUTAGE, 0.01),
    "99003": ({day: round(0.7 * value, 4) for day, value in OUTAGE.items()}, 0.01),
    "99009": ({}, CALM),  # never out
    "99011": (NEVER_BACK, CALM),  # out and never back within the window
}
OFFICIAL = {
    "99001": ({0: 0.8, 1: 0.55, 2: 0.35, 3: 0.15, 4: 0.06, 5: 0.03, 6: 0.02, 7: 0.01}, 0.01),
    "99003": ({0: 1.25, 1: 1.03, 2: 0.25, 3: 0.12, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.01}, 0.01),  # over-counts first
    "99007": ({0: 0.7, 1: 0.5, 2: 0.3, 3: 0.08, 4: 0.05, 5: 0.02, 6: 0.01, 7: 0.01}, 0.01),  # out, unseen
    "99009": ({}, 0.01),
    "99011": ({0: 0.85, 1: 0.75, 2: 0.65, 3: 0.6, 4: 0.55, 5: 0.5, 6: 0.45, 7: 0.4}, CALM),
}


def status_for(fips: str, night: date) -> str:
    if fips == "99005":
        return "not_measurable"  # too dark to measure on every night
    if fips == "99007" or (fips == "99003" and night in CLOUDY):
        return "cant_see"
    return "ok"


def estimate_for(fips: str, night: date) -> float:
    if fips == "99003" and night == BLANK:
        return math.nan
    by_day, elsewhere = ESTIMATE.get(fips, ({}, CALM))
    return by_day.get((night - STORM.landfall).days, elsewhere)


def official_for(fips: str, night: date) -> float:
    if fips == "99005" or (fips == "99011" and night == GAP):
        return math.nan  # no customer count; no usable run at the pass
    by_day, elsewhere = OFFICIAL[fips]
    return by_day.get((night - STORM.landfall).days, elsewhere)


def synthetic_storm(storm_id: str) -> Storm:
    if storm_id != STORM.id:
        raise KeyError(storm_id)
    return STORM


def synthetic_counties(states: tuple[str, ...]) -> gpd.GeoDataFrame:
    if tuple(states) != STORM.states:
        raise ValueError(f"the fixture storm covers {STORM.states}, not {states}")
    return gpd.GeoDataFrame({
        "fips": [c[0] for c in COUNTIES], "name": [c[1] for c in COUNTIES], "state": [c[2] for c in COUNTIES],
        "housing_units": [c[3] for c in COUNTIES], "customers": pd.array([c[4] for c in COUNTIES], dtype="Int64"),
    }, geometry=[c[5] for c in COUNTIES], crs="EPSG:4326")


def synthetic_table() -> pd.DataFrame:
    """A county x night table with exactly the columns table.py writes."""
    records = []
    for night in NIGHTS:
        for fips, _, state, housing, customers, _ in COUNTIES:
            status, share = status_for(fips, night), official_for(fips, night)
            count = share * customers if customers else math.nan
            records.append({
                "storm_id": STORM.id, "fips": fips, "night": night, "satellite": "VNP46A2",
                "pct_darker": estimate_for(fips, night) if status == "ok" else math.nan,
                "visible_share": 0.9 if status == "ok" else 0.1, "base_total": 800.0, "status": status,
                "sensor_zenith": 25.0, "lunar_irradiance": 0.5,
                "official_customers_out": count, "official_customers_out_30": count, "official_customers_out_90": count,
                "official_pct_out": share, "official_pct_out_30": share, "official_pct_out_90": share,
                "customers": float(customers) if customers else math.nan, "housing_units": housing,
                "pass_utc": pd.Timestamp(datetime.combine(night + timedelta(days=1), PASS_TIME, tzinfo=UTC)),
                "pass_source": "VNP46A1", "wind_band": 64 if state == "ZA" else 34,
                "coverage": 0.95 if state == "ZA" else 0.7, "covered": state == "ZA",
            })
    return pd.DataFrame(records)[TABLE_COLUMNS]


def synthetic_predictions(table: pd.DataFrame) -> pd.DataFrame:
    """The fit's output. Rows the satellite can't see carry est 0.0 on purpose: the export must still write null."""
    seen = (table["status"] == "ok").to_numpy()
    est = np.where(seen, [estimate_for(f, n) for f, n in zip(table["fips"], table["night"])], 0.0)
    lo = np.clip(est - 0.1, 0.0, 1.0)
    folded = ((table["fips"] == "99001") & (table["night"] == FOLDED)).to_numpy()
    return pd.DataFrame({"storm_id": table["storm_id"], "fips": table["fips"], "night": table["night"],
                         "status": table["status"], "est": est, "lo": np.where(folded, est + 0.05, lo),
                         "hi": np.clip(est + 0.1, 0.0, 1.0)})


def synthetic_scorecard() -> pd.DataFrame:
    """evaluate-style rows: the three required methods, the two optional ones, a NaN metric, another storm's row."""
    return pd.DataFrame({
        "storm_id": [STORM.id] * 5 + ["other2000"],
        "window": [60] * 6,
        "method": ["isotonic", "wind_only", "nothing", "hybrid", "wind_timing", "isotonic"],
        "mae_pp": [12.5, 20.0, 35.0, 9.0, 11.0, 1.0],
        "peak_total_est": [100_000.0, 80_000.0, 0.0, 150_000.0, 120_000.0, 1.0],
        "peak_total_official": [120_000.0] * 5 + [1.0],
        "catch_rate_50": [0.75, 0.5, 0.0, 0.9, 0.8, 1.0],
        "false_alarm_50": [0.1, 0.2, math.nan, 0.25, 0.3, 0.0],
        "restore_day_err": [1.5, 3.0, math.nan, 1.0, 2.0, 0.0],
        "measurable_share": [0.8, 1.0, 1.0, 0.8, 1.0, 1.0],
    })


def generate(out: Path) -> Path:
    """Write <out>/index.json and <out>/synth2099/ (the eight files and expected_exposure.json); returns the folder.

    The parquet inputs live in a temporary folder that stands in for data/processed, and the storm list and Census
    shapes are patched for the duration of the export only.
    """
    out = Path(out)
    with tempfile.TemporaryDirectory() as scratch, ExitStack() as patches:
        processed = Path(scratch)
        table = synthetic_table()
        table.to_parquet(processed / f"county_nights_{STORM.id}.parquet", index=False)
        synthetic_predictions(table).to_parquet(processed / f"predictions_{STORM.id}.parquet", index=False)
        patches.enter_context(mock.patch.object(export, "PROCESSED", processed))
        patches.enter_context(mock.patch.object(export, "get_storm", synthetic_storm))
        patches.enter_context(mock.patch.object(export, "load_counties", synthetic_counties))
        patches.enter_context(mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": str(int(GENERATED.timestamp()))}))
        folder = export.export_storm(STORM.id, out=out, scorecard=synthetic_scorecard())
    exposure = json.loads((folder / "exposure.json").read_text(encoding="utf-8"))
    expected = {str(hours): export.expected_policies_out(exposure, hours) for hours in export.WAITING_PERIODS}
    export.write_text(folder / EXPECTED_FILE, json.dumps(expected, allow_nan=False, indent=2) + "\n")
    return folder


def fixture_files(root: Path) -> dict[str, bytes]:
    """index.json and every file of the storm folder under `root`, by relative posix path."""
    files = {}
    for path in sorted(Path(root).rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and (relative == "index.json" or relative.startswith(f"{STORM.id}/")):
            files[relative] = path.read_bytes()
    return files


def differences(committed: Path, fresh: Path) -> list[str]:
    """Relative paths whose bytes differ, or that exist on one side only."""
    before, after = fixture_files(committed), fixture_files(fresh)
    return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))


def sync(fresh: Path, out: Path) -> None:
    """Replace the committed fixture files with the fresh ones, removing stale files from the storm folder."""
    out.mkdir(parents=True, exist_ok=True)
    stale = out / STORM.id
    if stale.exists():
        shutil.rmtree(stale)
    for relative, data in fixture_files(fresh).items():
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build (or check) the contract fixture under tests/fixtures/contract")
    parser.add_argument("--check", action="store_true", help="regenerate into a temporary folder and compare")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        fresh = Path(scratch)
        generate(fresh)
        if args.check:
            stale = differences(OUT, fresh)
            if stale:
                print("stale contract fixture: " + ", ".join(stale) + "\nregenerate with: uv run python -I "
                      "tests/fixtures/make_app_fixture.py", file=sys.stderr)
                return 1
            print(f"{OUT.relative_to(REPO)} is current")
            return 0
        sync(fresh, OUT)
    size = sum(len(data) for data in fixture_files(OUT).values())
    print(f"wrote {OUT.relative_to(REPO)}: {len(fixture_files(OUT))} files, {size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
