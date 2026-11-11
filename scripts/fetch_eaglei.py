"""Download EAGLE-I yearly outage CSVs from figshare and keep them as compact parquet files.

Run from the repo root: uv run python -I scripts/fetch_eaglei.py 2018 2020 2021 2022 2023 2024
With no years it fetches only the small files (MCC.csv, coverage_history.csv, DQI.csv).

Each CSV is checked against figshare's MD5, converted to data/raw/eaglei/eaglei_outages_<year>.parquet with
fips_code kept as text (DuckDB would guess BIGINT), checked for an equal row count, and then deleted. The parquet
is about a tenth of the CSV, and `build_storm` copies each storm's states and dates from it. It is written under a
.part name and renamed once checked, and a parquet already on disk is kept only if it can be read and, for a year
pinned in docs/reproduce/inputs.json, holds the pinned number of rows; otherwise it is fetched again.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import duckdb
import httpx

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data/raw/eaglei"
META = REPO / "data/raw/docs/figshare_24237376.json"
PINNED = REPO / "docs/reproduce/inputs.json"  # MD5s of the files the committed tables were built from
# figshare keeps every version of an article, so pinning one keeps the inputs fixed when ORNL publishes the next.
ARTICLE_VERSION = 4
ARTICLE = f"https://api.figshare.com/v2/articles/24237376/versions/{ARTICLE_VERSION}"  # EAGLE-I (CC BY 4.0)
SMALL_FILES = ("MCC.csv", "coverage_history.csv", "DQI.csv")


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_md5(meta: dict) -> str | None:
    return meta.get("computed_md5") or meta.get("supplied_md5")


def check_pinned(files: dict[str, dict]) -> None:
    """Stop before downloading when figshare's listing no longer matches the MD5s in docs/reproduce/inputs.json."""
    if not PINNED.exists():
        return
    pins = json.loads(PINNED.read_text())["eaglei"]["files"]
    changed = [name for name, pin in pins.items() if name not in files or expected_md5(files[name]) != pin["md5"]]
    if changed:
        raise SystemExit(f"upstream EAGLE-I input changed on figshare: {changed} are gone from the listing or no "
                         f"longer match the MD5s in {PINNED.relative_to(REPO)}, so a rebuild would not be comparable "
                         f"with the committed tables")


def pinned_rows(year: int) -> int | None:
    """Rows of the year's file when the committed tables were built (docs/reproduce/inputs.json); None if not pinned."""
    if not PINNED.exists():
        return None
    return json.loads(PINNED.read_text())["eaglei"]["files"].get(f"eaglei_outages_{year}.csv", {}).get("rows")


def parquet_rows(path: Path) -> int | None:
    """The row count in the parquet footer; None for a file that cannot be read (cut short, or not parquet)."""
    try:
        return duckdb.connect().execute(f"select count(*) from read_parquet('{path}')").fetchall()[0][0]
    except duckdb.Error:
        return None


def fetch_year(year: int, files: dict[str, dict]) -> Path:
    out = RAW / f"eaglei_outages_{year}.parquet"
    pinned = pinned_rows(year)
    if out.exists():
        rows = parquet_rows(out)
        if rows is not None and pinned in (None, rows):
            print(f"{year}: already have {out.name} ({rows:,} rows{', as pinned' if pinned else ''})")
            return out
        found = "cannot be read" if rows is None else f"has {rows:,} rows, not the pinned {pinned:,}"
        print(f"{year}: {out.name} {found}: fetching it again")
        out.unlink()
    meta = files[f"eaglei_outages_{year}.csv"]
    csv = RAW / meta["name"]
    if not csv.exists() or csv.stat().st_size != meta["size"]:
        with httpx.Client(timeout=600, follow_redirects=True) as client, client.stream("GET", meta["download_url"]) as r:
            r.raise_for_status()
            with csv.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 22):
                    fh.write(chunk)
    expected = expected_md5(meta)
    if expected and md5_of(csv) != expected:
        raise SystemExit(f"{year}: MD5 mismatch for {csv.name}")
    con = duckdb.connect()
    header = con.execute(f"select * from read_csv('{csv}', header=true, all_varchar=true) limit 0").description
    cols = [c[0] for c in header]
    count_col = "customers_out" if "customers_out" in cols else "sum"
    src = f"read_csv('{csv}', header=true, types={{'fips_code': 'VARCHAR', '{count_col}': 'DOUBLE'}})"
    part = out.with_suffix(".part")  # renamed only once checked: a conversion that is killed leaves no parquet behind
    con.execute(f"""copy (select fips_code, county, state, "{count_col}" as customers_out,
                        cast(run_start_time as timestamp) as run_start_time from {src})
                    to '{part}' (format parquet, compression zstd)""")
    n_csv = con.execute(f"select count(*) from {src}").fetchall()[0][0]
    n_pq = con.execute(f"select count(*) from read_parquet('{part}')").fetchall()[0][0]
    if n_csv != n_pq or pinned not in (None, n_pq):
        part.unlink()
        raise SystemExit(f"{year}: row count changed {n_csv} -> {n_pq}" if n_csv != n_pq else
                         f"{year}: {n_pq:,} rows, not the {pinned:,} pinned in {PINNED.relative_to(REPO)}")
    os.replace(part, out)
    csv.unlink()
    print(f"{year}: {n_pq:,} rows -> {out.name} ({out.stat().st_size / 1e6:.0f} MB); columns were {cols}")
    return out


def file_listing() -> dict[str, dict]:
    """The article's files by name, from the cached metadata or the figshare API (cached afterwards)."""
    if not META.exists():
        META.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(ARTICLE)
            response.raise_for_status()
            META.write_text(response.text)
    return {f["name"]: f for f in json.loads(META.read_text())["files"]}


def fetch_small(files: dict[str, dict]) -> None:
    """MCC.csv (customers per county), coverage_history.csv and DQI.csv, checked against figshare's MD5."""
    RAW.mkdir(parents=True, exist_ok=True)
    for name in SMALL_FILES:
        meta = files[name]
        target = RAW / name
        expected = expected_md5(meta)
        if target.exists() and (not expected or md5_of(target) == expected):
            continue
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get(meta["download_url"])
            response.raise_for_status()
            target.write_bytes(response.content)
        if expected and md5_of(target) != expected:
            raise SystemExit(f"{name}: MD5 mismatch")
        print(f"fetched {name} ({target.stat().st_size:,} bytes)")


def main(argv: list[str]) -> int:
    files = file_listing()
    check_pinned(files)
    fetch_small(files)
    for year in map(int, argv):
        fetch_year(year, files)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
