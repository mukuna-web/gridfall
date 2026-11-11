"""Task 7: leave-one-storm-out predictions, restore days and the scorecard (docs/plan.md, Week 4). Every table here
is synthetic; write_scorecard runs on two tiny tables written to tmp_path."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from blackout.evaluate import METHODS, SCORE_COLUMNS, loso, official_restore_day, scorecard, write_scorecard
from blackout.storms import Storm, get_storm
from blackout.table import TABLE_COLUMNS

NAN = float("nan")


def make_storm(storm_id: str, role: str = "main", landfall: date = date(2022, 9, 28)) -> Storm:
    baseline_end = landfall - timedelta(days=3)
    return Storm(storm_id, storm_id, None, landfall, baseline_end - timedelta(days=30), baseline_end,
                 landfall + timedelta(days=21), role, ("FL",))


STORMS = [
    make_storm("aaa2018", landfall=date(2018, 9, 14)),
    make_storm("bbb2020", landfall=date(2020, 8, 27)),
    make_storm("ccc2022"),
    make_storm("box2024", role="lockbox", landfall=date(2024, 10, 9)),
    make_storm("sss2021", role="stress", landfall=date(2021, 2, 15)),
]


# --- leave one storm out -----------------------------------------------------------------------------------------

class SpyPredictor:
    def __init__(self, trained_on: set[str]):
        self.trained_on = trained_on

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        seen = set(df["storm_id"])
        assert not seen & self.trained_on, f"predicting {seen} with a fit that saw {self.trained_on}"
        return np.full(len(df), 0.25)


def little_table(storm: Storm, counties: int = 3) -> pd.DataFrame:
    return pd.DataFrame([{"storm_id": storm.id, "fips": f"12{2 * k + 1:03d}", "night": storm.landfall,
                          "status": "ok", "pct_darker": 0.1 * k} for k in range(counties)])


def test_loso_never_sees_its_storm():
    df = pd.concat([little_table(s) for s in STORMS], ignore_index=True)
    before = df.copy()
    calls: list[set[str]] = []

    def spy_fit(train: pd.DataFrame) -> SpyPredictor:
        ids = set(train["storm_id"])
        calls.append(ids)
        return SpyPredictor(ids)

    out = loso(df, spy_fit, storms=STORMS)
    mains = {"aaa2018", "bbb2020", "ccc2022"}
    assert len(calls) == 3
    assert all(ids <= mains and len(ids) == 2 for ids in calls)  # never the lockbox or the stress storm
    assert {next(iter(mains - ids)) for ids in calls} == mains  # each main storm is held out once
    assert set(out["storm_id"]) == mains and len(out) == 9
    assert (out["pred_pct_out"] == 0.25).all()
    pd.testing.assert_frame_equal(df, before)


def test_loso_drops_the_held_out_storms_county_nights_from_other_tables():
    """Michael's baseline holds Florence's event nights for the shared states; they must not train Florence's fold."""
    a, b = STORMS[0], STORMS[1]
    shared_night = a.landfall
    rows_a = little_table(a).assign(official_pct_out=0.9)
    rows_b = pd.concat([little_table(b), little_table(a).assign(storm_id=b.id, official_pct_out=0.9)])
    rows_b = rows_b.assign(night=[b.landfall] * 3 + [shared_night] * 3)
    seen = {}

    class Spy:
        def __init__(self, train):
            seen[frozenset(train["storm_id"])] = set(zip(train["fips"], train["night"]))

        def predict(self, df):
            return np.zeros(len(df))

    loso(pd.concat([rows_a, rows_b], ignore_index=True), Spy, STORMS)
    fold_a = seen[frozenset({b.id})]
    assert not any(night == shared_night for _, night in fold_a)  # a's own county-nights, filed under b, are out
    assert any(night == b.landfall for _, night in fold_a)  # b's own nights stay


def test_loso_needs_two_main_storms():
    df = pd.concat([little_table(STORMS[0]), little_table(STORMS[3])], ignore_index=True)
    with pytest.raises(ValueError, match="two main storms"):
        loso(df, lambda train: SpyPredictor(set(train["storm_id"])), storms=STORMS)


# --- restore day -------------------------------------------------------------------------------------------------

def days(*values: float) -> pd.Series:
    return pd.Series(values, index=range(len(values)), dtype=float)


def test_official_restore_day_needs_24h():
    assert official_restore_day(days(0.8, 0.5, 0.08, 0.3, 0.09, 0.05)) == 4.0  # the dip on day 2 bounces back
    assert np.isnan(official_restore_day(days(0.8, 0.4, 0.05)))  # no later night to confirm day 2
    assert official_restore_day(days(0.05, 0.05, 0.7, 0.2, 0.1, 0.1)) == 4.0  # before the peak never counts
    assert official_restore_day(days(0.9, 0.05, 0.05, 0.9, 0.05, 0.05)) == 1.0  # the peak is the first max
    assert official_restore_day(days(0.8, 0.5, 0.08), threshold=0.5) == 1.0


def test_official_restore_day_skips_nan_nights():
    assert official_restore_day(days(0.8, NAN, 0.05, NAN, 0.07, 0.2)) == 2.0  # NaN does not break the stretch
    assert official_restore_day(days(0.6, 0.05, NAN, 0.3, 0.05, NAN, 0.06)) == 4.0  # nor count as restored
    assert official_restore_day(days(NAN, 0.6, 0.02, 0.01)) == 2.0
    assert official_restore_day(pd.Series([0.05, 0.8, 0.05], index=[2, 0, 3])) == 2.0  # order by day
    assert np.isnan(official_restore_day(days(NAN, NAN)))
    assert np.isnan(official_restore_day(pd.Series([], dtype=float)))


# --- scorecard ---------------------------------------------------------------------------------------------------

TOY = make_storm("toy2022")  # landfall 2022-09-28, window_end 2022-10-19 (day 21)
A = ("12001", 64, True, 1000.0)  # fips, wind band, covered, customers
B = ("12003", 50, True, 2000.0)
C = ("12005", 0, True, 500.0)  # not hit
D = ("13001", 34, False, 4000.0)  # hit, but its state's EAGLE-I coverage is too low
TOY_SPEC = [  # county, day after landfall, status, official % out, predicted % out
    (A, -5, "ok", 0.0, 0.5),  # baseline night: outside the event window
    (A, 0, "ok", 0.7, 0.6),
    (A, 1, "ok", 1.2, 0.7),  # over-count: dropped from scoring
    (A, 2, "ok", 0.6, 0.5),
    (A, 3, "ok", 0.05, 0.05),
    (A, 4, "ok", 0.04, 0.36),
    (A, 5, "ok", 0.03, 0.05),
    (A, 21, "ok", 0.02, 0.08),  # window_end is scored
    (A, 22, "ok", 0.0, 0.9),  # after window_end
    (B, 0, "ok", 0.1, 0.6),
    (B, 1, "ok", 0.5, 0.35),
    (B, 2, "cant_see", 0.3, NAN),
    (B, 3, "ok", 0.0, 0.0),
    (B, 4, "ok", 0.0, 0.0),
    (B, 5, "cant_see", 0.0, NAN),
    (B, 6, "cant_see", 0.0, NAN),
    (C, 0, "ok", 0.9, 0.1),
    *[(C, d, "cant_see", 0.0, NAN) for d in range(1, 7)],
    (D, 0, "ok", 0.9, 0.1),
    *[(D, d, "ok", 0.5, 0.5) for d in range(1, 4)],
    *[(D, d, "cant_see", 0.5, NAN) for d in range(4, 7)],
]


def toy_frame() -> pd.DataFrame:
    records = []
    for (fips, band, covered, customers), day, status, truth, pred in TOY_SPEC:
        records.append({"storm_id": TOY.id, "fips": fips, "night": TOY.landfall + timedelta(days=day),
                        "status": status, "official_pct_out": truth, "official_pct_out_30": truth,
                        "official_pct_out_90": truth, "pred_pct_out": pred, "customers": customers,
                        "wind_band": band, "covered": covered})
    return pd.DataFrame(records)


def test_scorecard_toy():
    toy = toy_frame()
    before = toy.copy()
    card = scorecard(toy, storms=[TOY])
    assert list(card.columns) == SCORE_COLUMNS and len(card) == 1
    s = card.iloc[0]
    assert s["storm_id"] == "toy2022"
    # Scored: A on days 0, 2, 3, 4, 5, 21 and B on days 0, 1, 3, 4. |error| sums to 0.60 + 0.65 = 1.25 over 10 rows.
    assert s["mae_pp"] == pytest.approx(12.5)
    assert s["rows_scored"] == 10 and s["overcount_dropped"] == 1
    # Night sums over scored rows: day 0 is 600 + 1200 estimated; day 1 is B alone, 0.5 x 2000 official.
    assert s["peak_total_est"] == pytest.approx(1800.0)
    assert s["peak_total_official"] == pytest.approx(1000.0)
    assert s["catch_rate_50"] == pytest.approx(2 / 3)  # official >= 0.5: A0, A2 caught; B1 missed
    assert s["false_alarm_50"] == pytest.approx(1 / 3)  # estimated >= 0.5: A0, A2 right; B0 wrong
    # A: official day 3, estimated day 5 (its day 3 bounces on day 4). B: both day 3. Median of 2 and 0.
    assert s["restore_day_err"] == pytest.approx(1.0)
    assert s["measurable_share"] == pytest.approx(15 / 21)  # A 7 of 7, B 4 of 7, D 4 of 7; C is not hit
    pd.testing.assert_frame_equal(toy, before)


def test_restore_day_error_ignores_predictions_on_blind_nights():
    """Can't see never becomes zero: a value a predictor leaves on a can't-see night (0.0 here) is not a reading, so it
    never moves the estimated restore day. Counted, B's 0.0 on day 2 would restore it on day 2 instead of day 3."""
    toy = toy_frame()
    blind_zero = toy.assign(pred_pct_out=np.where(toy["status"] == "ok", toy["pred_pct_out"], 0.0))
    s = scorecard(blind_zero, storms=[TOY]).iloc[0]
    assert s["restore_day_err"] == pytest.approx(1.0)
    assert s["mae_pp"] == pytest.approx(12.5) and s["rows_scored"] == 10


def test_scorecard_window_picks_the_truth_column():
    toy = toy_frame()
    a_day0 = (toy["fips"] == "12001") & (toy["night"] == TOY.landfall)
    toy = toy.assign(official_pct_out_30=np.where(a_day0, 0.9, toy["official_pct_out_30"]))
    s30 = scorecard(toy, window=30, storms=[TOY]).iloc[0]
    assert s30["mae_pp"] == pytest.approx(14.5)
    assert s30["peak_total_official"] == pytest.approx(1100.0)
    assert scorecard(toy, window=60, storms=[TOY]).iloc[0]["mae_pp"] == pytest.approx(12.5)
    assert scorecard(toy, window=90, storms=[TOY]).iloc[0]["mae_pp"] == pytest.approx(12.5)
    with pytest.raises(ValueError, match="window"):
        scorecard(toy, window=45, storms=[TOY])


def test_scorecard_storm_with_nothing_to_score():
    blind = toy_frame().assign(status="cant_see", pred_pct_out=NAN)
    s = scorecard(blind, storms=[TOY]).iloc[0]
    assert s["rows_scored"] == 0 and s["measurable_share"] == 0.0
    assert np.isnan([s["mae_pp"], s["peak_total_est"], s["peak_total_official"], s["restore_day_err"]]).all()


class ShortPredictor:
    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.zeros(1)


def test_bad_inputs_fail_loudly(tmp_path):
    with pytest.raises(ValueError, match="unknown storm ids"):
        scorecard(toy_frame(), storms=STORMS)  # toy2022 is not in that storm list
    with pytest.raises(ValueError, match="needs columns"):
        scorecard(toy_frame().drop(columns=["covered"]), storms=[TOY])
    two = pd.concat([little_table(s) for s in STORMS[:2]], ignore_index=True)
    with pytest.raises(ValueError, match="shape"):
        loso(two, lambda train: ShortPredictor(), storms=STORMS)
    synthetic_table(get_storm("ida2021"), 3).to_parquet(tmp_path / "county_nights_ian2022.parquet")
    with pytest.raises(ValueError, match="expected only ian2022"):
        write_scorecard(processed=tmp_path, out=tmp_path / "scorecard.md")


def test_scorecard_stress_storm_scores_every_county():
    stress = STORMS[4]
    rows = [{"storm_id": stress.id, "fips": fips, "night": stress.landfall, "status": "ok",
             "official_pct_out": truth, "official_pct_out_30": truth, "official_pct_out_90": truth,
             "pred_pct_out": pred, "customers": 1000.0, "wind_band": -1, "covered": True}
            for fips, truth, pred in (("48001", 0.4, 0.2), ("48003", 0.0, 0.1))]
    s = scorecard(pd.DataFrame(rows), storms=STORMS).iloc[0]
    assert s["rows_scored"] == 2
    assert s["mae_pp"] == pytest.approx(15.0)
    assert np.isnan(s["false_alarm_50"]) and np.isnan(s["catch_rate_50"])


# --- write_scorecard ---------------------------------------------------------------------------------------------

def synthetic_table(storm: Storm, seed: int, counties: int = 8) -> pd.DataFrame:
    """A county x night table in the real schema: angle and moon noise on calm nights, a decaying outage after
    landfall that % darker tracks, a fifth of the county-nights cloudy, and one over-count."""
    rng = np.random.default_rng(seed)
    records = []
    for night in storm.nights:
        day = (night - storm.landfall).days
        for k in range(counties):
            zenith, moon = rng.uniform(0, 65), (rng.uniform(0, 1) if rng.random() < 0.4 else 0.0)
            out = 0.9 * np.exp(-day / 4) * (k + 1) / counties if day >= 0 else 0.0
            out = 1.2 if (day, k) == (2, 4) else out
            seen = (k + day) % 5 != 0
            darker = 0.02 + 0.3 * (1 / np.cos(np.radians(zenith)) - 1) + 0.1 * moon + 0.8 * min(out, 1.0)
            customers = 1000.0 * (k + 1)
            records.append({
                "storm_id": storm.id, "fips": f"12{2 * k + 1:03d}", "night": night, "satellite": "VNP46A2",
                "pct_darker": darker + rng.normal(0, 0.01) if seen else NAN,
                "visible_share": 0.9 if seen else 0.1, "base_total": 50_000.0, "status": "ok" if seen else "cant_see",
                "sensor_zenith": zenith, "lunar_irradiance": moon,
                **{f"official_customers_out{w}": out * customers for w in ("", "_30", "_90")},
                **{f"official_pct_out{w}": out for w in ("", "_30", "_90")},
                "customers": customers, "housing_units": int(customers / 1.5),
                "pass_utc": pd.Timestamp(night + timedelta(days=1), tz="UTC") + pd.Timedelta(hours=7),
                "pass_source": "VNP46A1", "wind_band": (64, 50, 34, 0)[k % 4], "coverage": 0.97, "covered": True,
            })
    return pd.DataFrame(records)[TABLE_COLUMNS]


def test_write_scorecard_on_two_synthetic_tables(tmp_path):
    for storm_id, seed in (("ian2022", 1), ("ida2021", 2)):
        synthetic_table(get_storm(storm_id), seed).to_parquet(tmp_path / f"county_nights_{storm_id}.parquet")
    for locked in ("helene2024", "milton2024"):  # decoys: opening either would raise
        (tmp_path / f"county_nights_{locked}.parquet").write_bytes(b"lockbox decoy, never opened")
    out = tmp_path / "scorecard.md"
    combined = write_scorecard(processed=tmp_path, out=out)
    assert len(combined) == 2 * 3 * len(METHODS)  # storms x windows x methods
    assert set(combined["method"]) == set(METHODS)
    assert set(combined["window"]) == {30, 60, 90}
    assert set(combined["storm_id"]) == {"ian2022", "ida2021"}
    head = combined[combined["window"] == 60].set_index(["storm_id", "method"])
    assert head.loc[("ian2022", "isotonic"), "mae_pp"] < head.loc[("ian2022", "nothing"), "mae_pp"]
    assert head.loc[("ian2022", "isotonic"), "overcount_dropped"] == 1
    text = out.read_text()
    assert "DRAFT" in text and "Lockbox (Helene, Milton) not scored yet." in text
    assert "not committed" not in text  # the pass bar was committed (2f534f9); the draft must not say otherwise
    for heading in ("±60", "±30", "±90", "Noise", "Over-counts"):
        assert heading in text
    for missing in ("florence2018", "michael2018", "laura2020", "isaias2020", "idalia2023", "beryl2024"):
        assert missing in text
    assert "milton2024" not in text and "helene2024" not in text
    preds = pd.read_parquet(tmp_path / "loso_predictions.parquet")
    assert {"pred_pct_out", "pred_wind_only", "pred_nothing"} <= set(preds.columns)
    assert set(preds["storm_id"]) == {"ian2022", "ida2021"}
    assert preds.loc[preds["status"] != "ok", ["pred_pct_out", "pred_wind_only", "pred_nothing"]].isna().all().all()


@pytest.mark.parametrize(("scale", "expected"), [
    (1.0, "the curve made no at-least-half calls"),  # truth reaches 0.9, so the catch rate is a real 0%
    (0.4, "No scored county-night was officially at least half out"),  # truth tops out at 0.48
])
def test_write_scorecard_reads_plainly_when_half_out_has_nothing_to_count(tmp_path, scale, expected):
    """Real storms so far give a curve that tops out far below 50%, so false alarms have nothing to count, and a mild
    storm may have no county-night half out at all. The reading says so in words instead of printing "n/a"."""
    truth_columns = ("official_pct_out", "official_pct_out_30", "official_pct_out_90")
    for storm_id, seed in (("ian2022", 3), ("ida2021", 4)):
        t = synthetic_table(get_storm(storm_id), seed)
        noise = np.random.default_rng(seed).normal(0.0, 0.05, len(t))  # % darker unrelated to the outage
        blind = t.assign(pct_darker=np.where(t["status"] == "ok", noise, NAN), **{c: t[c] * scale for c in truth_columns})
        blind.to_parquet(tmp_path / f"county_nights_{storm_id}.parquet")
    combined = write_scorecard(processed=tmp_path, out=tmp_path / "scorecard.md")
    assert combined.loc[(combined["method"] == "isotonic") & (combined["window"] == 60), "false_alarm_50"].isna().all()
    reading = (tmp_path / "scorecard.md").read_text().split("## Plain-language reading")[1]
    sentence = next(line for line in reading.splitlines() if "at least half" in line)
    assert expected in sentence and "n/a" not in sentence


def test_write_scorecard_with_one_storm_says_so(tmp_path):
    synthetic_table(get_storm("ian2022"), 1).to_parquet(tmp_path / "county_nights_ian2022.parquet")
    out = tmp_path / "scorecard.md"
    combined = write_scorecard(processed=tmp_path, out=out)
    assert combined.empty and list(combined.columns) == ["method", "window", *SCORE_COLUMNS]
    text = out.read_text()
    assert "at least two" in text and "Lockbox (Helene, Milton) not scored yet." in text
    assert not (tmp_path / "loso_predictions.parquet").exists()


def test_diagnostics_hand_computed():
    from blackout.evaluate import PRED_COLUMNS, diagnostics

    storm = STORMS[2]
    nights = [storm.landfall + timedelta(days=k) for k in range(4)]
    # one county: official 0.9, 0.6, 0.2, 0.1; the curve ranks both half-out nights first and moves the same way
    frame = pd.DataFrame({"storm_id": storm.id, "fips": "12001", "night": nights, "status": "ok", "covered": True,
                          "wind_band": 64, "customers": 100.0, "official_pct_out": [0.9, 0.6, 0.2, 0.1]})
    preds = frame.assign(**{column: np.nan for column in PRED_COLUMNS.values()})
    preds = preds.assign(pred_pct_out=[0.7, 0.5, 0.2, 0.15], pred_nothing=0.0)
    diag = diagnostics(preds, STORMS).set_index("method")
    curve = diag.loc["isotonic"]
    assert curve["rows"] == 4
    assert curve["mae_pp"] == pytest.approx(8.75)  # (20 + 10 + 0 + 5) / 4
    assert curve["mae_big_pp"] == pytest.approx(8.75)  # every night is at least 10% out
    assert curve["bias_pp"] == pytest.approx(-6.25)
    assert curve["auc_50"] == pytest.approx(1.0)
    assert curve["change_spearman"] == pytest.approx(1.0)
    nothing = diag.loc["nothing"]
    assert nothing["auc_50"] == pytest.approx(0.5) and np.isnan(nothing["change_spearman"])
    assert "hybrid" not in diag.index  # a method with no predictions is left out, not scored as zero


def test_satellite_increment_hand_computed():
    from blackout.evaluate import satellite_increment

    storm = STORMS[2]
    nights = [storm.landfall + timedelta(days=k) for k in range(4)]
    frame = pd.DataFrame({"storm_id": storm.id, "fips": "12001", "night": nights, "status": "ok", "covered": True,
                          "wind_band": 64, "customers": 100.0, "official_pct_out": [0.9, 0.6, 0.05, 0.02],
                          "pred_pct_out": np.nan, "pred_hybrid": [0.8, 0.5, 0.1, 0.0],
                          "pred_wind_timing": [0.3, 0.3, 0.3, 0.3]})  # a flat guess ranks nothing
    inc = satellite_increment(frame, STORMS).set_index("storm_id")
    row = inc.loc[storm.id]
    assert row["rows_big"] == 2
    assert row["mae_big_hybrid"] == pytest.approx(10.0)  # (10 + 10) / 2 on the two nights >= 10% out
    assert row["mae_big_wind_timing"] == pytest.approx(45.0)  # (60 + 30) / 2
    assert row["mae_big_diff"] == pytest.approx(-35.0)
    assert row["auc_hybrid"] == pytest.approx(1.0) and row["auc_wind_timing"] == pytest.approx(0.5)
    assert inc.loc["all storms pooled", "auc_diff"] == pytest.approx(0.5)
    assert "pooled without Ida" not in inc.index  # only when Ida is among the scored storms


def test_every_method_scores_the_same_rows():
    from blackout.evaluate import PRED_COLUMNS, loso_predictions

    tables = [synthetic_table(STORMS[0], 1), synthetic_table(STORMS[1], 2), synthetic_table(STORMS[2], 3)]
    preds = loso_predictions(pd.concat(tables, ignore_index=True), STORMS)
    masks = {m: np.isfinite(preds[c].to_numpy(dtype=float)) for m, c in PRED_COLUMNS.items()}
    first = next(iter(masks.values()))
    assert all(np.array_equal(first, mask) for mask in masks.values())
    assert np.array_equal(first, (preds["status"] == "ok").to_numpy() & np.isfinite(preds["pct_darker"].to_numpy()))
