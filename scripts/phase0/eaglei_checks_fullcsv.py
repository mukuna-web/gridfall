"""Phase 0 / eaglei: checks that need the full EAGLE-I 2022 CSV.

T1  schema, customers_out range, zero rows, FIPS shape, duplicate keys
T3a DST start 2022-03-13: are there runs stamped 02:00-02:59?
T3b DST end 2022-11-06: duplicate (fips_code, run_start_time) at 01:00-01:59?
T3c July 2022 diurnal cycle of customers_out by stamp hour, per zone group

Prints a summary and writes data/interim/eaglei_fullcsv_checks.json so the
numbers stay auditable after the raw CSV is deleted.

Run from the repo root:
    uv run python -I scripts/phase0/eaglei_checks_fullcsv.py
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
RAW_CSV = REPO_ROOT / "data" / "raw" / "eaglei" / "eaglei_outages_2022.csv"
OUT_JSON = REPO_ROOT / "data" / "interim" / "eaglei_fullcsv_checks.json"

CSV_COLUMNS = {
    "fips_code": "VARCHAR",
    "county": "VARCHAR",
    "state": "VARCHAR",
    "customers_out": "BIGINT",
    "run_start_time": "TIMESTAMP",
}

DST_START_DAY = dt.date(2022, 3, 13)
DST_END_DAY = dt.date(2022, 11, 6)
JULY_START = "2022-07-01 00:00:00"
JULY_END_EXCLUSIVE = "2022-08-01 00:00:00"
RUN_STEP = np.timedelta64(15, "m")

# Zone groups by state FIPS prefix; the comment gives the July UTC offset.
ZONE_GROUPS = {
    "eastern": ("12", "13", "36", "37", "39", "42", "45", "51"),  # EDT -4: FL GA NY NC OH PA SC VA
    "central": ("01", "05", "17", "19", "22", "27", "28", "29", "40", "55"),  # CDT -5
    "mountain": ("08", "30", "35", "49", "56"),  # MDT -6: CO MT NM UT WY
    "arizona": ("04",),  # MST -7 (no DST)
    "pacific": ("06", "32", "41", "53"),  # PDT -7: CA NV OR WA
}
JULY_UTC_OFFSET_HOURS = {"eastern": -4, "central": -5, "mountain": -6, "arizona": -7, "pacific": -7}
# Florida's western panhandle is on Central time; Gulf (12045) is split, so drop it too.
FL_CENTRAL_FIPS = (
    "12005", "12013", "12033", "12045", "12059",
    "12063", "12091", "12113", "12131", "12133",
)


def sql_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def sql_list(items: tuple[str, ...]) -> str:
    return "(" + ", ".join(sql_quote(i) for i in items) + ")"


def json_default(obj: object) -> object:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (pd.Timestamp, dt.datetime, dt.date)):
        return obj.isoformat()
    if isinstance(obj, (pd.Timedelta, dt.timedelta)):
        return str(obj)
    raise TypeError(f"not JSON serialisable: {type(obj)}")


def records(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    return con.sql(sql).df().to_dict(orient="records")


def load_raw(con: duckdb.DuckDBPyConnection) -> None:
    columns = ", ".join(f"{sql_quote(k)}: {sql_quote(v)}" for k, v in CSV_COLUMNS.items())
    con.sql(
        f"CREATE TABLE raw AS SELECT * FROM read_csv({sql_quote(str(RAW_CSV))}, "
        f"header = true, columns = {{{columns}}})"
    )


def t1_schema(con: duckdb.DuckDBPyConnection) -> dict:
    path = sql_quote(str(RAW_CSV))
    sniffed = con.sql(
        f"DESCRIBE SELECT * FROM read_csv({path}, header = true, types = {{'fips_code': 'VARCHAR'}})"
    ).fetchall()
    sniff_row = con.sql(f"SELECT * FROM sniff_csv({path})").df().iloc[0].to_dict()
    dialect_keys = ("Delimiter", "Quote", "HasHeader", "NewLineDelimiter", "TimestampFormat", "DateFormat")
    stats = records(
        con,
        """
        SELECT count(*) AS n_rows,
               min(customers_out) AS min_customers_out,
               max(customers_out) AS max_customers_out,
               count(*) FILTER (WHERE customers_out = 0) AS n_zero,
               count(*) FILTER (WHERE customers_out < 0) AS n_negative,
               count(*) FILTER (WHERE customers_out IS NULL) AS n_null_customers_out,
               count(*) FILTER (WHERE run_start_time IS NULL) AS n_null_time,
               count(*) FILTER (WHERE fips_code IS NULL) AS n_null_fips,
               count(*) FILTER (WHERE NOT regexp_full_match(fips_code, '[0-9]{5}')) AS n_fips_not_5_digits,
               count(DISTINCT fips_code) AS n_fips,
               count(DISTINCT state) AS n_states,
               count(DISTINCT run_start_time) AS n_runs,
               min(run_start_time) AS min_time,
               max(run_start_time) AS max_time
        FROM raw
        """,
    )[0]
    return {
        "sniffed_types": {name: col_type for name, col_type, *_ in sniffed},
        "dialect": {k: sniff_row.get(k) for k in dialect_keys if k in sniff_row},
        "stats": stats,
        "fips_length_counts": records(con, "SELECT length(fips_code) AS len, count(*) AS n FROM raw GROUP BY 1 ORDER BY 1"),
        "states_for_fips_12": records(con, "SELECT state, count(*) AS n FROM raw WHERE starts_with(fips_code, '12') GROUP BY 1"),
        "fips_prefix_for_state_florida": records(
            con, "SELECT substr(fips_code, 1, 2) AS prefix, count(*) AS n FROM raw WHERE state = 'Florida' GROUP BY 1"
        ),
        "duplicate_keys_full_year": records(
            con,
            """
            SELECT count(*) AS n_keys_repeated, coalesce(sum(c), 0) AS n_rows_in_repeated_keys
            FROM (SELECT fips_code, run_start_time, count(*) AS c FROM raw GROUP BY ALL HAVING count(*) > 1)
            """,
        )[0],
        "example_rows": records(con, "SELECT * FROM raw WHERE starts_with(fips_code, '12071') ORDER BY run_start_time LIMIT 3"),
        "zero_rows_by_month": records(
            con,
            """
            SELECT month(run_start_time) AS month, count(*) AS n_rows,
                   count(*) FILTER (WHERE customers_out = 0) AS n_zero
            FROM raw GROUP BY 1 ORDER BY 1
            """,
        ),
        "zero_rows_top_states": records(
            con,
            """
            SELECT state, count(*) FILTER (WHERE customers_out = 0) AS n_zero, count(*) AS n_rows
            FROM raw GROUP BY 1 ORDER BY 2 DESC LIMIT 8
            """,
        ),
        "counties_per_run": records(
            con,
            """
            SELECT min(n) AS min_n, quantile_cont(n, 0.5) AS median_n, max(n) AS max_n
            FROM (SELECT run_start_time, count(*) AS n FROM raw GROUP BY 1)
            """,
        )[0],
    }


def runs_per_day(con: duckdb.DuckDBPyConnection, days: list[dt.date]) -> list[dict]:
    day_list = ", ".join(f"DATE {sql_quote(d.isoformat())}" for d in days)
    return records(
        con,
        f"""
        SELECT CAST(run_start_time AS DATE) AS day, count(DISTINCT run_start_time) AS n_runs, count(*) AS n_rows
        FROM raw WHERE CAST(run_start_time AS DATE) IN ({day_list}) GROUP BY 1 ORDER BY 1
        """,
    )


def runs_between(con: duckdb.DuckDBPyConnection, start: str, end: str) -> list[dict]:
    return records(
        con,
        f"""
        SELECT run_start_time, count(*) AS n_rows, count(DISTINCT fips_code) AS n_fips, sum(customers_out) AS total_out
        FROM raw
        WHERE run_start_time >= TIMESTAMP {sql_quote(start)} AND run_start_time < TIMESTAMP {sql_quote(end)}
        GROUP BY 1 ORDER BY 1
        """,
    )


def t3a_dst_start(con: duckdb.DuckDBPyConnection) -> dict:
    day = DST_START_DAY.isoformat()
    window = runs_between(con, f"{day} 00:00:00", f"{day} 05:00:00")
    in_gap = [r for r in window if pd.Timestamp(r["run_start_time"]).hour == 2]
    neighbours = [DST_START_DAY - dt.timedelta(days=1), DST_START_DAY, DST_START_DAY + dt.timedelta(days=1)]
    return {
        "runs_00_to_05": window,
        "n_runs_stamped_02xx": len(in_gap),
        "runs_per_day": runs_per_day(con, neighbours),
    }


def duplicate_keys_between(con: duckdb.DuckDBPyConnection, start: str, end: str) -> dict:
    return records(
        con,
        f"""
        SELECT count(*) AS n_keys_repeated, coalesce(sum(c), 0) AS n_rows_in_repeated_keys
        FROM (
            SELECT fips_code, run_start_time, count(*) AS c FROM raw
            WHERE run_start_time >= TIMESTAMP {sql_quote(start)} AND run_start_time < TIMESTAMP {sql_quote(end)}
            GROUP BY ALL HAVING count(*) > 1
        )
        """,
    )[0]


def t3b_dst_end(con: duckdb.DuckDBPyConnection) -> dict:
    day = DST_END_DAY.isoformat()
    neighbours = [DST_END_DAY - dt.timedelta(days=1), DST_END_DAY, DST_END_DAY + dt.timedelta(days=1)]
    return {
        "duplicates_01xx": duplicate_keys_between(con, f"{day} 01:00:00", f"{day} 02:00:00"),
        "duplicates_whole_day": duplicate_keys_between(con, f"{day} 00:00:00", f"{day} 23:59:59.999"),
        "runs_00_to_03": runs_between(con, f"{day} 00:00:00", f"{day} 03:00:00"),
        "runs_per_day": runs_per_day(con, neighbours),
    }


def zone_case_sql() -> str:
    eastern = f"WHEN st IN {sql_list(ZONE_GROUPS['eastern'])} AND fips_code NOT IN {sql_list(FL_CENTRAL_FIPS)} THEN 'eastern'"
    others = [f"WHEN st IN {sql_list(v)} THEN {sql_quote(k)}" for k, v in ZONE_GROUPS.items() if k != "eastern"]
    return "CASE " + " ".join([eastern, *others]) + " END"


def july_group_totals(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Per-run totals by zone group over every national July run (absent = 0)."""
    window = f"run_start_time >= TIMESTAMP {sql_quote(JULY_START)} AND run_start_time < TIMESTAMP {sql_quote(JULY_END_EXCLUSIVE)}"
    totals = con.sql(
        f"""
        WITH labelled AS (
            SELECT run_start_time, customers_out, {zone_case_sql()} AS zone_group
            FROM (SELECT *, substr(fips_code, 1, 2) AS st FROM raw WHERE {window})
        )
        SELECT run_start_time, zone_group, sum(customers_out) AS total_out
        FROM labelled WHERE zone_group IS NOT NULL GROUP BY ALL
        """
    ).df()
    runs = con.sql(f"SELECT DISTINCT run_start_time FROM raw WHERE {window} ORDER BY 1").df()["run_start_time"]
    wide = totals.pivot(index="run_start_time", columns="zone_group", values="total_out")
    return wide.reindex(index=runs, columns=list(ZONE_GROUPS)).fillna(0.0)


def diurnal_summary(wide: pd.DataFrame) -> dict:
    hours = wide.index.hour
    mean_by_hour = wide.groupby(hours).mean()
    sum_by_hour = wide.groupby(hours).sum()
    gaps_ok = wide.index.to_series().diff().eq(RUN_STEP).to_numpy()
    rises = wide.diff().clip(lower=0).loc[gaps_ok]
    onset_by_hour = rises.groupby(rises.index.hour).sum()
    summary = {}
    for group in wide.columns:
        peak = int(mean_by_hour[group].idxmax())
        summary[group] = {
            "peak_hour_stamp": peak,
            "peak_hour_if_stamps_utc_local": (peak + JULY_UTC_OFFSET_HOURS[group]) % 24,
            "trough_hour_stamp": int(mean_by_hour[group].idxmin()),
            "peak_onset_hour_stamp": int(onset_by_hour[group].idxmax()),
            "mean_out_per_run_by_hour": mean_by_hour[group].round(0).tolist(),
            "sum_out_by_hour": sum_by_hour[group].round(0).tolist(),
            "rise_by_hour": onset_by_hour[group].reindex(range(24), fill_value=0).round(0).tolist(),
        }
    return {"n_july_runs": len(wide), "runs_per_hour": wide.groupby(hours).size().tolist(), "groups": summary}


def print_summary(results: dict) -> None:
    t1 = results["t1"]
    print("T1 sniffed types:", t1["sniffed_types"])
    print("T1 dialect:", t1["dialect"])
    print("T1 stats:", t1["stats"])
    print("T1 fips lengths:", t1["fips_length_counts"])
    print("T1 states for fips 12*:", t1["states_for_fips_12"], "| prefixes for state=Florida:", t1["fips_prefix_for_state_florida"])
    print("T1 duplicate keys (year):", t1["duplicate_keys_full_year"])
    print("T1 example Lee rows:", t1["example_rows"])
    print("T1 zero rows by month:", t1["zero_rows_by_month"])
    print("T1 zero rows, top states:", t1["zero_rows_top_states"])
    print("T1 counties per run:", t1["counties_per_run"])
    t3a = results["t3a"]
    print("T3a runs stamped 02:xx on 2022-03-13:", t3a["n_runs_stamped_02xx"], "| runs/day:", t3a["runs_per_day"])
    for r in t3a["runs_00_to_05"]:
        print("   ", r)
    t3b = results["t3b"]
    print("T3b dup keys 01:xx 2022-11-06:", t3b["duplicates_01xx"], "| whole day:", t3b["duplicates_whole_day"])
    print("T3b runs/day:", t3b["runs_per_day"])
    for r in t3b["runs_00_to_03"]:
        print("   ", r)
    t3c = results["t3c"]
    print("T3c July runs:", t3c["n_july_runs"], "| runs per stamp hour:", t3c["runs_per_hour"])
    for group, g in t3c["groups"].items():
        print(
            f"T3c {group:9s} peak(mean/run) {g['peak_hour_stamp']:02d}  trough {g['trough_hour_stamp']:02d}  "
            f"peak-rise {g['peak_onset_hour_stamp']:02d}  -> local peak if UTC {g['peak_hour_if_stamps_utc_local']:02d}"
        )
    print("T3c eastern mean out per run by stamp hour:", t3c["groups"]["eastern"]["mean_out_per_run_by_hour"])


def main() -> int:
    if not RAW_CSV.is_file():
        print(f"Missing {RAW_CSV}; download it first.", file=sys.stderr)
        return 1
    con = duckdb.connect()
    load_raw(con)
    results = {
        "source": str(RAW_CSV.relative_to(REPO_ROOT)),
        "source_bytes": RAW_CSV.stat().st_size,
        "t1": t1_schema(con),
        "t3a": t3a_dst_start(con),
        "t3b": t3b_dst_end(con),
        "t3c": diurnal_summary(july_group_totals(con)),
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=1, default=json_default))
    print_summary(results)
    print(f"wrote {OUT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
