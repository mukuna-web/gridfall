"""Rebuild the Task 2 fixtures from the real files (docs/plan.md, Task 2 recipe).

Run from the repo root: uv run python -I tests/fixtures/build_eaglei_fixtures.py
Needs the Phase 0 extracts in data/interim/ and MCC.csv / coverage_history.csv in data/raw/eaglei/.
"""

import re
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tests/fixtures"
FL = REPO / "data/interim/eaglei_fl_2022-08-20_2022-10-25.parquet"
IDA = REPO / "data/interim/eaglei_2021_ida_LA_MS_2021-08-01_2021-09-30.parquet"
URI = REPO / "data/interim/eaglei_2021_uri_TX_2021-01-20_2021-03-10.parquet"
# window: source, fips prefix, first stamp, last stamp (both included), expected rows
WINDOWS = {
    "A": (FL, "12", "2022-09-29 07:45:00", "2022-09-29 12:15:00", 1156),
    "B": (FL, "12", "2022-09-30 05:30:00", "2022-09-30 09:00:00", 783),
    "C": (FL, "12", "2022-09-15 06:45:00", "2022-09-15 10:45:00", 419),
    "D": (FL, "12", "2022-10-18 22:00:00", "2022-10-19 01:30:00", 440),
    "E": (FL, "12", "2022-10-17 12:00:00", "2022-10-17 16:00:00", 772),
    "F": (FL, "12", "2022-10-07 21:00:00", "2022-10-08 01:30:00", 829),
    "G": (FL, "12", "2022-09-17 12:30:00", "2022-09-17 17:00:00", 663),
    "H": (IDA, "22", "2021-08-30 16:00:00", "2021-08-30 19:00:00", 687),
    "I": (URI, "48", "2021-02-18 04:30:00", "2021-02-18 06:30:00", 1747),
}


def build_eaglei_small() -> None:
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    rows = []
    for name, (path, prefix, first, last, expected) in WINDOWS.items():
        got = con.execute(
            "select fips_code, county, state, customers_out, run_start_time from read_parquet(?) "
            "where left(fips_code, 2) = ? and run_start_time between cast(? as timestamp) and cast(? as timestamp)",
            [str(path), prefix, first, last],
        ).fetchall()
        if len(got) != expected:
            raise SystemExit(f"window {name}: {len(got)} rows, expected {expected}")
        rows.extend(got)
    rows.sort(key=lambda r: (r[4], r[0]))
    lines = ["fips_code,county,state,customers_out,run_start_time"]
    for fips, county, state, count, time in rows:
        lines.append(f"{fips},{county},{state},{'' if count is None else int(count)},{time:%Y-%m-%d %H:%M:%S}")
    (OUT / "eaglei_small.csv").write_bytes(("\n".join(lines) + "\n").encode())


def build_mcc_and_coverage() -> None:
    mcc = (REPO / "data/raw/eaglei/MCC.csv").read_bytes()
    lines = mcc.split(b"\r\n")
    (OUT / "mcc_small.csv").write_bytes(b"\r\n".join(lines[:3]) + b"\r\n" + lines[-1])
    cov = (REPO / "data/raw/eaglei/coverage_history.csv").read_bytes().split(b"\r\n")
    keep = [ln for ln in cov if ln.startswith(b"year,") or re.search(rb",(FL|LA|TX),", ln)]
    (OUT / "coverage_small.csv").write_bytes(b"\r\n".join(keep) + b"\r\n")


if __name__ == "__main__":
    build_eaglei_small()
    build_mcc_and_coverage()
