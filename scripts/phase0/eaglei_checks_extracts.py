"""Phase 0 / eaglei: checks on the kept extracts and the three small files.

T2  run cadence; missing 15-minute stamps 2022-09-20..2022-10-20
    (national: no rows at all; Florida: no FL rows while other states have rows)
T3d Lee County (12071) in Ian: first runs past 10/50/80% of its MCC customers
T4  MCC.csv: byte-order mark, unpadded County_FIPS, Lee/Charlotte/Collier, 67 FL counties
T5  coverage_history.csv Florida rows; DQI.csv FEMA region 4 rows
T6  Lee % out at 01:30 local each day 2022-09-20..2022-10-20
    -> data/interim/eaglei_lee_0130_series.csv

Also writes data/interim/eaglei_extract_checks.json.

Run from the repo root, after eaglei_extract.py:
    uv run python -I scripts/phase0/eaglei_checks_extracts.py

Superseded for T6 (2026-11-06): T6 reads Lee at 01:30 EDT (05:30 UTC), but the satellite passes near 01:30 local
mean solar time (about 07:00 UTC over Lee). scripts/phase0/ian_lee.py uses each night's real pass time instead.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "eaglei"
INTERIM_DIR = REPO_ROOT / "data" / "interim"
MCC_CSV = RAW_DIR / "MCC.csv"
COVERAGE_CSV = RAW_DIR / "coverage_history.csv"
DQI_CSV = RAW_DIR / "DQI.csv"
FL_PARQUET = INTERIM_DIR / "eaglei_fl_2022-08-20_2022-10-25.parquet"
RUNS_PARQUET = INTERIM_DIR / "eaglei_2022_runs.parquet"
SERIES_CSV = INTERIM_DIR / "eaglei_lee_0130_series.csv"
OUT_JSON = INTERIM_DIR / "eaglei_extract_checks.json"

# Phase 0 conclusion (T3a-d): run_start_time is naive UTC.
EAGLEI_STAMP_TZ = "UTC"
LOCAL_TZ = "America/New_York"

LEE, CHARLOTTE, COLLIER = "12071", "12015", "12021"
# Florida's 67 counties: odd codes 001-133, except 025 (old Dade), plus 086 (Miami-Dade).
FL_COUNTY_FIPS = frozenset({f"12{n:03d}" for n in range(1, 134, 2) if n != 25} | {"12086"})

YEAR_START, YEAR_LAST_RUN = "2022-01-01 00:00:00", "2022-12-31 23:45:00"
WINDOW_START, WINDOW_LAST_RUN = "2022-09-20 00:00:00", "2022-10-20 23:45:00"
IAN_START, IAN_END_EXCLUSIVE = "2022-09-27 00:00:00", "2022-09-30 00:00:00"
LANDFALL_UTC = pd.Timestamp("2022-09-28 19:05", tz="UTC")
THRESHOLDS = (0.10, 0.50, 0.80)
PASS_LOCAL_TIME = dt.time(1, 30)
SERIES_DAYS = pd.date_range("2022-09-20", "2022-10-20", freq="D")
RUN_STEP = dt.timedelta(minutes=15)
MAX_PICK_LAG = dt.timedelta(minutes=60)
ROBUST_HALF_WINDOW = dt.timedelta(minutes=30)
RECOVERY_PCT = 10.0


def sql_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def json_default(obj: object) -> object:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, (pd.Timestamp, dt.datetime, dt.date)):
        return obj.isoformat()
    if isinstance(obj, (pd.Timedelta, dt.timedelta)):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"not JSON serialisable: {type(obj)}")


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.sql(f"CREATE VIEW fl AS SELECT * FROM read_parquet({sql_quote(str(FL_PARQUET))})")
    con.sql(f"CREATE VIEW runs AS SELECT * FROM read_parquet({sql_quote(str(RUNS_PARQUET))})")
    return con


def stamp_ranges(stamps: list[pd.Timestamp]) -> list[dict]:
    """Collapse sorted 15-minute stamps into [first, last] runs of consecutive stamps."""
    ranges: list[dict] = []
    for ts in stamps:
        if ranges and ts - ranges[-1]["last"] == RUN_STEP:
            ranges[-1] = {**ranges[-1], "last": ts, "n": ranges[-1]["n"] + 1}
        else:
            ranges.append({"first": ts, "last": ts, "n": 1})
    return ranges


def expected_stamps_sql(first: str, last: str) -> str:
    return (
        f"SELECT ts FROM generate_series(TIMESTAMP {sql_quote(first)}, TIMESTAMP {sql_quote(last)}, "
        "INTERVAL 15 MINUTE) AS g(ts)"
    )


def stamps(con: duckdb.DuckDBPyConnection, sql: str) -> list[pd.Timestamp]:
    return [pd.Timestamp(row[0]) for row in con.sql(sql).fetchall()]


def t2_cadence(con: duckdb.DuckDBPyConnection) -> dict:
    gaps = con.sql(
        """
        SELECT gap, count(*) AS n FROM (
            SELECT run_start_time - lag(run_start_time) OVER (ORDER BY run_start_time) AS gap FROM runs
        ) WHERE gap IS NOT NULL GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()
    off_grid = con.sql(
        "SELECT count(*) FROM runs WHERE date_trunc('minute', run_start_time) <> run_start_time "
        "OR minute(run_start_time) % 15 <> 0"
    ).fetchall()[0][0]
    missing_year = stamps(
        con,
        f"SELECT ts FROM ({expected_stamps_sql(YEAR_START, YEAR_LAST_RUN)}) "
        "WHERE ts NOT IN (SELECT run_start_time FROM runs) ORDER BY ts",
    )
    missing_national = stamps(
        con,
        f"SELECT ts FROM ({expected_stamps_sql(WINDOW_START, WINDOW_LAST_RUN)}) "
        "WHERE ts NOT IN (SELECT run_start_time FROM runs) ORDER BY ts",
    )
    missing_florida = stamps(
        con,
        f"""
        SELECT run_start_time FROM runs
        WHERE run_start_time BETWEEN TIMESTAMP {sql_quote(WINDOW_START)} AND TIMESTAMP {sql_quote(WINDOW_LAST_RUN)}
          AND run_start_time NOT IN (SELECT DISTINCT run_start_time FROM fl)
        ORDER BY 1
        """,
    )
    fl_rows_per_run = con.sql(
        f"""
        SELECT min(n), quantile_cont(n, 0.5), max(n) FROM (
            SELECT run_start_time, count(*) AS n FROM fl
            WHERE run_start_time BETWEEN TIMESTAMP {sql_quote(WINDOW_START)} AND TIMESTAMP {sql_quote(WINDOW_LAST_RUN)}
            GROUP BY 1)
        """
    ).fetchall()[0]
    return {
        "gap_counts_2022": [{"gap": str(g), "n": n} for g, n in gaps],
        "n_runs_off_15min_grid_2022": off_grid,
        "missing_stamps_2022_national": missing_year,
        "window": [WINDOW_START, WINDOW_LAST_RUN],
        "n_expected_window": int((pd.Timestamp(WINDOW_LAST_RUN) - pd.Timestamp(WINDOW_START)).total_seconds() // RUN_STEP.total_seconds()) + 1,
        "missing_window_national": missing_national,
        "missing_window_florida_only": stamp_ranges(missing_florida),
        "n_missing_window_florida_only": len(missing_florida),
        "fl_rows_per_present_run_window": dict(zip(("min", "median", "max"), fl_rows_per_run)),
    }


def lee_on_florida_runs(con: duckdb.DuckDBPyConnection, start: str, end_exclusive: str) -> pd.DataFrame:
    """Lee customers_out on every run that has Florida rows; absent Lee -> 0."""
    window = (
        f"run_start_time >= TIMESTAMP {sql_quote(start)} AND run_start_time < TIMESTAMP {sql_quote(end_exclusive)}"
    )
    return con.sql(
        f"""
        WITH fl_runs AS (SELECT DISTINCT run_start_time FROM fl WHERE {window}),
             lee AS (SELECT run_start_time, customers_out FROM fl WHERE fips_code = {sql_quote(LEE)} AND {window})
        SELECT r.run_start_time, coalesce(l.customers_out, 0) AS customers_out, l.customers_out IS NOT NULL AS lee_row
        FROM fl_runs r LEFT JOIN lee l USING (run_start_time)
        ORDER BY 1
        """
    ).df()


def t3d_ian(con: duckdb.DuckDBPyConnection, lee_mcc: int) -> dict:
    lee = lee_on_florida_runs(con, IAN_START, IAN_END_EXCLUSIVE).assign(
        pct_out=lambda d: 100.0 * d["customers_out"] / lee_mcc
    )
    crossings = {}
    for share in THRESHOLDS:
        hit = lee[lee["customers_out"] >= share * lee_mcc]
        first = pd.Timestamp(hit["run_start_time"].iloc[0]) if len(hit) else None
        crossings[f"{round(share * 100)}%"] = {
            "first_stamp": first,
            "if_utc_local_edt": None if first is None else first.tz_localize("UTC").tz_convert(LOCAL_TZ),
            "if_utc_hours_after_landfall": None
            if first is None
            else round((first.tz_localize("UTC") - LANDFALL_UTC).total_seconds() / 3600, 2),
            "customers_out": None if first is None else int(hit["customers_out"].iloc[0]),
        }
    peak = lee.loc[lee["customers_out"].idxmax()]
    change = lee["customers_out"].diff()
    worst = int(change.idxmin())
    one_run_drop = {
        "stamp": lee.loc[worst, "run_start_time"],
        "before": int(lee.loc[worst - 1, "customers_out"]),
        "at": int(lee.loc[worst, "customers_out"]),
        "after": int(lee.loc[worst + 1, "customers_out"]) if worst + 1 in lee.index else None,
    }
    hourly =lee[lee["run_start_time"].dt.minute.eq(0) & lee["run_start_time"].between("2022-09-28 06:00", "2022-09-29 06:00")]
    missing_fl = stamps(
        con,
        f"""
        SELECT run_start_time FROM runs
        WHERE run_start_time >= TIMESTAMP {sql_quote(IAN_START)} AND run_start_time < TIMESTAMP {sql_quote(IAN_END_EXCLUSIVE)}
          AND run_start_time NOT IN (SELECT DISTINCT run_start_time FROM fl) ORDER BY 1
        """,
    )
    return {
        "lee_mcc": lee_mcc,
        "n_florida_runs": len(lee),
        "n_runs_lee_absent": int((~lee["lee_row"]).sum()),
        "florida_missing_runs_in_window": missing_fl,
        "crossings": crossings,
        "peak": {"stamp": peak["run_start_time"], "customers_out": int(peak["customers_out"]), "pct_out": round(peak["pct_out"], 2)},
        "largest_one_run_drop": one_run_drop,
        "hourly_sep28_06_to_sep29_06": [
            {"stamp": r.run_start_time, "customers_out": int(r.customers_out), "pct_out": round(r.pct_out, 2)}
            for r in hourly.itertuples()
        ],
    }


def read_mcc() -> tuple[dict, pd.DataFrame]:
    raw = MCC_CSV.read_bytes()
    naive_header = pd.read_csv(MCC_CSV, nrows=0, encoding="utf-8").columns[0]
    table = pd.read_csv(MCC_CSV, encoding="utf-8-sig", dtype={"County_FIPS": str})
    is_total = table["County_FIPS"].str.strip().str.lower().eq("grand total")
    counties = table.loc[~is_total].assign(fips=lambda d: d["County_FIPS"].str.strip().str.zfill(5))
    facts = {
        "starts_with_utf8_bom": raw.startswith(b"\xef\xbb\xbf"),
        "first_bytes_hex": raw[:16].hex(" "),
        "crlf_line_endings": b"\r\n" in raw[:256],
        "header_if_read_as_plain_utf8": repr(naive_header),
        "columns_utf8_sig": table.columns.tolist(),
        "n_rows_total": len(table),
        "grand_total_rows": table.loc[is_total].to_dict(orient="records"),
        "raw_fips_length_counts": counties["County_FIPS"].str.len().value_counts().sort_index().to_dict(),
        "example_unpadded": counties["County_FIPS"].head(3).tolist(),
        "n_duplicate_fips": int(counties["fips"].duplicated().sum()),
        "sum_customers_vs_grand_total": [int(counties["Customers"].sum()), table.loc[is_total, "Customers"].tolist()],
    }
    return facts, counties


def t4_mcc(con: duckdb.DuckDBPyConnection) -> tuple[dict, dict[str, int]]:
    facts, counties = read_mcc()
    customers = dict(zip(counties["fips"], counties["Customers"].astype(int)))
    fl_mcc = {f for f in customers if f.startswith("12")}
    fl_outage_fips = {r[0] for r in con.sql("SELECT DISTINCT fips_code FROM fl").fetchall()}
    facts |= {
        "customers": {name: customers.get(fips) for name, fips in (("Lee", LEE), ("Charlotte", CHARLOTTE), ("Collier", COLLIER))},
        "n_fl_codes_in_mcc": len(fl_mcc),
        "fl_expected_missing_from_mcc": FL_COUNTY_FIPS - fl_mcc,
        "fl_mcc_codes_not_expected": fl_mcc - FL_COUNTY_FIPS,
        "fl_total_customers_mcc": sum(customers[f] for f in fl_mcc),
        "n_fl_fips_in_outage_extract": len(fl_outage_fips),
        "fl_outage_fips_missing_from_mcc": fl_outage_fips - fl_mcc,
        "fl_expected_absent_from_outage_extract": FL_COUNTY_FIPS - fl_outage_fips,
    }
    return facts, customers


def t5_coverage() -> dict:
    coverage = pd.read_csv(COVERAGE_CSV, dtype=str)
    florida = coverage.loc[coverage["state"].eq("FL")].assign(
        year_parsed=lambda d: pd.to_datetime(d["year"], format="%m/%d/%y").dt.year
    )
    dqi = pd.read_csv(DQI_CSV, dtype=str)
    return {
        "coverage_columns": coverage.columns.tolist(),
        "coverage_years_present": sorted(coverage["year"].unique().tolist()),
        "coverage_florida": florida.to_dict(orient="records"),
        "dqi_columns": dqi.columns.tolist(),
        "dqi_region_4": dqi.loc[dqi["fema"].eq("4")].to_dict(orient="records"),
    }


def pick_run(fl_runs: pd.DatetimeIndex, target: pd.Timestamp) -> tuple[pd.Timestamp | None, pd.Timedelta | None]:
    """Latest Florida-present run at or before target (None if lag exceeds MAX_PICK_LAG)."""
    position = fl_runs.searchsorted(target, side="right") - 1
    if position < 0:
        return None, None
    chosen = fl_runs[position]
    lag = target - chosen
    return (chosen, lag) if lag <= MAX_PICK_LAG else (None, lag)


def pct_of(value: float, lee_mcc: int) -> float:
    return np.nan if np.isnan(value) else round(100.0 * value / lee_mcc, 3)


def lee_at(fl_runs: pd.DatetimeIndex, lee: pd.Series, target: pd.Timestamp) -> float:
    chosen, _ = pick_run(fl_runs, target)
    return np.nan if chosen is None else float(lee.get(chosen, 0))


def lee_window_median(fl_runs: pd.DatetimeIndex, lee: pd.Series, target: pd.Timestamp) -> float:
    """Median Lee value (absent -> 0) over Florida-present runs within +-30 min of target."""
    near = fl_runs[(fl_runs >= target - ROBUST_HALF_WINDOW) & (fl_runs <= target + ROBUST_HALF_WINDOW)]
    return float(np.median([lee.get(ts, 0) for ts in near])) if len(near) else np.nan


def series_row(day: pd.Timestamp, fl_runs: pd.DatetimeIndex, lee: pd.Series, national: set, lee_mcc: int) -> dict:
    target_local = pd.Timestamp(dt.datetime.combine(day.date(), PASS_LOCAL_TIME)).tz_localize(LOCAL_TZ)
    target_stamp = target_local.tz_convert(EAGLEI_STAMP_TZ).tz_localize(None)
    chosen, lag = pick_run(fl_runs, target_stamp)
    value = np.nan if chosen is None else float(lee.get(chosen, 0))
    return {
        "local_date": day.date().isoformat(),
        "night_label": (day.date() - dt.timedelta(days=1)).isoformat(),
        "target_local": target_local.isoformat(),
        "target_stamp_utc": target_stamp.isoformat(),
        "chosen_run_stamp": None if chosen is None else chosen.isoformat(),
        "lag_minutes": None if lag is None else lag.total_seconds() / 60,
        "national_run_at_target": target_stamp in national,
        "florida_rows_at_target": chosen is not None and chosen == target_stamp,
        "lee_row_present": chosen is not None and chosen in lee.index,
        "customers_out": value,
        "mcc_customers": lee_mcc,
        "pct_out": pct_of(value, lee_mcc),
        "pct_out_median_runs_pm30min": pct_of(lee_window_median(fl_runs, lee, target_stamp), lee_mcc),
        "pct_out_if_stamps_were_eastern": pct_of(lee_at(fl_runs, lee, target_local.tz_localize(None)), lee_mcc),
    }


def t6_lee_0130(con: duckdb.DuckDBPyConnection, lee_mcc: int) -> tuple[pd.DataFrame, dict]:
    fl_runs = pd.DatetimeIndex(stamps(con, "SELECT DISTINCT run_start_time FROM fl ORDER BY 1"))
    lee_rows = con.sql(f"SELECT run_start_time, customers_out FROM fl WHERE fips_code = {sql_quote(LEE)}").df()
    lee = pd.Series(lee_rows["customers_out"].to_numpy(), index=pd.DatetimeIndex(lee_rows["run_start_time"]))
    national = set(stamps(con, "SELECT run_start_time FROM runs"))
    series = pd.DataFrame([series_row(day, fl_runs, lee, national, lee_mcc) for day in SERIES_DAYS])
    peak_idx = series["pct_out"].idxmax()
    after_peak = series.loc[peak_idx:]
    recovered = after_peak[after_peak["pct_out"] < RECOVERY_PCT]
    summary = {
        "stamp_tz_assumed": EAGLEI_STAMP_TZ,
        "peak_pct_out": series.loc[peak_idx, "pct_out"],
        "peak_local_date": series.loc[peak_idx, "local_date"],
        "peak_customers_out": series.loc[peak_idx, "customers_out"],
        "first_local_date_below_10pct_after_peak": None if recovered.empty else recovered["local_date"].iloc[0],
        "n_days_nan": int(series["pct_out"].isna().sum()),
        "n_days_lagged_pick": int((series["lag_minutes"].fillna(0) > 0).sum()),
        "max_abs_diff_vs_eastern_stamps_pctpts": float((series["pct_out"] - series["pct_out_if_stamps_were_eastern"]).abs().max()),
        "max_abs_diff_vs_pm30min_median_pctpts": float((series["pct_out"] - series["pct_out_median_runs_pm30min"]).abs().max()),
    }
    return series, summary


def main() -> int:
    for path in (FL_PARQUET, RUNS_PARQUET, MCC_CSV, COVERAGE_CSV, DQI_CSV):
        if not path.is_file():
            print(f"Missing {path}; run eaglei_extract.py first.", file=sys.stderr)
            return 1
    con = connect()
    t4, customers = t4_mcc(con)
    lee_mcc = customers[LEE]
    series, t6 = t6_lee_0130(con, lee_mcc)
    results = {"t2": t2_cadence(con), "t3d": t3d_ian(con, lee_mcc), "t4": t4, "t5": t5_coverage(), "t6": t6}
    series.to_csv(SERIES_CSV, index=False)
    OUT_JSON.write_text(json.dumps(results, indent=1, default=json_default))
    print(json.dumps(results, indent=1, default=json_default))
    print(series.to_string(index=False))
    print(f"wrote {SERIES_CSV.relative_to(REPO_ROOT)} and {OUT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
