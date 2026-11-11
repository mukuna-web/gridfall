"""Phase 0 / tz2021: which clock does EAGLE-I run_start_time use? (2021 file)

An independent cross-check of the 2022 timezone tests, on the 2021 file and
different events. Every time below is in the file's own stamps ("file clock").

(a) DST start 2021-03-14: are there runs stamped 02:00-02:59?
    US wall-clock local time skips that hour.
(b) DST end 2021-11-07: duplicate (fips_code, run_start_time) at 01:00-01:59?
    US wall-clock local time repeats that hour.
(c) Winter Storm Uri: Texas (FIPS 48) total customers_out per run from
    2021-02-14 18:00 to 2021-02-15 18:00. ERCOT rotating outages began about
    01:25 CST = 07:25 UTC on 2021-02-15.
(d) Hurricane Ida: Orleans Parish (22071) customers_out per run. Landfall was
    about 16:55 UTC on 2021-08-29; New Orleans went fully dark early evening
    local, about 23:00-00:30 UTC.
(e) July 2021 customers_out by stamp hour for all-Eastern states
    (GA SC NC VA NY PA OH). Summer storm outages peak about 17-20 local.

Reads data/raw/eaglei_2021/eaglei_outages_2021.csv with DuckDB (fips_code as
VARCHAR). Prints a short summary; --json-out PATH writes every number to JSON.

Run from the repo root:
    uv run python -I scripts/phase0/tz2021_checks.py [--json-out PATH]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CSV = REPO_ROOT / "data" / "raw" / "eaglei_2021" / "eaglei_outages_2021.csv"

EXPECTED_COLUMNS = ("fips_code", "county", "state", "customers_out", "run_start_time")
CSV_TYPES = {
    "fips_code": "VARCHAR",
    "county": "VARCHAR",
    "state": "VARCHAR",
    "customers_out": "BIGINT",
    "run_start_time": "TIMESTAMP",
}
FIPS_REGEX = "[0-9]{5}"
INTEGER_REGEX = "[0-9]+"
# "YYYY-MM-DD HH:MM:SS" with no offset, "Z" or zone name.
PLAIN_STAMP_REGEX = "[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}"
RUN_FREQ = "15min"
RUN_STEP = pd.Timedelta(15, unit="m")
ONE_HOUR = pd.Timedelta(1, unit="h")
RUNS_PER_HOUR = 4
TOP_N = 5

# (a), (b) US DST in 2021.
DST_START_DAY = dt.date(2021, 3, 14)
DST_END_DAY = dt.date(2021, 11, 7)
DST_SKIPPED_HOUR = 2
DST_REPEATED_HOUR = 1
NO_DST_PREFIXES = ("04", "15", "60", "66", "69", "72", "78")  # AZ HI AS GU MP PR VI

# (c) Winter Storm Uri.
TX_PREFIX = "48"
URI_START, URI_END = "2021-02-14 18:00:00", "2021-02-15 18:00:00"  # inclusive
URI_PRE_END = "2021-02-15 00:00:00"  # pre-shed level: [URI_START, URI_PRE_END)
URI_ONSET_UTC = pd.Timestamp("2021-02-15 07:25:00")
URI_HYPOTHESES_H = {"UTC": 0, "US Eastern (EST, UTC-5)": -5, "county local (CST, UTC-6)": -6}
URI_SPAN = pd.Timedelta(2, unit="h")
URI_STEP_THRESHOLD = 50_000

# (d) Hurricane Ida.
LA_PREFIX = "22"
ORLEANS_FIPS = "22071"
IDA_START, IDA_END = "2021-08-29 00:00:00", "2021-08-30 12:00:00"  # inclusive
IDA_LANDFALL_UTC = pd.Timestamp("2021-08-29 16:55:00")
IDA_DARK_UTC = (pd.Timestamp("2021-08-29 23:00:00"), pd.Timestamp("2021-08-30 00:30:00"))
IDA_HYPOTHESES_H = {"UTC": 0, "US Eastern (EDT, UTC-4)": -4, "county local (CDT, UTC-5)": -5}
NEAR_TOTAL_SHARES = (0.5, 0.9, 0.98)

# (e) July diurnal cycle; all counties in these states are on Eastern time (EDT = UTC-4).
JULY_START, JULY_END = "2021-07-01 00:00:00", "2021-08-01 00:00:00"  # half-open
EASTERN_STATES = {"13": "GA", "45": "SC", "37": "NC", "51": "VA", "36": "NY", "42": "PA", "39": "OH"}
ELSA_DAYS = (dt.date(2021, 7, 7), dt.date(2021, 7, 10))  # Tropical Storm Elsa, inclusive
EDT_OFFSET_H = -4


def sql_quote(text: str) -> str:
    """Return text as a single-quoted SQL string literal."""
    return "'" + text.replace("'", "''") + "'"


def sql_ts(value: object) -> str:
    return f"TIMESTAMP {sql_quote(str(value))}"


def sql_in(items: tuple[str, ...] | list[str]) -> str:
    return "(" + ", ".join(sql_quote(i) for i in items) + ")"


def records(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    return con.sql(sql).df().to_dict(orient="records")


def to_jsonable(obj: object) -> object:
    """Recursively convert numpy/pandas values to plain JSON types (NaN -> None)."""
    if obj is pd.NaT or obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.datetime64):
        return pd.Timestamp(obj).isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if math.isnan(obj) else float(obj)
    if isinstance(obj, (pd.Timestamp, dt.datetime, dt.date)):
        return obj.isoformat()
    if isinstance(obj, (pd.Timedelta, dt.timedelta)):
        return str(obj)
    return obj


# ---------------------------------------------------------------- loading


def text_checks(con: duckdb.DuckDBPyConnection, csv_path: Path) -> dict:
    """Scan the raw text: header, FIPS shape, integer counts, zone-free stamps."""
    source = f"read_csv({sql_quote(str(csv_path))}, header = true, all_varchar = true)"
    names = tuple(row[0] for row in con.sql(f"DESCRIBE SELECT * FROM {source}").fetchall())
    if names != EXPECTED_COLUMNS:
        raise SystemExit(f"Unexpected header {names}; expected {EXPECTED_COLUMNS}")
    stats = records(
        con,
        f"""
        SELECT count(*) AS n_rows,
               count(*) FILTER (WHERE fips_code IS NULL
                   OR NOT regexp_full_match(fips_code, {sql_quote(FIPS_REGEX)})) AS n_fips_not_5_digits,
               count(*) FILTER (WHERE customers_out IS NULL
                   OR NOT regexp_full_match(customers_out, {sql_quote(INTEGER_REGEX)})) AS n_customers_out_not_integer,
               count(*) FILTER (WHERE run_start_time IS NULL
                   OR NOT regexp_full_match(run_start_time, {sql_quote(PLAIN_STAMP_REGEX)})) AS n_stamps_not_plain,
               min(length(run_start_time)) AS min_stamp_length,
               max(length(run_start_time)) AS max_stamp_length
        FROM {source}
        """,
    )[0]
    return {"header": list(names), **stats}


def load_typed(con: duckdb.DuckDBPyConnection, csv_path: Path) -> None:
    columns = ", ".join(f"{sql_quote(k)}: {sql_quote(v)}" for k, v in CSV_TYPES.items())
    con.sql(
        f"CREATE TABLE raw AS SELECT * FROM read_csv({sql_quote(str(csv_path))}, "
        f"header = true, columns = {{{columns}}})"
    )


def profile(con: duckdb.DuckDBPyConnection) -> dict:
    stats = records(
        con,
        """
        SELECT count(*) AS n_rows,
               count(DISTINCT run_start_time) AS n_runs,
               min(run_start_time) AS first_stamp,
               max(run_start_time) AS last_stamp,
               count(DISTINCT fips_code) AS n_fips,
               count(DISTINCT state) AS n_states,
               min(customers_out) AS min_customers_out,
               max(customers_out) AS max_customers_out,
               count(*) FILTER (WHERE customers_out IS NULL) AS n_null_customers_out,
               count(*) FILTER (WHERE minute(run_start_time) % 15 <> 0
                                   OR second(run_start_time) <> 0) AS n_rows_off_15min_grid,
               list_sort(list(DISTINCT run_start_time) FILTER (WHERE minute(run_start_time) % 15 <> 0
                                   OR second(run_start_time) <> 0)) AS off_grid_stamps
        FROM raw
        """,
    )[0]
    dups = records(
        con,
        """
        SELECT count(*) AS n_dup_pairs, coalesce(sum(n - 1), 0) AS n_extra_rows
        FROM (SELECT fips_code, run_start_time, count(*) AS n
              FROM raw GROUP BY ALL HAVING count(*) > 1)
        """,
    )[0]
    slots_in_year = 365 * 24 * RUNS_PER_HOUR
    return {**stats, "slots_in_2021": slots_in_year, "file_wide_duplicates": dups}


# ---------------------------------------------------------------- (a), (b) DST


def hour_bounds(day: dt.date, hour: int) -> tuple[str, str]:
    start = dt.datetime.combine(day, dt.time(hour))
    return sql_ts(start), sql_ts(start + dt.timedelta(hours=1))


def day_runs(con: duckdb.DuckDBPyConnection, day: dt.date) -> int:
    lo, hi = sql_ts(day), sql_ts(day + dt.timedelta(days=1))
    sql = f"SELECT count(DISTINCT run_start_time) FROM raw WHERE run_start_time >= {lo} AND run_start_time < {hi}"
    return con.sql(sql).fetchall()[0][0]


def hours_without_four_runs(con: duckdb.DuckDBPyConnection, day: dt.date) -> list[dict]:
    """Hours of `day` whose run count is not 4: a DST skip, repeat or shift shows up here."""
    lo, hi = sql_ts(day), sql_ts(day + dt.timedelta(days=1))
    return records(
        con,
        f"""
        WITH hours AS (SELECT range AS hour FROM range(24)),
             runs AS (SELECT hour(run_start_time) AS hour, count(DISTINCT run_start_time) AS n_runs
                      FROM raw WHERE run_start_time >= {lo} AND run_start_time < {hi} GROUP BY 1)
        SELECT hours.hour, coalesce(runs.n_runs, 0) AS n_runs
        FROM hours LEFT JOIN runs USING (hour)
        WHERE coalesce(runs.n_runs, 0) <> {RUNS_PER_HOUR}
        ORDER BY hours.hour
        """,
    )


def skipped_hour_stats(con: duckdb.DuckDBPyConnection, day: dt.date, hour: int) -> dict:
    lo, hi = hour_bounds(day, hour)
    row = records(
        con,
        f"""
        SELECT count(DISTINCT run_start_time) AS n_runs,
               count(*) AS n_rows,
               count(DISTINCT fips_code) AS n_fips,
               count(DISTINCT state) AS n_states,
               count(*) FILTER (WHERE substr(fips_code, 1, 2) NOT IN {sql_in(NO_DST_PREFIXES)})
                   AS n_rows_dst_observing_states,
               list_sort(list(DISTINCT strftime(run_start_time, '%H:%M'))) AS stamps
        FROM raw WHERE run_start_time >= {lo} AND run_start_time < {hi}
        """,
    )[0]
    return {"day": day.isoformat(), "hour": f"{hour:02d}:00-{hour:02d}:59", **row}


def repeated_hour_stats(con: duckdb.DuckDBPyConnection, day: dt.date, hour: int) -> dict:
    lo, hi = hour_bounds(day, hour)
    row = records(
        con,
        f"""
        WITH pairs AS (
            SELECT fips_code, run_start_time, count(*) AS n,
                   count(DISTINCT customers_out) AS n_values
            FROM raw WHERE run_start_time >= {lo} AND run_start_time < {hi}
            GROUP BY fips_code, run_start_time
        )
        SELECT coalesce(sum(n), 0) AS n_rows,
               count(*) AS n_pairs,
               count(*) FILTER (WHERE n > 1) AS n_dup_pairs,
               coalesce(sum(n - 1), 0) AS n_extra_rows,
               count(*) FILTER (WHERE n_values > 1) AS n_pairs_conflicting_values,
               count(DISTINCT run_start_time) AS n_runs,
               count(DISTINCT fips_code) AS n_fips,
               round(coalesce(sum(n), 0) / nullif(count(DISTINCT fips_code), 0), 3) AS rows_per_fips
        FROM pairs
        """,
    )[0]
    return {"day": day.isoformat(), "hour": f"{hour:02d}:00-{hour:02d}:59", **row}


def test_a_dst_start(con: duckdb.DuckDBPyConnection) -> dict:
    days = [DST_START_DAY + dt.timedelta(days=k) for k in (-1, 0, 1)]
    return {
        "question": "Runs stamped 02:00-02:59 on 2021-03-14? US wall-clock local time skips that hour.",
        "hour_02": [skipped_hour_stats(con, d, DST_SKIPPED_HOUR) for d in days],
        "runs_per_day": {d.isoformat(): day_runs(con, d) for d in days},
        "hours_without_4_runs": {d.isoformat(): hours_without_four_runs(con, d) for d in days},
    }


def test_b_dst_end(con: duckdb.DuckDBPyConnection) -> dict:
    days = [DST_END_DAY + dt.timedelta(days=k) for k in (-1, 0, 1)]
    return {
        "question": "Duplicate (fips_code, run_start_time) at 01:00-01:59 on 2021-11-07? "
        "US wall-clock local time repeats that hour.",
        "hour_01": [repeated_hour_stats(con, d, DST_REPEATED_HOUR) for d in days],
        "runs_per_day": {d.isoformat(): day_runs(con, d) for d in days},
        "hours_without_4_runs": {d.isoformat(): hours_without_four_runs(con, d) for d in days},
    }


# ---------------------------------------------------------------- 15-minute series


def slot_table(
    con: duckdb.DuckDBPyConnection, start: str, end: str, state_prefix: str, fips: str | None
) -> pd.DataFrame:
    """One row per 15-minute slot in [start, end] (file clock).

    state_value: sum over the state's non-null rows; NaN when the run has no rows for the state.
    county_value: the county's customers_out; 0 when the state reported but the county
    had no row (no row means zero out); NaN when the state did not report (scraper miss)
    or the county's row has an empty customers_out.
    """
    prefix = sql_quote(state_prefix)
    county = sql_quote(fips) if fips else "NULL"
    found = con.sql(
        f"""
        SELECT run_start_time AS stamp,
               count(*) AS n_rows_all,
               count(*) FILTER (WHERE starts_with(fips_code, {prefix})) AS n_state_rows,
               count(*) FILTER (WHERE starts_with(fips_code, {prefix}) AND customers_out IS NULL)
                   AS n_state_null_rows,
               sum(customers_out) FILTER (WHERE starts_with(fips_code, {prefix})) AS state_out,
               count(*) FILTER (WHERE fips_code = {county}) AS n_county_rows,
               sum(customers_out) FILTER (WHERE fips_code = {county}) AS county_out
        FROM raw
        WHERE run_start_time BETWEEN {sql_ts(start)} AND {sql_ts(end)}
        GROUP BY run_start_time
        """
    ).df()
    found = found.assign(stamp=pd.to_datetime(found["stamp"]).dt.as_unit("ns")).set_index("stamp").sort_index()
    grid = pd.date_range(start, end, freq=RUN_FREQ, name="stamp").as_unit("ns")
    table = found.reindex(grid)
    state_reported = table["n_state_rows"].fillna(0) > 0
    county_absent = table["n_county_rows"].fillna(0) == 0
    county_value = table["county_out"].where(~(county_absent & state_reported), 0.0)
    return table.assign(
        run_in_file=grid.isin(found.index),
        state_value=table["state_out"].where(state_reported),
        county_value=county_value,
        n_off_grid=len(found.index.difference(grid)),
    )


def rise_summary(values: pd.Series) -> dict:
    """Largest 15-minute and 60-minute increases of a series on the 15-minute grid."""
    rise_15 = values.diff()
    rise_60 = values - values.shift(RUNS_PER_HOUR)
    top_15 = [
        {
            "from_stamp": t - RUN_STEP,
            "to_stamp": t,
            "from_value": values[t - RUN_STEP],
            "to_value": values[t],
            "rise": r,
        }
        for t, r in rise_15.nlargest(TOP_N).items()
    ]
    top_60 = [
        {
            "from_stamp": t - ONE_HOUR,
            "to_stamp": t,
            "from_value": values[t - ONE_HOUR],
            "to_value": values[t],
            "rise": r,
        }
        for t, r in rise_60.nlargest(TOP_N).items()
    ]
    return {"top_15min_rises": top_15, "top_60min_rises": top_60}


def hourly_view(values: pd.Series) -> list[dict]:
    on_the_hour = values[values.index.minute == 0]
    return [{"stamp": t, "value": v} for t, v in on_the_hour.items()]


def series_view(values: pd.Series) -> list[dict]:
    return [{"stamp": t, "value": v} for t, v in values.items()]


# ---------------------------------------------------------------- (c) Uri


def onset_changes(values: pd.Series, onset_utc: pd.Timestamp, hypotheses: dict, span: pd.Timedelta) -> list[dict]:
    """Change over `span` after the onset each hypothesis puts in the file clock."""
    rows = []
    for label, hours in hypotheses.items():
        onset = onset_utc + pd.Timedelta(hours, unit="h")
        before, after = values.asof(onset), values.asof(onset + span)
        rows.append(
            {
                "hypothesis": label,
                "onset_in_file_clock": onset,
                "value_at_onset": before,
                "value_after_span": after,
                "change": after - before,
            }
        )
    return rows


def first_step_over(values: pd.Series, threshold: float) -> dict | None:
    """First 15-minute step larger than `threshold`."""
    steps = values.diff()
    big = steps[steps > threshold]
    if big.empty:
        return None
    t = big.index[0]
    return {"threshold": threshold, "from_stamp": t - RUN_STEP, "to_stamp": t, "rise": big.iloc[0]}


def test_c_uri(con: duckdb.DuckDBPyConnection) -> dict:
    table = slot_table(con, URI_START, URI_END, TX_PREFIX, None)
    tx = table["state_value"]
    pre = tx[tx.index < pd.Timestamp(URI_PRE_END)]
    return {
        "question": "Texas customers_out steep rise near 01:25 (CST clock) or near 07:25 (UTC clock)?",
        "n_slots": len(table),
        "n_slots_without_run": int((~table["run_in_file"]).sum()),
        "n_slots_without_tx_rows": int(tx.isna().sum()),
        "n_tx_rows_null_customers_out": int(table["n_state_null_rows"].sum()),
        "n_off_grid_stamps": int(table["n_off_grid"].iloc[0]),
        "first_15min_step_over_50k": first_step_over(tx, URI_STEP_THRESHOLD),
        "tx_counties_per_run": {
            "min": table["n_state_rows"].min(),
            "median": table["n_state_rows"].median(),
            "max": table["n_state_rows"].max(),
        },
        "pre_level_median": pre.median(),
        "pre_level_max": pre.max(),
        "window_max": {"stamp": tx.idxmax(), "value": tx.max()},
        "onset_change_2h": onset_changes(tx, URI_ONSET_UTC, URI_HYPOTHESES_H, URI_SPAN),
        **rise_summary(tx),
        "hourly": hourly_view(tx),
        "series_15min": series_view(tx),
    }


# ---------------------------------------------------------------- (d) Ida


def threshold_crossings(values: pd.Series, peak: float) -> list[dict]:
    rows = []
    for share in NEAR_TOTAL_SHARES:
        above = values[values >= share * peak]
        rows.append({"share_of_window_max": share, "first_stamp": above.index.min() if len(above) else None})
    return rows


def dark_window(values: pd.Series, peak: float, label: str, hours: int) -> dict:
    """Where Orleans stands at the start and end of the dark window a hypothesis implies."""
    shift = pd.Timedelta(hours, unit="h")
    start, end = IDA_DARK_UTC[0] + shift, IDA_DARK_UTC[1] + shift
    at_start, at_end = values.asof(start), values.asof(end)
    return {
        "hypothesis": label,
        "landfall_in_file_clock": IDA_LANDFALL_UTC + shift,
        "dark_window_in_file_clock": [start, end],
        "value_at_start": at_start,
        "value_at_end": at_end,
        "share_of_max_at_start": round(at_start / peak, 3),
        "share_of_max_at_end": round(at_end / peak, 3),
    }


def test_d_ida(con: duckdb.DuckDBPyConnection) -> dict:
    table = slot_table(con, IDA_START, IDA_END, LA_PREFIX, ORLEANS_FIPS)
    orleans = table["county_value"]
    peak = orleans.max()
    windows = [dark_window(orleans, peak, label, h) for label, h in IDA_HYPOTHESES_H.items()]
    return {
        "question": "When does Orleans Parish (22071) go (nearly) fully out in the file clock?",
        "n_slots": len(table),
        "n_slots_without_run": int((~table["run_in_file"]).sum()),
        "n_slots_without_la_rows": int(table["state_value"].isna().sum()),
        "n_la_rows_null_customers_out": int(table["n_state_null_rows"].sum()),
        "n_slots_orleans_null_customers_out": int(((table["n_county_rows"] > 0) & table["county_out"].isna()).sum()),
        "slots_orleans_no_row_la_present": [
            t for t in table.index[(table["n_county_rows"].fillna(0) == 0) & table["state_value"].notna()]
        ],
        "window_max": {"stamp": orleans.idxmax(), "value": peak},
        "crossings": threshold_crossings(orleans, peak),
        "hypothesis_windows": windows,
        **rise_summary(orleans),
        "la_total_hourly": hourly_view(table["state_value"]),
        "hourly": hourly_view(orleans),
        "series_15min": series_view(orleans),
    }


# ---------------------------------------------------------------- (e) diurnal


def peak_and_trough(profile: pd.Series) -> dict:
    return {"peak_hour": int(profile.idxmax()), "trough_hour": int(profile.idxmin())}


def test_e_diurnal(con: duckdb.DuckDBPyConnection) -> dict:
    per_run = con.sql(
        f"""
        SELECT run_start_time AS stamp, sum(customers_out) AS east_out, count(DISTINCT fips_code) AS n_fips,
               count(*) AS n_rows, count(*) FILTER (WHERE customers_out IS NULL) AS n_null_rows
        FROM raw
        WHERE run_start_time >= {sql_ts(JULY_START)} AND run_start_time < {sql_ts(JULY_END)}
          AND substr(fips_code, 1, 2) IN {sql_in(list(EASTERN_STATES))}
        GROUP BY run_start_time ORDER BY run_start_time
        """
    ).df()
    frame = per_run.assign(hour=per_run["stamp"].dt.hour, day=per_run["stamp"].dt.date)
    by_hour = frame.groupby("hour")["east_out"]
    median_day = frame.groupby(["day", "hour"])["east_out"].mean().unstack("hour").median()
    daily_peaks = frame.loc[frame.groupby("day")["east_out"].idxmax(), "hour"].value_counts().sort_index()
    no_elsa = frame[~frame["day"].between(*ELSA_DAYS)].groupby("hour")["east_out"].mean()
    return {
        "question": "Hour of day (file clock) of peak July customers_out in all-Eastern states.",
        "states": list(EASTERN_STATES.values()),
        "n_runs": len(frame),
        "n_days": frame["day"].nunique(),
        "n_rows": int(frame["n_rows"].sum()),
        "n_rows_null_customers_out": int(frame["n_null_rows"].sum()),
        "sum_by_hour": by_hour.sum().to_dict(),
        "runs_by_hour": by_hour.size().to_dict(),
        "mean_per_run_by_hour": by_hour.mean().round(1).to_dict(),
        "median_day_by_hour": median_day.round(1).to_dict(),
        "mean_per_run_by_hour_without_elsa": no_elsa.round(1).to_dict(),
        "daily_peak_hour_counts": daily_peaks.to_dict(),
        "peaks": {
            "sum": peak_and_trough(by_hour.sum()),
            "mean_per_run": peak_and_trough(by_hour.mean()),
            "median_day": peak_and_trough(median_day),
            "without_elsa": peak_and_trough(no_elsa),
            "daily_peak_hour_mode": int(daily_peaks.idxmax()),
        },
        "if_utc_peak_local_edt": (int(by_hour.sum().idxmax()) + EDT_OFFSET_H) % 24,
    }


# ---------------------------------------------------------------- main


def print_summary(result: dict) -> None:
    a, b, c, d, e = (result[k] for k in ("a_dst_start", "b_dst_end", "c_uri", "d_ida", "e_diurnal"))
    print("text checks:", result["text_checks"])
    print("profile:", {k: v for k, v in result["profile"].items()})
    print(
        "(a) 02:00-02:59 runs/rows per day:",
        [(h["day"], h["n_runs"], h["n_rows"], h["n_states"]) for h in a["hour_02"]],
        a["runs_per_day"],
    )
    print("(a) hours without 4 runs:", a["hours_without_4_runs"])
    print(
        "(b) 01:00-01:59 rows/dup pairs per day:",
        [(h["day"], h["n_rows"], h["n_dup_pairs"], h["rows_per_fips"]) for h in b["hour_01"]],
        b["runs_per_day"],
    )
    print("(b) hours without 4 runs:", b["hours_without_4_runs"])
    print("(c) Uri onset changes:", [(o["hypothesis"], o["change"]) for o in c["onset_change_2h"]])
    print("(c) Uri first big step:", c["first_15min_step_over_50k"])
    print("(c) Uri top 60-min rises:", [(r["to_stamp"], r["rise"]) for r in c["top_60min_rises"]])
    print("(d) Ida crossings:", d["crossings"], "max", d["window_max"])
    print(
        "(d) Ida dark windows:",
        [(w["hypothesis"], w["share_of_max_at_start"], w["share_of_max_at_end"]) for w in d["hypothesis_windows"]],
    )
    print("(d) Ida top 60-min rises:", [(r["to_stamp"], r["rise"]) for r in d["top_60min_rises"]])
    print("(e) diurnal peaks:", e["peaks"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-out", type=Path, default=None, help="write every number to this JSON file")
    args = parser.parse_args()
    if not RAW_CSV.is_file():
        print(f"Missing {RAW_CSV}; download it first.", file=sys.stderr)
        return 1
    con = duckdb.connect()
    result = {"source": str(RAW_CSV.relative_to(REPO_ROOT)), "text_checks": text_checks(con, RAW_CSV)}
    load_typed(con, RAW_CSV)
    result = {
        **result,
        "profile": profile(con),
        "a_dst_start": test_a_dst_start(con),
        "b_dst_end": test_b_dst_end(con),
        "c_uri": test_c_uri(con),
        "d_ida": test_d_ida(con),
        "e_diurnal": test_e_diurnal(con),
    }
    clean = to_jsonable(result)
    print_summary(clean)
    if args.json_out is not None:
        args.json_out.write_text(json.dumps(clean, indent=2))
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
