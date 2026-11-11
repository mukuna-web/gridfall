"""Task 10: static JSON for the app (docs/plan.md, Week 6).

Everything here is synthetic and offline: a toy storm with four square counties, a tiny county x night table and
predictions in tmp_path, `load_counties` and `get_storm` monkeypatched, and small stand-ins for ranges.py,
evaluate.py and model.py. Other builders write those modules in parallel; the stand-ins follow their documented
signatures, so these tests pass whether or not the real modules exist yet.
"""

from __future__ import annotations

import json
import math
import sys
import types
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import geopandas as gpd
import jsonschema
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon, box, shape

import blackout
from blackout import export
from blackout.portfolio import make_claims, make_portfolio
from blackout.storms import Storm
from blackout.table import TABLE_COLUMNS

REPO = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((REPO / "schema/export.schema.json").read_text())
TOY = json.loads((Path(__file__).parent / "fixtures/exposure_toy.json").read_text())
STORM_FILES = {
    "meta.json": "meta", "counties.geojson": "counties", "states.geojson": "states", "nights.json": "nights",
    "restoration.json": "restoration", "exposure.json": "exposure", "claims.json": "claims",
    "scorecard.json": "scorecard",
}
STORM = Storm(id="toy2099", name="Toy", atcf_id=None, landfall=date(2099, 9, 10), baseline_start=date(2099, 8, 8),
              baseline_end=date(2099, 9, 7), window_end=date(2099, 9, 14), role="main", states=("FL", "GA"))
NIGHTS = [date(2099, 9, 5) + timedelta(days=k) for k in range(10)]  # 09-05..09-07 sit in the baseline window
EXPORTED = [night for night in NIGHTS if night > STORM.baseline_end]
EST = {date(2099, 9, 10): 0.8, date(2099, 9, 11): 0.6, date(2099, 9, 12): 0.4, date(2099, 9, 13): 0.2,
       date(2099, 9, 14): 0.05}
COUNTIES = [  # fips, state, housing units, customers (None: MCC.csv has no count)
    ("12001", "FL", 100_000, 120_000),
    ("12003", "FL", 50_000, 60_000),
    ("13001", "GA", 30_000, None),
    ("13003", "GA", 20_000, 25_000),
    ("13005", "GA", 10_000, 12_000),  # seen every night and never more than 10% out
]
CLOUDY = {("12003", date(2099, 9, 10)), ("12003", date(2099, 9, 11))}


def status_for(fips: str, night: date) -> str:
    if fips == "13001":
        return "not_measurable"  # too dark to measure on every night
    if fips == "13003" or (fips, night) in CLOUDY:
        return "cant_see"  # 13003 is blind on every night
    return "ok"


def official_for(fips: str, night: date) -> float:
    if fips == "13001":
        return math.nan  # no customer count
    if (fips, night) == ("12001", date(2099, 9, 11)):
        return math.nan  # EAGLE-I had no usable run at the pass
    if (fips, night) == ("12003", date(2099, 9, 10)):
        return 1.25  # an EAGLE-I over-count
    if fips == "13005":
        return 0.02
    return round(0.9 * EST.get(night, 0.0), 4)


def est_for(fips: str, night: date) -> float:
    return 0.01 if fips == "13005" else EST.get(night, 0.0)


def toy_counties() -> gpd.GeoDataFrame:
    # 12001's south edge carries 99 extra collinear points, so simplify(0.005) must bring its ring down to 5 corners.
    wiggly = Polygon([(-82.0 + k * 0.005, 29.0) for k in range(100)] + [(-81.5, 29.0), (-81.5, 29.5), (-82.0, 29.5)])
    shapes = [wiggly, box(-81.5, 29.0, -81.0, 29.5), box(-82.0, 29.5, -81.5, 30.0), box(-81.5, 29.5, -81.0, 30.0),
              box(-81.0, 29.5, -80.5, 30.0)]
    return gpd.GeoDataFrame({
        "fips": [c[0] for c in COUNTIES], "name": ["Alpha", "Bravo", "Charlie", "Delta", "Echo"],
        "state": [c[1] for c in COUNTIES], "housing_units": [c[2] for c in COUNTIES],
        "customers": pd.array([c[3] for c in COUNTIES], dtype="Int64"),
    }, geometry=shapes, crs="EPSG:4326")


def toy_table(storm_id: str = STORM.id, rows=COUNTIES, nights=NIGHTS, status=status_for, official=official_for,
              est=est_for) -> pd.DataFrame:
    """A county x night table with exactly the columns table.py writes."""
    records = []
    for night in nights:
        for fips, state, housing, customers in rows:
            seen, share = status(fips, night) == "ok", official(fips, night)
            count = share * customers if customers else math.nan
            records.append({
                "storm_id": storm_id, "fips": fips, "night": night, "satellite": "VNP46A2",
                "pct_darker": est(fips, night) if seen else math.nan, "visible_share": 0.9 if seen else 0.1,
                "base_total": 800.0, "status": status(fips, night), "sensor_zenith": 25.0, "lunar_irradiance": 0.5,
                "official_customers_out": count, "official_customers_out_30": count, "official_customers_out_90": count,
                "official_pct_out": share, "official_pct_out_30": share, "official_pct_out_90": share,
                "customers": float(customers) if customers else math.nan, "housing_units": housing,
                "pass_utc": pd.Timestamp(night + timedelta(days=1), tz="UTC") + pd.Timedelta(hours=7),
                "pass_source": "VNP46A1", "wind_band": 64 if state == "FL" else 34,
                "coverage": 0.95 if state == "FL" else 0.7, "covered": state == "FL",
            })
    return pd.DataFrame(records)[TABLE_COLUMNS]


def toy_predictions(table: pd.DataFrame, est=est_for) -> pd.DataFrame:
    """The fit's output. Blind rows carry est 0.0 on purpose: the export must still write null there."""
    seen = (table["status"] == "ok").to_numpy()
    value = np.where(seen, [est(f, n) for f, n in zip(table["fips"], table["night"])], 0.0)
    return pd.DataFrame({"storm_id": table["storm_id"], "fips": table["fips"], "night": table["night"],
                         "status": table["status"], "est": value, "lo": np.clip(value - 0.1, 0, 1),
                         "hi": np.clip(value + 0.1, 0, 1)})


# --- stand-ins for ranges.py, evaluate.py and model.py --------------------------------------------------------------

@dataclass
class Calls:
    restoration: list = field(default_factory=list)
    brackets: list = field(default_factory=list)
    official: list = field(default_factory=list)


def stand_ins(calls: Calls, overcount_rule=None) -> dict[str, types.ModuleType | None]:
    ranges, evaluate = types.ModuleType("blackout.ranges"), types.ModuleType("blackout.evaluate")

    def restoration_interval(county_nights, landfall, threshold=0.10):
        calls.restoration.append((county_nights.copy(), landfall, threshold))
        ok = county_nights[(county_nights["status"] == "ok") & (county_nights["night"] >= landfall)]
        ok = ok.sort_values("night")
        days = [(night - landfall).days for night in ok["night"]]
        for k, (day, value) in enumerate(zip(days, ok["est"])):
            if value <= threshold:
                return (float(days[k - 1]) if k else 0.0, float(day))
        return (float(days[-1]), None)

    def pct_out_bracket(county_nights, landfall, hours):
        calls.brackets.append((county_nights.copy(), landfall, hours))
        if not (county_nights["status"] == "ok").any():
            return None
        return (0.6, 0.2) if hours == 24 else (0.1, 0.3)  # 24 h comes back high-first: the export sorts it

    def official_restore_day(series, threshold=0.10):
        """Like evaluate's rule: the first known night after the (first) peak at or below the threshold. A county
        that was never out still gets a day from it (the night after its tiny peak), which the export must not use."""
        calls.official.append((series.copy(), threshold))
        known = series.dropna()
        after = known.loc[known.idxmax():].iloc[1:]
        below = after[after <= threshold]
        return float(below.index[0]) if len(below) else math.nan

    ranges.restoration_interval, ranges.pct_out_bracket = restoration_interval, pct_out_bracket
    evaluate.official_restore_day = official_restore_day
    model = None  # None in sys.modules makes `import blackout.model` fail: "model.py doesn't exist yet"
    if overcount_rule is not None:
        model = types.ModuleType("blackout.model")
        model.apply_overcount_rule = overcount_rule
    return {"ranges": ranges, "evaluate": evaluate, "model": model}


def install(monkeypatch, modules: dict[str, types.ModuleType | None]) -> None:
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, f"blackout.{name}", module)
        if module is None:
            monkeypatch.delattr(blackout, name, raising=False)
        else:
            monkeypatch.setattr(blackout, name, module, raising=False)


@dataclass
class World:
    out: Path
    processed: Path
    calls: Calls


def _toy_storm(storm_id: str) -> Storm:
    if storm_id != STORM.id:
        raise KeyError(storm_id)
    return STORM


def _toy_load_counties(states: tuple[str, ...]) -> gpd.GeoDataFrame:
    assert states == STORM.states
    return toy_counties()


def toy_world(tmp_path: Path, monkeypatch, nights: list[date] = NIGHTS) -> World:
    """The toy storm's table and predictions in tmp_path, with storms and Census shapes patched out (offline)."""
    processed = tmp_path / "processed"
    processed.mkdir()
    table = toy_table(nights=nights)
    table.to_parquet(processed / "county_nights_toy2099.parquet", index=False)
    toy_predictions(table).to_parquet(processed / "predictions_toy2099.parquet", index=False)
    monkeypatch.setattr(export, "PROCESSED", processed)
    monkeypatch.setattr(export, "get_storm", _toy_storm)
    monkeypatch.setattr(export, "load_counties", _toy_load_counties)
    return World(tmp_path / "app_data", processed, Calls())


@pytest.fixture
def world(tmp_path, monkeypatch) -> World:
    toy = toy_world(tmp_path, monkeypatch)
    install(monkeypatch, stand_ins(toy.calls))
    return toy


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


# --- tests -----------------------------------------------------------------------------------------------------------

def test_export_validates_schema(world):
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    folder = export.export_storm(STORM.id, out=world.out)
    assert folder == world.out / STORM.id
    assert sorted(p.name for p in folder.iterdir()) == sorted(STORM_FILES)
    for name, kind in STORM_FILES.items():
        validate(kind, read_strict(folder / name))
    index = read_strict(world.out / "index.json")
    validate("index", index)
    assert index == {"storms": [{"id": "toy2099", "name": "Toy", "landfall": "2099-09-10", "role": "main",
                                 "satellite": "VNP46A2"}]}
    meta = read_strict(folder / "meta.json")
    assert meta["nights"] == [night.isoformat() for night in EXPORTED]  # nights after the baseline window only
    assert (meta["waiting_periods"], meta["default_waiting_period"]) == ([24, 48, 72], 72)
    nights = read_strict(folder / "nights.json")
    assert sorted(nights) == [c[0] for c in COUNTIES]
    assert all([entry["night"] for entry in entries] == meta["nights"] for entries in nights.values())
    claims = read_strict(folder / "claims.json")
    book = make_portfolio(toy_counties())
    expected = make_claims(book, {"12001": 4.0, "12003": 4.0, "13001": math.nan, "13003": 4.0, "13005": 0.0})
    assert claims == expected.to_dict(orient="records")
    assert "13005" not in {claim["fips"] for claim in claims}  # never out, so nothing to claim against
    exposure = read_strict(folder / "exposure.json")
    kinds = pd.crosstab(book["fips"], book["kind"])
    assert {f: (e["home"], e["business"]) for f, e in exposure.items()} == {
        f: (int(kinds.at[f, "home"]), int(kinds.at[f, "business"])) for f in kinds.index}


def test_cant_see_exports_null_not_zero(world):
    folder = export.export_storm(STORM.id, out=world.out)
    for path in folder.iterdir():
        text = path.read_text()
        assert "NaN" not in text and "Infinity" not in text, path.name
    nights = by_night(read_strict(folder / "nights.json"))
    cloudy = nights["12003"]["2099-09-10"]
    assert cloudy["status"] == "cant_see"
    assert (cloudy["est"], cloudy["lo"], cloudy["hi"]) == (None, None, None)  # the predictions said 0.0
    no_run = nights["12001"]["2099-09-11"]
    assert no_run["official"] is None  # NaN in the table
    assert (no_run["est"], no_run["lo"], no_run["hi"]) == (0.6, 0.5, 0.7)  # visible, so the estimate stays
    assert all(e["status"] == "not_measurable" and e["est"] is None and e["official"] is None
               for e in nights["13001"].values())
    assert all(e["est"] is None for e in nights["13003"].values())
    restoration = read_strict(folder / "restoration.json")
    assert restoration["13003"] == {"est_lo": None, "est_hi": None, "official_day": 4.0}
    assert restoration["13001"] == {"est_lo": None, "est_hi": None, "official_day": None}
    exposure = read_strict(folder / "exposure.json")
    assert exposure["13001"]["at"] == exposure["13003"]["at"] == {"24": None, "48": None, "72": None}
    blind = sum(exposure[f]["home"] + exposure[f]["business"] for f in ("13001", "13003"))
    seen = sum(exposure[f]["home"] + exposure[f]["business"] for f in ("12001", "12003", "13005"))
    totals = export.expected_policies_out(exposure, 72)
    assert totals["unknown_policies"] == blind > 0  # can't-see policies are unknown, never zero
    assert totals["low"] == pytest.approx(0.1 * seen) and totals["high"] == pytest.approx(0.3 * seen)


def test_fit_cannot_show_what_the_table_cannot_see(world):
    predictions = pd.read_parquet(world.processed / "predictions_toy2099.parquet")
    blind = (predictions["fips"] == "13003") & (predictions["night"] == date(2099, 9, 12))
    hidden = (predictions["fips"] == "12001") & (predictions["night"] == date(2099, 9, 12))
    predictions.loc[blind, ["status", "est", "lo", "hi"]] = ["ok", 0.0, 0.0, 0.1]  # a buggy fit "sees" a blind county
    predictions.loc[hidden, ["status", "est", "lo", "hi"]] = ["cant_see", math.nan, math.nan, math.nan]
    dark = (predictions["fips"] == "13001") & (predictions["night"] == date(2099, 9, 12))
    predictions.loc[dark, "status"] = "cant_see"  # a stale fit: the table says too dark to measure, not cloud
    predictions.to_parquet(world.processed / "predictions_toy2099.parquet", index=False)
    folder = export.export_storm(STORM.id, out=world.out)
    nights = by_night(read_strict(folder / "nights.json"))
    assert nights["13003"]["2099-09-12"] | {"official": None} == {
        "night": "2099-09-12", "status": "cant_see", "est": None, "lo": None, "hi": None, "official": None}
    assert (nights["12001"]["2099-09-12"]["status"], nights["12001"]["2099-09-12"]["est"]) == ("cant_see", None)
    assert nights["13001"]["2099-09-12"]["status"] == "not_measurable"  # the table names why it can't be seen
    assert any("status differs" in note for note in read_strict(folder / "meta.json")["notes"])


def test_exposure_toy():
    validate("exposure", TOY["exposure"])
    for hours in (24, 48, 72):
        assert export.expected_policies_out(TOY["exposure"], hours) == pytest.approx(TOY["expected"][str(hours)])
    with pytest.raises(ValueError):
        export.expected_policies_out(TOY["exposure"], 36)
    # the app reads a pair as (min, max) and a half-null pair as unknown; the twin must too
    odd = {"12001": {"home": 9, "business": 1, "at": {"24": [0.75, 0.5], "48": [None, 0.5], "72": None}}}
    assert export.expected_policies_out(odd, 24) == {"low": 5.0, "high": 7.5, "unknown_policies": 0}
    assert export.expected_policies_out(odd, 48) == {"low": 0.0, "high": 0.0, "unknown_policies": 10}


def test_restoration_and_brackets_come_from_ranges(world):
    folder = export.export_storm(STORM.id, out=world.out)
    restoration = read_strict(folder / "restoration.json")
    assert restoration["12001"] == {"est_lo": 3.0, "est_hi": 4.0, "official_day": 4.0}
    assert restoration["12003"] == {"est_lo": 3.0, "est_hi": 4.0, "official_day": 4.0}
    # never above 10% out: back by landfall, the convention ranges.restoration_interval uses for estimates
    assert restoration["13005"] == {"est_lo": 0.0, "est_hi": 0.0, "official_day": 0.0}
    exposure = read_strict(folder / "exposure.json")
    assert exposure["12001"]["at"] == {"24": [0.2, 0.6], "48": [0.1, 0.3], "72": [0.1, 0.3]}
    for frame, landfall, threshold in world.calls.restoration:
        assert landfall == STORM.landfall and threshold == pytest.approx(0.10)
        assert {"night", "status", "est"} <= set(frame.columns)
        assert all(isinstance(night, date) for night in frame["night"])
        assert frame.loc[frame["status"] == "ok", "est"].notna().all()  # no "ok" row without an estimate
    assert len(world.calls.restoration) == 3  # blind counties are never sent: they have no estimate at all
    assert sorted(hours for _, _, hours in world.calls.brackets) == [24] * 3 + [48] * 3 + [72] * 3
    assert all("pass_utc" in frame.columns for frame, _, _ in world.calls.brackets)
    assert len(world.calls.official) == 3  # 13001 has no official reading, 13005 was never out
    for series, threshold in world.calls.official:
        assert series.index.min() == 0 and threshold == pytest.approx(0.10)  # days after landfall, no earlier
        assert (series.dropna() <= 1).all()  # over-counts never feed the restore day


def test_never_out_county_is_back_by_its_first_official_reading():
    """A county EAGLE-I never showed above 10% after landfall is back by its first reading, confirmed a day later
    (evaluate's 24-hour rule). Nights EAGLE-I missed are unknown, never "not out", so day 0 needs a landfall reading."""
    def county(values: list[float], start: int = 0) -> pd.DataFrame:
        nights = [STORM.landfall + timedelta(days=start + k) for k in range(len(values))]
        return pd.DataFrame({"night": nights, "official": values})

    assert export.official_restore(county([0.02, 0.01, 0.03]), STORM.landfall) == 0.0
    assert export.official_restore(county([0.9, 0.5, 0.02, 0.01], start=-2), STORM.landfall) == 0.0  # earlier storm
    assert export.official_restore(county([math.nan, math.nan, 0.02, math.nan, 0.01]), STORM.landfall) == 2.0
    assert math.isnan(export.official_restore(county([math.nan, math.nan, 0.02]), STORM.landfall))  # unconfirmed
    assert math.isnan(export.official_restore(county([math.nan, math.nan]), STORM.landfall))


def test_claims_only_where_eagle_i_shows_an_outage(world):
    """13005 never shows above 10%, but with no reading on days 0-1 it is only "back by day 2": still no claims."""
    path = world.processed / "county_nights_toy2099.parquet"
    table = pd.read_parquet(path)
    gap = (table["fips"] == "13005") & table["night"].isin([date(2099, 9, 10), date(2099, 9, 11)])
    table.loc[gap, ["official_pct_out", "official_customers_out"]] = math.nan
    table.to_parquet(path, index=False)
    folder = export.export_storm(STORM.id, out=world.out)
    assert read_strict(folder / "restoration.json")["13005"]["official_day"] == 2.0
    claims = read_strict(folder / "claims.json")
    assert len(claims) == 200 and {claim["fips"] for claim in claims} == {"12001", "12003", "13003"}


def test_index_merges_and_sorts_by_landfall(world):
    world.out.mkdir(parents=True)
    later = {"id": "zeta2100", "name": "Zeta", "landfall": "2100-10-01", "role": "main", "satellite": "VNP46A2"}
    earlier = {"id": "abel2001", "name": "Abel", "landfall": "2001-06-01", "role": "stress", "satellite": "VJ146A2"}
    stale = {**later, "id": "toy2099", "name": "Old name", "landfall": "2099-09-10"}
    (world.out / "index.json").write_text(json.dumps({"storms": [later, stale, earlier]}))
    export.export_storm(STORM.id, out=world.out)
    export.export_storm(STORM.id, out=world.out)  # a re-export replaces its entry, never duplicates it
    index = read_strict(world.out / "index.json")
    assert [s["id"] for s in index["storms"]] == ["abel2001", "toy2099", "zeta2100"]
    assert index["storms"][1]["name"] == "Toy"
    (world.out / "index.json").write_text("{not json")
    with pytest.raises(ValueError):
        export.export_storm(STORM.id, out=world.out)  # never overwrite an index it cannot read


def test_counties_simplified_and_states_dissolved(world):
    folder = export.export_storm(STORM.id, out=world.out)
    features = {f["properties"]["fips"]: f for f in read_strict(folder / "counties.geojson")["features"]}
    assert len(features["12001"]["geometry"]["coordinates"][0]) == 5  # 104 ring points simplified to the corners
    assert features["12001"]["properties"] == {"fips": "12001", "name": "Alpha", "state": "FL",
                                               "housing_units": 100000, "customers": 120000}
    assert features["13001"]["properties"]["customers"] is None
    states = {f["properties"]["state"]: f for f in read_strict(folder / "states.geojson")["features"]}
    assert sorted(states) == ["FL", "GA"]
    assert shape(states["FL"]["geometry"]).equals(box(-82.0, 29.0, -81.0, 29.5))


def test_overcount_is_null_with_a_note(world):
    folder = export.export_storm(STORM.id, out=world.out)
    assert by_night(read_strict(folder / "nights.json"))["12003"]["2099-09-10"]["official"] is None
    assert any("over-count" in note.lower() for note in read_strict(folder / "meta.json")["notes"])


def test_overcount_rule_from_model_is_used(world, monkeypatch):
    def apply_overcount_rule(table: pd.DataFrame) -> pd.DataFrame:
        capped = table.copy()
        capped["official_pct_out"] = capped["official_pct_out"].clip(upper=1.0)
        return capped

    install(monkeypatch, {"model": stand_ins(Calls(), apply_overcount_rule)["model"]})
    folder = export.export_storm(STORM.id, out=world.out)
    assert by_night(read_strict(folder / "nights.json"))["12003"]["2099-09-10"]["official"] == 1.0
    assert any("apply_overcount_rule" in note for note in read_strict(folder / "meta.json")["notes"])


def test_scorecard_from_frame_and_unscored(world):
    unscored = read_strict(export.export_storm(STORM.id, out=world.out) / "scorecard.json")
    assert (unscored["storm_id"], unscored["window"]) == (STORM.id, 60)
    assert sorted(unscored["methods"]) == ["isotonic", "nothing", "wind_only"]
    assert all(value is None for metrics in unscored["methods"].values() for value in metrics.values())
    assert "not scored" in unscored["note"].lower()
    frame = pd.DataFrame({
        "storm_id": [STORM.id] * 3 + ["other2000"],
        "method": ["isotonic", "wind_only", "nothing", "isotonic"],
        "mae_pp": [12.5, 20.0, 35.0, 1.0],
        "peak_total_est": [100_000.0, 80_000.0, 0.0, 1.0],
        "peak_total_official": [120_000.0] * 3 + [1.0],
        "catch_rate_50": [0.75, 0.5, 0.0, 1.0],
        "false_alarm_50": [0.1, 0.2, math.nan, 0.0],
        "restore_day_err": [1.5, 3.0, math.nan, 0.0],
        "measurable_share": [0.8, 1.0, 1.0, 1.0],
    })
    card = read_strict(export.export_storm(STORM.id, out=world.out, scorecard=frame) / "scorecard.json")
    validate("scorecard", card)
    assert card["methods"]["isotonic"]["mae_pp"] == 12.5
    assert card["methods"]["wind_only"]["catch_rate_50"] == 0.5
    assert card["methods"]["nothing"]["false_alarm_50"] is None
    assert "not scored" not in card["note"].lower()
    assert "hybrid" not in card["methods"]  # optional methods appear only when scored
    hybrid = pd.concat([frame, frame.iloc[[0]].assign(method="hybrid", mae_pp=9.0),
                        frame.iloc[[1]].assign(method="wind_timing", mae_pp=11.0)], ignore_index=True)
    card = read_strict(export.export_storm(STORM.id, out=world.out, scorecard=hybrid) / "scorecard.json")
    validate("scorecard", card)
    assert card["methods"]["hybrid"]["mae_pp"] == 9.0 and card["methods"]["wind_timing"]["mae_pp"] == 11.0


def test_without_predictions_estimates_are_null(world):
    (world.processed / "predictions_toy2099.parquet").unlink()
    folder = export.export_storm(STORM.id, out=world.out)
    nights = read_strict(folder / "nights.json")
    assert all(entry["est"] is None for entries in nights.values() for entry in entries)
    assert by_night(nights)["12001"]["2099-09-10"]["official"] == 0.72  # the official line still shows
    assert any("predictions" in note.lower() for note in read_strict(folder / "meta.json")["notes"])
    with pytest.raises(FileNotFoundError):
        export.export_storm(STORM.id, out=world.out, predictions=world.processed / "missing.parquet")


def test_export_refuses_bad_inputs(world):
    predictions = pd.read_parquet(world.processed / "predictions_toy2099.parquet")
    row = predictions.index[(predictions["fips"] == "12001") & (predictions["night"] == date(2099, 9, 12))][0]
    predictions.loc[row, "est"] = 1.5
    predictions.to_parquet(world.processed / "bad.parquet", index=False)
    with pytest.raises(ValueError):
        export.export_storm(STORM.id, out=world.out, predictions=world.processed / "bad.parquet")
    assert not (world.out / STORM.id).exists()  # nothing is written before every file passes
    (world.processed / "county_nights_toy2099.parquet").unlink()
    with pytest.raises(FileNotFoundError):
        export.export_storm(STORM.id, out=world.out)


def test_schema_failure_writes_nothing(world, monkeypatch):
    monkeypatch.setattr(sys.modules["blackout.ranges"], "pct_out_bracket", lambda nights, landfall, hours: (0.2, 1.7))
    with pytest.raises(ValueError, match="exposure.json"):
        export.export_storm(STORM.id, out=world.out)
    assert not world.out.exists()  # not even index.json


@pytest.mark.parametrize("spoil", [
    lambda t: t.drop(columns="official_pct_out"),
    lambda t: t.assign(storm_id="zeta2100"),  # rows filed under another storm
    lambda t: t.assign(fips="12x01"),
    lambda t: t.assign(status="cloudy"),
    lambda t: pd.concat([t, t.iloc[:1]], ignore_index=True),
    lambda t: t.assign(satellite=["VNP46A2", "VJ146A2"] * (len(t) // 2)),
])
def test_bad_tables_are_refused(world, spoil):
    path = world.processed / "county_nights_toy2099.parquet"
    spoil(pd.read_parquet(path)).to_parquet(path, index=False)
    with pytest.raises(ValueError):
        export.export_storm(STORM.id, out=world.out)
    assert not world.out.exists()


@pytest.mark.parametrize("spoil", [
    lambda c: c.drop(columns="housing_units"),
    lambda c: c.assign(fips="12001"),
    lambda c: c.assign(state="Florida"),
    lambda c: c.assign(housing_units=-1),
    lambda c: c.assign(customers=1.5),
    lambda c: c.set_geometry(c.geometry.boundary),
])
def test_bad_counties_are_refused(world, monkeypatch, spoil):
    monkeypatch.setattr(export, "load_counties", lambda states: spoil(toy_counties()))
    with pytest.raises(ValueError):
        export.export_storm(STORM.id, out=world.out)


def test_missing_rows_and_unknown_counties_get_notes(world):
    path = world.processed / "county_nights_toy2099.parquet"
    table = pd.read_parquet(path)
    gap = (table["fips"] == "12001") & (table["night"] == date(2099, 9, 13))
    extra = table[table["fips"] == "12003"].assign(fips="12099")  # a county with no shape
    pd.concat([table[~gap], extra], ignore_index=True).to_parquet(path, index=False)
    folder = export.export_storm(STORM.id, out=world.out)
    entry = by_night(read_strict(folder / "nights.json"))["12001"]["2099-09-13"]
    assert (entry["status"], entry["est"], entry["official"]) == ("cant_see", None, None)
    notes = " ".join(read_strict(folder / "meta.json")["notes"])
    assert "no row in the county x night table" in notes and "12099" in notes and "GA (70%)" in notes


def test_export_with_the_real_modules(tmp_path, monkeypatch):
    """The same toy through the real ranges.py, evaluate.py and model.py (skipped until they exist), with nights
    to 09-20 so evaluate's 24-hour rule can confirm the restore days. The stand-ins above only mirror signatures."""
    for name in ("ranges", "evaluate", "model"):
        pytest.importorskip(f"blackout.{name}")
    toy = toy_world(tmp_path, monkeypatch, nights=[date(2099, 9, 5) + timedelta(days=k) for k in range(16)])
    folder = export.export_storm(STORM.id, out=toy.out)
    files = {name: read_strict(folder / name) for name in STORM_FILES}
    for name, kind in STORM_FILES.items():
        validate(kind, files[name])
    nights = by_night(files["nights.json"])
    assert (nights["12003"]["2099-09-10"]["est"], nights["12003"]["2099-09-10"]["official"]) == (None, None)
    assert nights["12001"]["2099-09-11"]["official"] is None
    restoration = files["restoration.json"]
    assert restoration["12001"]["official_day"] == restoration["13003"]["official_day"] == 4.0
    assert restoration["12001"]["est_lo"] < restoration["12001"]["est_hi"]
    assert restoration["13005"] == {"est_lo": 0.0, "est_hi": 0.0, "official_day": 0.0}
    assert restoration["13001"] == {"est_lo": None, "est_hi": None, "official_day": None}
    assert restoration["13003"]["est_lo"] is restoration["13003"]["est_hi"] is None
    for fips, county in files["exposure.json"].items():
        brackets = county["at"].values()
        if fips in ("13001", "13003"):  # never seen: unknown at every hour, never zero
            assert all(bracket is None for bracket in brackets)
        else:
            assert all(bracket is None or 0 <= bracket[0] <= bracket[1] <= 1 for bracket in brackets)
    claimable = {fips for fips, entry in restoration.items() if (entry["official_day"] or 0) > 0}
    assert files["claims.json"] and {claim["fips"] for claim in files["claims.json"]} <= claimable
    assert any("apply_overcount_rule" in note for note in files["meta.json"]["notes"])


def test_export_sample_is_offline(tmp_path, monkeypatch):
    install(monkeypatch, stand_ins(Calls()))
    rows = [("12071", "FL", 260_000, 280_000), ("12015", "FL", 120_000, 125_000), ("12021", "FL", 230_000, 250_000)]
    nights = [date(2022, 9, 20) + timedelta(days=k) for k in range(16)]
    est = {date(2022, 9, 28): 0.9, date(2022, 9, 29): 0.7, date(2022, 9, 30): 0.5, date(2022, 10, 1): 0.3,
           date(2022, 10, 2): 0.15, date(2022, 10, 3): 0.08}
    table = toy_table("ian2022", rows, nights, lambda f, n: "ok", lambda f, n: round(0.9 * est.get(n, 0.0), 4),
                      lambda f, n: est.get(n, 0.0))
    sample = tmp_path / "sample"
    sample.mkdir()
    table.to_parquet(sample / "county_nights_ian_sample.parquet", index=False)
    toy_predictions(table, lambda f, n: est.get(n, 0.0)).to_parquet(sample / "predictions_ian_sample.parquet",
                                                                    index=False)
    gpd.GeoDataFrame({"fips": [r[0] for r in rows], "name": ["Lee", "Charlotte", "Collier"],
                      "state": ["FL"] * 3, "housing_units": [r[2] for r in rows], "customers": [r[3] for r in rows]},
                     geometry=[box(-82.0, 26.3, -81.5, 26.8), box(-82.3, 26.8, -81.6, 27.0),
                               box(-81.8, 25.8, -80.9, 26.3)],
                     crs="EPSG:4326").to_file(sample / "counties_ian_sample.geojson", driver="GeoJSON")

    def no_census(states):
        raise AssertionError("the sample export must not touch Census files")

    monkeypatch.setattr(export, "SAMPLE", sample)
    monkeypatch.setattr(export, "load_counties", no_census)
    folder = export.export_sample(out=tmp_path / "data")
    assert folder == tmp_path / "data" / "ian2022_sample"
    for name, kind in STORM_FILES.items():
        validate(kind, read_strict(folder / name))
    meta = read_strict(folder / "meta.json")
    assert (meta["id"], meta["name"], meta["landfall"], meta["role"]) == (
        "ian2022_sample", "Ian (sample: Lee, Charlotte, Collier)", "2022-09-28", "main")
    assert meta["nights"][0] == "2022-09-26"  # Ian's baseline ends 2022-09-25
    assert [s["id"] for s in read_strict(tmp_path / "data" / "index.json")["storms"]] == ["ian2022_sample"]
    assert sorted(read_strict(folder / "nights.json")) == ["12015", "12021", "12071"]


def test_lockbox_storm_export_waits_for_the_lockbox_run(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "PROCESSED", tmp_path)
    with pytest.raises(export.LockboxClosedError):
        export.export_storm("milton2024", out=tmp_path / "out")


def test_range_always_contains_the_point(world):
    """A bias-corrected range can exclude its own point; the export folds the point into the range."""
    path = world.processed / "predictions_toy2099.parquet"
    fit = pd.read_parquet(path)
    ok = fit["status"] == "ok"
    fit.loc[ok, "lo"] = (fit.loc[ok, "est"] * 0.1).clip(upper=1)
    fit.loc[ok, "hi"] = (fit.loc[ok, "est"] * 0.5).clip(upper=1)  # a range entirely below its own point
    fit.to_parquet(path, index=False)
    nights = read_strict(export.export_storm(STORM.id, out=world.out, predictions=path) / "nights.json")
    checked = 0
    for records in nights.values():
        for rec in records:
            if rec["est"] is not None:
                assert rec["lo"] <= rec["est"] <= rec["hi"]
                checked += 1
    assert checked > 0
