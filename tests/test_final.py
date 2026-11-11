"""Task 9: the pass-bar checks, the agreement statistic, strict JSON, the pure verdict, the one-shot lockbox run and
its guard against a second opening (synthetic data; test plan §5.1)."""

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from blackout import final
from blackout.storms import Storm


def storm(sid: str, landfall: date, role: str = "main") -> Storm:
    return Storm(id=sid, name=sid, atcf_id=None, landfall=landfall, baseline_start=landfall - timedelta(days=12),
                 baseline_end=landfall - timedelta(days=3), window_end=landfall + timedelta(days=8), role=role,
                 states=("FL",), landfall_utc=f"{landfall}T18:00Z")


MAIN = [storm("a2020", date(2020, 9, 10)), storm("b2021", date(2021, 9, 10)), storm("c2022", date(2022, 9, 10))]
LOCK = [storm("lock2024", date(2024, 9, 10), role="lockbox"), storm("lock2025", date(2025, 9, 10), role="lockbox")]
STORMS = [*MAIN, *LOCK]


def world(s: Storm, seed: int, counties: int = 24) -> pd.DataFrame:
    """Hit counties lose 60% for three nights after landfall, then restore; darkening tracks it with noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(counties):
        band = 64 if c < counties // 2 else 0
        for night in s.nights:
            day = (night - s.landfall).days
            out = {0: 0.6, 1: 0.45, 2: 0.25}.get(day, 0.0) * (band == 64)
            rows.append({"storm_id": s.id, "fips": f"12{c:03d}", "night": night, "status": "ok", "covered": True,
                         "pct_darker": out + rng.normal(0, 0.05), "sensor_zenith": 20.0, "lunar_irradiance": 0.5,
                         "visible_share": 0.95, "base_total": 50_000.0, "wind_band": band, "customers": 10_000.0,
                         "official_pct_out": out, "official_pct_out_30": out, "official_pct_out_90": out,
                         "pass_utc": pd.Timestamp(night + timedelta(days=1), tz="UTC") + pd.Timedelta(hours=7)})
    return pd.DataFrame(rows)


def cloud_over(table: pd.DataFrame, s: Storm, counties: int, days: int = 7) -> pd.DataFrame:
    """A copy where the first `counties` hit counties can't be seen from landfall to landfall + days."""
    hit = sorted(table.loc[table["wind_band"] >= final.HIT_BAND, "fips"].unique())[:counties]
    blind = (table["fips"].isin(hit) & (table["night"] >= s.landfall)
             & (table["night"] <= s.landfall + timedelta(days=days))).to_numpy()
    return table.assign(status=np.where(blind, "cant_see", table["status"]),
                        pct_darker=np.where(blind, np.nan, table["pct_darker"]))


class StubPredictor:
    """perfect: official on ok rows; flat: 0.3 on ok rows; wind: 0.05 where the wind band is above 0."""

    def __init__(self, mode: str) -> None:
        self.mode = mode

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if self.mode == "perfect":
            values = df["official_pct_out"].to_numpy(dtype=float)
        elif self.mode == "flat":
            values = np.full(len(df), 0.3)
        else:
            values = np.where(df["wind_band"].to_numpy() > 0, 0.05, 0.0)
        return np.where((df["status"] == "ok").to_numpy(), values, np.nan)


class StubRanges:
    def interval(self, est):
        est = np.asarray(est, dtype=float)
        return np.clip(est - 0.1, 0.0, 1.0), np.clip(est + 0.1, 0.0, 1.0)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({"pred_from": [None], "pred_to": [None], "rows": [0], "lo_offset": [-0.1], "hi_offset": [0.1]})


def stub_fits(monkeypatch, isotonic: str = "perfect", hybrid: str = "flat") -> None:
    """Replace every fit run_final calls with a stub predictor, so a run takes a second and the verdict is known."""
    from blackout import hybrid as hybrid_mod
    from blackout import model, ranges

    monkeypatch.setattr(model, "fit_translation", lambda train, storms=None, final=False: StubPredictor(isotonic))
    monkeypatch.setattr(model.WindOnly, "fit", staticmethod(lambda train, storms=None, final=False: StubPredictor("wind")))
    monkeypatch.setattr(hybrid_mod, "fit_hybrid", lambda train, storms=None, final=False: StubPredictor(hybrid))
    monkeypatch.setattr(hybrid_mod, "fit_wind_timing", lambda train, storms=None, final=False: StubPredictor("wind"))
    monkeypatch.setattr(ranges, "fit_ranges", lambda preds, *args, **kwargs: StubRanges())


def synthetic_processed(monkeypatch, tmp_path: Path, tables: dict[str, pd.DataFrame] | None = None) -> Path:
    """Write every storm's table into tmp_path and point table_path and load_storms at the synthetic world."""
    import blackout.table as table_mod
    from blackout import evaluate, model

    tables = tables or {s.id: world(s, k) for k, s in enumerate(STORMS)}
    for s in STORMS:
        tables[s.id].to_parquet(tmp_path / f"county_nights_{s.id}.parquet", index=False)
    monkeypatch.setattr(table_mod, "PROCESSED", tmp_path)
    for module in (final, model, evaluate):
        monkeypatch.setattr(module, "load_storms", lambda: STORMS)
    return tmp_path


def passes(flag: bool) -> dict:
    return {w: {"storm_id": "x", "window": w, "passes": flag} for w in (60, 30, 90)}


def test_load_tables_uses_each_storms_own_satellite(monkeypatch, tmp_path):
    noaa = Storm(id="n2024", name="n", atcf_id=None, landfall=date(2024, 7, 8), baseline_start=date(2024, 6, 5),
                 baseline_end=date(2024, 7, 5), window_end=date(2024, 7, 29), role="main", states=("TX",),
                 satellite="VJ146A2")
    import blackout.table as table_mod

    monkeypatch.setattr(table_mod, "PROCESSED", tmp_path)
    monkeypatch.setattr(final, "table_path", table_mod.table_path)
    pd.DataFrame({"storm_id": ["n2024"], "satellite": ["VJ146A2"]}).to_parquet(tmp_path / "county_nights_n2024.parquet")
    pd.DataFrame({"storm_id": ["n2024"], "satellite": ["VNP46A2"]}).to_parquet(
        tmp_path / "county_nights_n2024_vnp46a2.parquet")
    assert final.load_tables([noaa])["satellite"].tolist() == ["VJ146A2"]
    assert final.load_tables([noaa], "VNP46A2")["satellite"].tolist() == ["VNP46A2"]


def test_first_difference_agreement_ignores_shared_decay():
    nights = [date(2022, 9, 10) + timedelta(days=k) for k in range(8)]
    decay = np.linspace(0.8, 0.1, 8)
    rng = np.random.default_rng(0)
    rows = pd.DataFrame({"fips": "12001", "night": nights, "official_pct_out": decay,
                         "pred_pct_out": decay + rng.normal(0, 0.001, 8)})
    rho, pairs = final.first_difference_agreement(rows, "official_pct_out")
    assert pairs == 7
    # Both fall every night, so levels agree perfectly, but the night-to-night changes are only noise.
    assert abs(rho) < 0.9
    steps = np.array([0.8, 0.5, 0.45, 0.2, 0.17, 0.1, 0.06, 0.0])
    matched = rows.assign(official_pct_out=steps, pred_pct_out=0.9 * steps + 0.01)  # same changes, scaled
    assert final.first_difference_agreement(matched, "official_pct_out")[0] == pytest.approx(1.0)
    assert np.isnan(final.first_difference_agreement(rows.iloc[:1], "official_pct_out")[0])


def test_pass_bar_check_reads_each_condition(monkeypatch):
    monkeypatch.setattr(final, "load_storms", lambda: STORMS)
    rows = world(LOCK[0], 1)
    good = rows.assign(pred_pct_out=rows["official_pct_out"] * 0.95, pred_wind_only=0.05 * (rows["wind_band"] > 0))
    result = final.pass_bar_check(good, LOCK[0], 60)
    assert result["beats_wind_only"] and result["agreement_ok"] and result["restore_ok"] and result["passes"]
    assert result["mae_pp_curve"] < result["mae_pp_wind_only"]
    flat = rows.assign(pred_pct_out=0.3, pred_wind_only=0.05 * (rows["wind_band"] > 0))
    worse = final.pass_bar_check(flat, LOCK[0], 60)
    assert not worse["beats_wind_only"] and not worse["passes"]


def test_satellite_test_edge_rules():
    row = {"storm_id": "lock2024", "rows_big": 40, "rows_half": 12, "mae_big_hybrid": 20.0, "mae_big_wind_timing": 25.0,
           "mae_big_diff": -5.0, "auc_hybrid": 0.9, "auc_wind_timing": 0.8, "auc_diff": 0.1}
    both = {**row, "storm_id": "lock2025"}
    verdict, detail, _ = final.satellite_test([row, both], ["lock2024", "lock2025"])
    assert verdict == "yes" and detail["lock2024"]["passes"]
    # too few half-out rows: the AUC condition is not evaluable and the test rests on the error condition
    few_half = {**both, "rows_half": 3, "auc_diff": -0.2}
    verdict, detail, _ = final.satellite_test([row, few_half], ["lock2024", "lock2025"])
    assert verdict == "yes" and detail["lock2025"]["auc_evaluable"] is False and detail["lock2025"]["passes"]
    # too few rows >= 10% out: not evaluable; the verdict covers the other storm and says so
    verdict, detail, _ = final.satellite_test([row, {**both, "rows_big": 4}], ["lock2024", "lock2025"])
    assert verdict == "yes (on the evaluable storm only)" and detail["lock2025"]["evaluable"] is False
    # a missing storm is the same; a worse hybrid fails
    verdict, _, _ = final.satellite_test([{**row, "mae_big_diff": 2.0}], ["lock2024", "lock2025"])
    assert verdict == "no"
    assert final.satellite_test([], ["lock2024"])[0] == "not evaluable"
    assert final.satellite_test([row, {**both, "auc_diff": -0.1}], ["lock2024", "lock2025"])[0] == "partial"


def test_satellite_test_reads_required_keys_strictly():
    """LB-37: a row without rows_half raises instead of silently dropping the AUC condition."""
    row = {"storm_id": "lock2024", "rows_big": 40, "rows_half": 12, "mae_big_hybrid": 20.0, "mae_big_wind_timing": 25.0,
           "mae_big_diff": -5.0, "auc_hybrid": 0.9, "auc_wind_timing": 0.8, "auc_diff": 0.1}
    for key in ("rows_half", "auc_diff", "mae_big_diff", "rows_big"):
        with pytest.raises(KeyError, match=key):
            final.satellite_test([{k: v for k, v in row.items() if k != key}], ["lock2024"])


def test_verdict_table():
    """LB-08: the committed rule, the drop rule's note and "no verdict" when nothing is evaluable."""
    kept, dropped = {"dropped": False, "share": 0.9}, {"dropped": True, "share": 0.4}
    assert final.verdict({"lock2024": passes(True), "lock2025": passes(True)}) == "pass"
    assert final.verdict({"lock2024": passes(True), "lock2025": passes(False)}) == "partial"
    assert final.verdict({"lock2024": passes(False), "lock2025": passes(False)}) == "fail"
    drop = {"lock2024": kept, "lock2025": dropped}
    assert final.verdict({"lock2024": passes(True), "lock2025": passes(False)}, drop) == \
        "pass (covers lock2024 alone; lock2025 dropped by the drop rule)"
    assert final.verdict({"lock2024": passes(False), "lock2025": passes(True)}, drop) == \
        "fail (covers lock2024 alone; lock2025 dropped by the drop rule)"
    assert final.verdict({"lock2024": passes(True), "lock2025": passes(True)},
                         {"lock2024": dropped, "lock2025": dropped}).startswith("no verdict")
    assert final.verdict({"lock2024": {"note": "table missing"}, "lock2025": {"note": "table missing"}}) == \
        "no verdict (lock2024 not scored: table missing; lock2025 not scored: table missing)"
    assert final.verdict({}) == "no verdict"
    assert final.verdict({"lock2024": passes(True), "lock2025": {"note": "table missing"}}) == \
        "pass (covers lock2024 alone; lock2025 not scored: table missing)"
    # window keys are strings after a JSON round trip; the inputs are never modified
    saved = json.loads(json.dumps({"lock2024": passes(True), "lock2025": passes(False)}))
    before = json.dumps(saved)
    assert final.verdict(saved, drop) == "pass (covers lock2024 alone; lock2025 dropped by the drop rule)"
    assert json.dumps(saved) == before and drop == {"lock2024": kept, "lock2025": dropped}


def test_strict_load_refuses_a_missing_main_table(monkeypatch, tmp_path):
    import blackout.table as table_mod

    monkeypatch.setattr(table_mod, "PROCESSED", tmp_path)
    monkeypatch.setattr(final, "table_path", table_mod.table_path)
    pd.DataFrame({"storm_id": ["a2020"]}).to_parquet(tmp_path / "county_nights_a2020.parquet")
    with pytest.raises(FileNotFoundError, match="b2021"):
        final.load_tables(MAIN[:2], strict=True)
    assert len(final.load_tables(MAIN[:2])) == 1


def test_shared_county_nights_are_dropped_from_final_training():
    train = pd.DataFrame({"fips": ["12001", "12001", "12003"], "night": [date(2024, 9, 1), date(2024, 9, 2), date(2024, 9, 1)]})
    held = pd.DataFrame({"fips": ["12001"], "night": [date(2024, 9, 2)], "official_pct_out": [0.9]})
    kept, dropped = final.drop_shared_county_nights(train, held)
    assert dropped == 1 and len(kept) == 2 and (kept["night"] != date(2024, 9, 2)).all()


def test_strict_json_writes_null_for_nan(tmp_path):
    path = tmp_path / "x.json"
    final.write_json(path, {"a": float("nan"), "b": [np.float64(np.inf), np.int64(3)], "c": np.bool_(True)})
    assert json.loads(path.read_text()) == {"a": None, "b": [None, 3], "c": True}


def test_predictions_frame_blanks_unseen_rows():
    class Ranges:
        def interval(self, est):
            return est - 0.1, est + 0.1

    table = pd.DataFrame({"storm_id": "a2020", "fips": ["12001", "12003"], "night": [date(2020, 9, 10)] * 2,
                          "status": ["ok", "cant_see"]})
    out = final.predictions_frame(table, np.array([0.5, 0.7]), Ranges())
    assert out.loc[0, "est"] == 0.5 and out.loc[0, "lo"] == pytest.approx(0.4)
    assert np.isnan(out.loc[1, "est"]) and np.isnan(out.loc[1, "lo"]) and np.isnan(out.loc[1, "hi"])


def test_run_final_scores_the_lockbox_once(monkeypatch, tmp_path):
    synthetic_processed(monkeypatch, tmp_path)
    result = final.run_final(processed=tmp_path)
    assert set(result["pass_bar"]) == {"lock2024", "lock2025"} and result["verdict"] in ("pass", "partial", "fail")
    assert set(result["hybrid"]) == {"lock2024", "lock2025"}
    assert set(result["drop_rule"]) == {"lock2024", "lock2025"}
    assert not any(d["dropped"] for d in result["drop_rule"].values())
    for s in STORMS:
        preds = pd.read_parquet(tmp_path / f"predictions_{s.id}.parquet")
        assert list(preds.columns) == ["storm_id", "fips", "night", "status", "est", "lo", "hi"]
        assert preds["est"].between(0, 1).all()
    scores = pd.read_parquet(tmp_path / "scorecard_final.parquet")
    assert set(scores["storm_id"]) == {"lock2024", "lock2025"} and set(scores["window"]) == {30, 60, 90}
    assert {"isotonic", "hybrid", "wind_only", "nothing", "wind_timing"} <= set(scores["method"])
    saved = json.loads((tmp_path / "lockbox_result.json").read_text())
    assert saved["verdict"] == result["verdict"]
    text = "\n".join(final.render_lockbox(saved))
    assert "## Lockbox: Helene and Milton, scored once" in text
    assert f"Pass-bar verdict (pre-registered isotonic curve): {saved['verdict'].upper()}" in text
    assert "does the satellite add to wind + timing?" in text and "lock2024" in text
    assert {r["storm_id"] for r in saved["satellite_increment"]} >= {"lock2024", "lock2025", "all storms pooled"}
    assert saved["satellite_test"]["verdict"] in ("yes", "yes (on the evaluable storm only)", "partial", "no", "not evaluable")
    assert saved["provenance"]["training_tables"][0]["storm_id"] == "a2020"
    assert set(saved["provenance"]["code_sha256_16"]) >= {"model.py", "hybrid.py", "ranges.py"}
    # In this world the satellite tracks the outage closely, so the hybrid should clear the bar on both storms.
    assert all(saved["hybrid"][s][str(60)]["beats_wind_only"] for s in ("lock2024", "lock2025"))
    marker = json.loads((tmp_path / "lockbox_opened.json").read_text())
    assert set(marker) >= {"opened_at_utc", "git_head", "reopen_reason"} and marker["reopen_reason"] is None


def test_verdict_follows_the_isotonic_curve_and_hybrid_is_separate(monkeypatch, tmp_path):
    """LB-36: `pass_bar` is the curve, `hybrid` the hybrid, and the satellite increment comes from `pred_hybrid`."""
    synthetic_processed(monkeypatch, tmp_path)
    stub_fits(monkeypatch, isotonic="perfect", hybrid="flat")
    first = final.run_final(processed=tmp_path)
    assert first["verdict"] == "pass"
    assert not any(first["hybrid"][sid][60]["passes"] for sid in ("lock2024", "lock2025"))
    increment = {r["storm_id"]: r for r in first["satellite_increment"]}
    assert all(increment[sid]["mae_big_hybrid"] > 0 for sid in ("lock2024", "lock2025"))
    stub_fits(monkeypatch, isotonic="flat", hybrid="perfect")
    other = tmp_path / "again"
    other.mkdir()
    synthetic_processed(monkeypatch, other)
    second = final.run_final(processed=other)
    assert second["verdict"] == "fail"
    assert all(second["hybrid"][sid][60]["passes"] for sid in ("lock2024", "lock2025"))
    increment = {r["storm_id"]: r for r in second["satellite_increment"]}
    assert all(increment[sid]["mae_big_hybrid"] == 0 for sid in ("lock2024", "lock2025"))


def test_satellite_test_reads_real_increment_rows(monkeypatch, tmp_path):
    """LB-37: both fake locked storms have enough rows for both conditions, and the recorded rows reproduce the
    verdict; a row without rows_half raises."""
    synthetic_processed(monkeypatch, tmp_path)
    stub_fits(monkeypatch, isotonic="flat", hybrid="perfect")
    result = final.run_final(processed=tmp_path)
    increment = {r["storm_id"]: r for r in result["satellite_increment"]}
    assert all(increment[sid]["rows_big"] >= final.MIN_BIG_ROWS and increment[sid]["rows_half"] >= final.MIN_HALF_ROWS
               for sid in ("lock2024", "lock2025"))
    verdict, per_storm, _ = final.satellite_test(result["satellite_increment"], ["lock2024", "lock2025"])
    assert all(per_storm[sid]["auc_evaluable"] for sid in ("lock2024", "lock2025"))
    assert verdict == result["satellite_test"]["verdict"] == "yes"
    assert per_storm == result["satellite_test"]["per_storm"]
    broken = [{k: v for k, v in r.items() if k != "rows_half"} for r in result["satellite_increment"]]
    with pytest.raises(KeyError, match="rows_half"):
        final.satellite_test(broken, ["lock2024", "lock2025"])


def test_run_final_applies_drop_rule(monkeypatch, tmp_path):
    """LB-10: a locked storm whose hit counties mostly stay under cloud for a week is dropped, left out of the
    verdict, and named in it."""
    tables = {s.id: world(s, k) for k, s in enumerate(STORMS)}
    tables["lock2025"] = cloud_over(tables["lock2025"], LOCK[1], counties=7)  # 5 of 12 hit counties get an ok night
    synthetic_processed(monkeypatch, tmp_path, tables)
    stub_fits(monkeypatch, isotonic="perfect", hybrid="flat")
    result = final.run_final(processed=tmp_path)
    assert result["drop_rule"]["lock2025"]["dropped"] is True
    assert result["drop_rule"]["lock2025"]["share"] == pytest.approx(5 / 12, abs=0.001)
    assert result["drop_rule"]["lock2024"]["dropped"] is False
    assert result["verdict"] == "pass (covers lock2024 alone; lock2025 dropped by the drop rule)"
    saved = json.loads((tmp_path / "lockbox_result.json").read_text())
    assert saved["verdict"] == result["verdict"] and saved["drop_rule"]["lock2025"]["dropped"] is True


def test_lockbox_refuses_a_second_opening(monkeypatch, tmp_path):
    """LB-13: a folder holding lockbox_result.json refuses before any table is read; a reopen with a reason writes a
    new, timestamped result and leaves the first byte-identical; a first run marks the opening before the first
    locked read."""
    synthetic_processed(monkeypatch, tmp_path)
    stub_fits(monkeypatch)
    marker = tmp_path / "lockbox_opened.json"
    reads = []
    real_read = pd.read_parquet

    def spy(path, *args, **kwargs):
        reads.append((Path(path).name, marker.exists()))
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", spy)
    first = final.run_final(processed=tmp_path)
    locked_reads = [seen for name, seen in reads if name.startswith("county_nights_lock")]
    assert locked_reads and all(locked_reads), "the opening marker must exist before any locked table is read"
    result_path = tmp_path / "lockbox_result.json"
    frozen = result_path.read_bytes()
    reads.clear()
    with pytest.raises(final.LockboxOpenedError, match="--reopen"):
        final.run_final(processed=tmp_path)
    assert reads == [], "a refused run must not read any table"
    with pytest.raises(ValueError, match="reopen_reason"):
        final.run_final(processed=tmp_path, reopen_reason="   ")
    again = final.run_final(processed=tmp_path, reopen_reason="re-check the drop rule after the fix")
    assert result_path.read_bytes() == frozen
    written = sorted(tmp_path.glob("lockbox_result_*.json"))
    assert len(written) == 1 and written[0].name == again["reopen"]["result"]
    saved = json.loads(written[0].read_text())
    assert saved["reopen"]["reason"] == "re-check the drop rule after the fix" and saved["verdict"] == first["verdict"]
    outputs = tmp_path / again["reopen"]["outputs"]
    assert (outputs / "predictions_lock2024.parquet").exists() and (outputs / "scorecard_final.parquet").exists()
    assert hashlib.sha256((tmp_path / "predictions_lock2024.parquet").read_bytes()).hexdigest() == \
        hashlib.sha256((outputs / "predictions_lock2024.parquet").read_bytes()).hexdigest()


def test_opening_paths_never_overwrite(tmp_path):
    only_marker = tmp_path / "m"
    only_marker.mkdir()
    (only_marker / "lockbox_opened.json").write_text("{}")
    # a crashed first run left only the marker: the refusal must name the file that exists, not the missing result
    with pytest.raises(final.LockboxOpenedError, match="lockbox_opened.json exists"):
        final.opening_paths(only_marker)
    with pytest.raises(FileNotFoundError, match="nothing to reopen"):
        final.opening_paths(tmp_path / "empty", reopen_reason="why")
    (tmp_path / "lockbox_result.json").write_text("{}")
    now = pd.Timestamp("2026-11-09T10:00:00Z")
    paths = final.opening_paths(tmp_path, reopen_reason="why", now=now)
    assert paths["result"].name == "lockbox_result_20261109T100000Z.json"
    assert paths["folder"].name == "reopen_20261109T100000Z"
    paths["result"].write_text("{}")
    with pytest.raises(FileExistsError):
        final.opening_paths(tmp_path, reopen_reason="why", now=now)


def test_run_final_reads_table_processed_at_call_time(monkeypatch, tmp_path):
    """`blackout lockbox` passes no folder, so run_final must resolve table.PROCESSED when it is called, never bind the
    real data/processed at import: a monkeypatched folder receives the whole run."""
    synthetic_processed(monkeypatch, tmp_path)
    stub_fits(monkeypatch)
    result = final.run_final()
    assert (tmp_path / "lockbox_result.json").exists() and (tmp_path / "lockbox_opened.json").exists()
    assert result["verdict"] in ("pass", "partial", "fail")
    assert all((tmp_path / f"predictions_{s.id}.parquet").exists() for s in STORMS)


def synthetic_record(result: dict, result_path: Path) -> dict:
    tables = [{"storm_id": s.id, "role": s.role, "table": f"county_nights_{s.id}.parquet", "newer_than_run": False}
              for s in [*STORMS, *[storm(f"m{k}", date(2019, 9, 1)) for k in range(5)],
                        storm("stress2021", date(2021, 2, 15), role="stress")]]
    return {"result_file": result_path.name, "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "run_at_utc": result["provenance"]["run_at_utc"], "git_head": result["provenance"]["git_head"],
            "environment": {k: "0" for k in ("python", "numpy", "pandas", "scikit-learn", "scipy", "pyarrow")},
            "tables": tables, "cross_check_tables": [], "rebuilt_after_run": False,
            "predictions": [{"storm_id": s.id, "minutes_from_run": 0.05} for s in STORMS],
            "drop_rule": {s.id: {"dropped": False, "share": 1.0} for s in LOCK},
            "customers_check": {"available": True, "per_storm": {s.id: {"counties": 12, "differ": 0, "match": True}
                                                                  for s in LOCK}}}


def test_integrity_checks_and_render_integrity(monkeypatch, tmp_path):
    """S1a: every offline check passes on a consistent record and renders as pass; a changed verdict renders as fail."""
    synthetic_processed(monkeypatch, tmp_path)
    stub_fits(monkeypatch)
    final.run_final(processed=tmp_path)
    result_path = tmp_path / "lockbox_result.json"
    saved = json.loads(result_path.read_text())
    saved["provenance"]["working_tree_dirty"] = False  # the developer's tree is not under test here
    record = synthetic_record(saved, result_path)
    checks = final.integrity_checks(saved, record, repo=tmp_path / "no-git", frozen=result_path)
    by_id = {c["id"]: c["passed"] for c in checks}
    assert set(by_id) >= {"LB-45", "LB-44", "LB-41a", "LB-41b", "LB-41c", "LB-41d", "LB-41e", "LB-36", "LB-37", "LB-40",
                          "LB-43"}
    assert by_id.pop("LB-41c") is False  # three fake main storms, not the eight the plan names: the check bites
    assert by_id.pop("LB-41a") is None and by_id.pop("LB-41b") is None  # no git history under tmp_path
    assert all(passed is True for passed in by_id.values()), by_id
    text = "\n".join(final.render_integrity(record, checks))
    assert text.startswith("### S1a Integrity of the recorded opening")
    assert text.count("| fail |") == 1 and text.count("| not checked |") == 2 and text.count("| pass |") == len(by_id)
    tampered = {**saved, "verdict": "fail"}  # the perfect-curve stub earns "pass"
    broken = final.integrity_checks(tampered, record, repo=tmp_path / "no-git", frozen=result_path)
    assert [c["id"] for c in broken if c["passed"] is False] == ["LB-41c", "LB-40"]
    assert "| LB-40 the verdict follows the committed rule, drop rule included | fail |" in \
        "\n".join(final.render_integrity(record, broken))
    stale = {**record, "result_sha256": "0" * 64}
    assert [c["id"] for c in final.integrity_checks(saved, stale, repo=tmp_path, frozen=result_path)
            if c["passed"] is False] == ["LB-45", "LB-41c"]


def test_dirty_tree_counts_as_disclosed_only_inside_d20(tmp_path):
    """LB-41d: a dirty working tree at the run passes only when the decision log's D-20 entry names it; the words
    appearing before D-20, or with no D-20 at all, do not count."""
    result = {"provenance": {"git_head": None, "working_tree_dirty": True, "code_sha256_16": {},
                             "training_tables": []}}
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    log = repo / "docs/decision-log.md"

    def lb41d() -> bool | None:
        return {c["id"]: c["passed"] for c in final._check_provenance(result, repo)}["LB-41d"]

    assert lb41d() is False, "no decision log at all"
    log.write_text("## D-12\n`working_tree_dirty` will be checked later.\n")
    assert lb41d() is False, "the words appear, but there is no D-20 entry"
    log.write_text("## D-12\nworking_tree_dirty: true\n\n## D-20\nNothing about the tree.\n")
    assert lb41d() is False, "the words appear before D-20, not inside it"
    log.write_text("## D-12\n\n## 2026-11-09: D-20, integrity\n`working_tree_dirty: true`, disclosed.\n")
    assert lb41d() is True
