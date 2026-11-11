"""Phase 0 / tz2021: save the Uri (Texas) and Ida (Louisiana, Mississippi) cuts
of the EAGLE-I 2021 CSV for later weeks.

Reads data/raw/eaglei_2021/eaglei_outages_2021.csv with DuckDB (fips_code as
VARCHAR, never a number) and writes to data/interim/, with run_start_time
copied unchanged from the file (no timezone conversion) and empty
customers_out kept as NULL (never zero):

* eaglei_2021_uri_TX_2021-01-20_2021-03-10.parquet
    fips_code starting '48'; run_start_time in [2021-01-20 00:00, 2021-03-11 00:00)
* eaglei_2021_ida_LA_MS_2021-08-01_2021-09-30.parquet
    fips_code starting '22' or '28'; run_start_time in [2021-08-01 00:00, 2021-10-01 00:00)

Each file is then re-read and compared with the same filter run directly on
the CSV (rows, NULL counts, customers_out sum, counties, runs, first and last
stamp), plus 5-digit FIPS and duplicate (fips_code, run_start_time) checks.

Run from the repo root:
    uv run python -I scripts/phase0/tz2021_extract.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CSV = REPO_ROOT / "data" / "raw" / "eaglei_2021" / "eaglei_outages_2021.csv"
INTERIM_DIR = REPO_ROOT / "data" / "interim"
SOURCE_URL = "https://ndownloader.figshare.com/files/42547891"
SOURCE_MD5 = "b5a5912be793ca22dddcc73ca2c3379d"

EXPECTED_COLUMNS = ("fips_code", "county", "state", "customers_out", "run_start_time")
CSV_TYPES = {
    "fips_code": "VARCHAR",
    "county": "VARCHAR",
    "state": "VARCHAR",
    "customers_out": "BIGINT",
    "run_start_time": "TIMESTAMP",
}
FIPS_REGEX = "[0-9]{5}"


@dataclass(frozen=True)
class Extract:
    path: Path
    fips_prefixes: tuple[str, ...]
    start: str  # inclusive, file clock
    end_exclusive: str  # exclusive, file clock


EXTRACTS = (
    Extract(
        INTERIM_DIR / "eaglei_2021_uri_TX_2021-01-20_2021-03-10.parquet",
        ("48",),
        "2021-01-20 00:00:00",
        "2021-03-11 00:00:00",
    ),
    Extract(
        INTERIM_DIR / "eaglei_2021_ida_LA_MS_2021-08-01_2021-09-30.parquet",
        ("22", "28"),
        "2021-08-01 00:00:00",
        "2021-10-01 00:00:00",
    ),
)


def sql_quote(text: str) -> str:
    """Return text as a single-quoted SQL string literal."""
    return "'" + text.replace("'", "''") + "'"


def csv_source(csv_path: Path) -> str:
    columns = ", ".join(f"{sql_quote(k)}: {sql_quote(v)}" for k, v in CSV_TYPES.items())
    return f"read_csv({sql_quote(str(csv_path))}, header = true, columns = {{{columns}}})"


def assert_header(con: duckdb.DuckDBPyConnection, csv_path: Path) -> None:
    """Fail fast if the file's header is not the one we expect."""
    sniffed = con.sql(f"DESCRIBE SELECT * FROM read_csv({sql_quote(str(csv_path))}, header = true, all_varchar = true)")
    names = tuple(row[0] for row in sniffed.fetchall())
    if names != EXPECTED_COLUMNS:
        raise SystemExit(f"Unexpected header {names}; expected {EXPECTED_COLUMNS}")


def where_clause(extract: Extract) -> str:
    prefixes = " OR ".join(f"starts_with(fips_code, {sql_quote(p)})" for p in extract.fips_prefixes)
    return (
        f"({prefixes}) AND run_start_time >= TIMESTAMP {sql_quote(extract.start)} "
        f"AND run_start_time < TIMESTAMP {sql_quote(extract.end_exclusive)}"
    )


def summary(con: duckdb.DuckDBPyConnection, relation: str, where: str) -> dict:
    row = con.sql(
        f"""
        SELECT count(*) AS n_rows,
               count(*) FILTER (WHERE customers_out IS NULL) AS n_null_customers_out,
               sum(customers_out) AS sum_customers_out,
               count(DISTINCT fips_code) AS n_fips,
               count(DISTINCT run_start_time) AS n_runs,
               min(run_start_time) AS first_stamp,
               max(run_start_time) AS last_stamp
        FROM {relation} WHERE {where}
        """
    ).df()
    return row.to_dict(orient="records")[0]


def key_checks(con: duckdb.DuckDBPyConnection, relation: str) -> dict:
    row = con.sql(
        f"""
        SELECT count(*) FILTER (WHERE fips_code IS NULL
                   OR NOT regexp_full_match(fips_code, {sql_quote(FIPS_REGEX)})) AS n_fips_not_5_digits,
               count(*) - count(DISTINCT (fips_code, run_start_time)) AS n_duplicate_keys
        FROM {relation}
        """
    ).df()
    return row.to_dict(orient="records")[0]


def write_extract(con: duckdb.DuckDBPyConnection, source: str, extract: Extract) -> None:
    metadata = {
        "source_file": "eaglei_outages_2021.csv",
        "source_url": SOURCE_URL,
        "source_md5": SOURCE_MD5,
        "filter": where_clause(extract),
        "run_start_time": "copied unchanged from the CSV (file clock); see docs/phase0/agent-timezone-2021.md",
        "customers_out": "NULL where the CSV field is empty; not zero",
    }
    kv = ", ".join(f"{k}: {sql_quote(v)}" for k, v in metadata.items())
    con.sql(
        f"""
        COPY (
            SELECT fips_code, county, state, customers_out, run_start_time
            FROM {source}
            WHERE {where_clause(extract)}
            ORDER BY run_start_time, fips_code
        ) TO {sql_quote(str(extract.path))} (FORMAT parquet, KV_METADATA {{{kv}}})
        """
    )


def verify(con: duckdb.DuckDBPyConnection, source: str, extract: Extract) -> dict:
    parquet = f"read_parquet({sql_quote(str(extract.path))})"
    from_csv = summary(con, source, where_clause(extract))
    from_parquet = summary(con, parquet, "true")
    keys = key_checks(con, parquet)
    types = {name: col_type for name, col_type, *_ in con.sql(f"DESCRIBE SELECT * FROM {parquet}").fetchall()}
    problems = [f"{k}: csv={from_csv[k]} parquet={from_parquet[k]}" for k in from_csv if from_csv[k] != from_parquet[k]]
    problems += [f"{k}={v}" for k, v in keys.items() if v != 0]
    if types.get("fips_code") != "VARCHAR":
        problems.append(f"fips_code type {types.get('fips_code')}")
    return {"summary": from_parquet, "keys": keys, "types": types, "problems": problems}


def main() -> int:
    if not RAW_CSV.is_file():
        print(f"Missing {RAW_CSV}; download it first.", file=sys.stderr)
        return 1
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    assert_header(con, RAW_CSV)
    source = csv_source(RAW_CSV)
    failed = False
    for extract in EXTRACTS:
        write_extract(con, source, extract)
        result = verify(con, source, extract)
        print(f"wrote {extract.path.relative_to(REPO_ROOT)}")
        print(f"  summary: {result['summary']}")
        print(f"  keys: {result['keys']}  types: {result['types']}")
        if result["problems"]:
            failed = True
            print(f"  PROBLEMS: {result['problems']}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
