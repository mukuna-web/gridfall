"""Phase 0 / eaglei: cut the two extracts we keep from the EAGLE-I 2022 CSV.

Reads data/raw/eaglei/eaglei_outages_2022.csv with DuckDB (fips_code as
VARCHAR, never as a number) and writes to data/interim/:

* eaglei_fl_2022-08-20_2022-10-25.parquet
    Every Florida row (fips_code starting '12') with run_start_time in
    [2022-08-20 00:00, 2022-10-26 00:00), in the file's own stamps.
* eaglei_2022_runs.parquet
    One row per run_start_time in 2022: n_rows, n_counties,
    total_customers_out (national).

Run from the repo root:
    uv run python -I scripts/phase0/eaglei_extract.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CSV = REPO_ROOT / "data" / "raw" / "eaglei" / "eaglei_outages_2022.csv"
INTERIM_DIR = REPO_ROOT / "data" / "interim"
FL_PARQUET = INTERIM_DIR / "eaglei_fl_2022-08-20_2022-10-25.parquet"
RUNS_PARQUET = INTERIM_DIR / "eaglei_2022_runs.parquet"

FL_FIPS_PREFIX = "12"
FL_WINDOW_START = "2022-08-20 00:00:00"
FL_WINDOW_END_EXCLUSIVE = "2022-10-26 00:00:00"

# Expected header, in order. fips_code is forced to VARCHAR everywhere.
CSV_COLUMNS = {
    "fips_code": "VARCHAR",
    "county": "VARCHAR",
    "state": "VARCHAR",
    "customers_out": "BIGINT",
    "run_start_time": "TIMESTAMP",
}


def sql_quote(text: str) -> str:
    """Return text as a single-quoted SQL string literal."""
    return "'" + text.replace("'", "''") + "'"


def outages_source(csv_path: Path) -> str:
    """read_csv() expression with the expected names and explicit types."""
    columns = ", ".join(f"{sql_quote(k)}: {sql_quote(v)}" for k, v in CSV_COLUMNS.items())
    return f"read_csv({sql_quote(str(csv_path))}, header = true, columns = {{{columns}}})"


def assert_header(con: duckdb.DuckDBPyConnection, csv_path: Path) -> None:
    """Fail fast if the file's header is not the one we expect."""
    sniffed = con.sql(
        f"DESCRIBE SELECT * FROM read_csv({sql_quote(str(csv_path))}, header = true, "
        "types = {'fips_code': 'VARCHAR'})"
    ).fetchall()
    names = [row[0] for row in sniffed]
    if names != list(CSV_COLUMNS):
        raise SystemExit(f"Unexpected header {names}; expected {list(CSV_COLUMNS)}")


def write_florida_extract(con: duckdb.DuckDBPyConnection, source: str) -> int:
    con.sql(
        f"""
        COPY (
            SELECT fips_code, county, state, customers_out, run_start_time
            FROM {source}
            WHERE starts_with(fips_code, {sql_quote(FL_FIPS_PREFIX)})
              AND run_start_time >= TIMESTAMP {sql_quote(FL_WINDOW_START)}
              AND run_start_time <  TIMESTAMP {sql_quote(FL_WINDOW_END_EXCLUSIVE)}
            ORDER BY run_start_time, fips_code
        ) TO {sql_quote(str(FL_PARQUET))} (FORMAT parquet)
        """
    )
    return con.sql(f"SELECT count(*) FROM read_parquet({sql_quote(str(FL_PARQUET))})").fetchall()[0][0]


def write_runs_summary(con: duckdb.DuckDBPyConnection, source: str) -> int:
    con.sql(
        f"""
        COPY (
            SELECT run_start_time,
                   count(*)                  AS n_rows,
                   count(DISTINCT fips_code) AS n_counties,
                   CAST(sum(customers_out) AS BIGINT) AS total_customers_out
            FROM {source}
            GROUP BY run_start_time
            ORDER BY run_start_time
        ) TO {sql_quote(str(RUNS_PARQUET))} (FORMAT parquet)
        """
    )
    return con.sql(f"SELECT count(*) FROM read_parquet({sql_quote(str(RUNS_PARQUET))})").fetchall()[0][0]


def main() -> int:
    if not RAW_CSV.is_file():
        print(f"Missing {RAW_CSV}; download it first.", file=sys.stderr)
        return 1
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    assert_header(con, RAW_CSV)
    source = outages_source(RAW_CSV)
    fl_rows = write_florida_extract(con, source)
    n_runs = write_runs_summary(con, source)
    print(f"wrote {FL_PARQUET.relative_to(REPO_ROOT)}: {fl_rows:,} rows")
    print(f"wrote {RUNS_PARQUET.relative_to(REPO_ROOT)}: {n_runs:,} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
