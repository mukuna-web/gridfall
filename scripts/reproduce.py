"""Reproduce the project's numbers on free compute: your laptop, GitHub Actions or a Google Colab session.

Run from the repo root:

    uv run python -I scripts/reproduce.py --level 0     # offline: tests, sample export, frozen record    (~2 min)
    uv run python -I scripts/reproduce.py --level 1     # one NASA tile, three counties, 55 nights (~4.5 min on Colab)
    uv run python -I scripts/reproduce.py --level 2     # all of Ian, 505 counties, 3 tiles        (~5.5 min on Colab)

Levels 1 and 2 need a free NASA Earthdata token in the EARTHDATA_TOKEN environment variable (or a .env file); tokens
expire 60 days after they are generated, and the token is tried on one byte of a real tile before anything large is
downloaded. They fetch what they need (EAGLE-I 2022, Census shapes, HURDAT2, satellite tiles streamed into memory),
check EAGLE-I, Census and HURDAT2 against the hashes in docs/reproduce/inputs.json so a change in one of them is
reported as such, and compare what they compute with what the repository committed: level 1 against
data/sample/county_nights_ian_sample.parquet, level 2 against docs/reproduce/ian2022_fingerprint.json. The satellite
tiles are not pinned (each is checked only against the MD5 NASA lists for it that day), so a NASA reprocessing shows
up as different numbers. Nothing in data/processed is touched: rebuilt tables go to a scratch folder. The JSON
report (--report) is rewritten after every check and says "complete": false until the run reaches its end, so a
killed or interrupted run never reads as a pass; the exit code is 0 only when the run finishes and every check passes.

    uv run python -I scripts/reproduce.py --fingerprint   # maintainers: refresh the level-2 fingerprint from
                                                          # data/processed/county_nights_ian2022.parquet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "data/sample/county_nights_ian_sample.parquet"
FINGERPRINT = REPO / "docs/reproduce/ian2022_fingerprint.json"
INPUTS = REPO / "docs/reproduce/inputs.json"  # MD5 / SHA-256 of the EAGLE-I, Census and HURDAT2 files the tables used
FROZEN = REPO / "docs/lockbox_result.json"
RECORD = REPO / "docs/lockbox_record.json"
HURDAT_DIR_URL = "https://www.nhc.noaa.gov/data/hurdat/"
SAMPLE_COUNTIES = ("12071", "12015", "12021")  # Lee, Charlotte, Collier
LEE = "12071"
STORM = "ian2022"
PROBE_DATE = date(2022, 9, 29)  # file date of Ian's landfall night: one real tile to try the token on
PROTECTED = ("data", "docs")  # the real tables, inputs and figures: --scratch may not point inside these
# The folders inside them that the pipeline keeps its files in. Each may be a link to another disk: the files are
# then where the link leads, and a rebuild written there overwrites them just as it would inside data/ itself.
PROTECTED_INSIDE = ("data/processed", "data/interim", "data/raw", "data/sample", "docs/img")
# Values compared to this many decimals. pct_darker sums float32 radiances in a fixed order, so it reproduces to
# float32 precision; the EAGLE-I medians and customer counts reproduce exactly.
TOLERANCES = {"pct_darker": 1e-5, "visible_share": 1e-6, "base_total": 1e-2, "sensor_zenith": 1e-3,
              "lunar_irradiance": 1e-3, "official_customers_out": 0.0, "official_customers_out_30": 0.0,
              "official_customers_out_90": 0.0, "official_pct_out": 1e-9, "official_pct_out_30": 1e-9,
              "official_pct_out_90": 1e-9, "customers": 0.0, "housing_units": 0.0, "wind_band": 0.0, "coverage": 1e-9}
EXACT = ("storm_id", "satellite", "status", "pass_source", "covered")  # compared as text, row by row
# The fingerprint sums each column over one night's rows (up to 505 counties): the per-row tolerances above, scaled
# to a sum. EAGLE-I medians are whole or half customers, so their sums rounded to one decimal reproduce exactly.
NIGHT_SUM_TOLERANCES = {"sum_pct_darker": 1e-3, "sum_visible_share": 1e-3, "sum_base_total": 1.0,
                        "sum_sensor_zenith": 1e-2, "sum_lunar_irradiance": 1e-2, "sum_official_customers_out": 0.1,
                        "sum_official_customers_out_30": 0.1, "sum_official_customers_out_90": 0.1}
NIGHT_COUNTS = ("rows", "ok", "cant_see", "not_measurable", "formula_passes")
# The same columns summed over one county's nights (55 for Ian, fewer rows than a night's counties, so the night
# tolerances hold), plus the official shares and the county's own inputs, so that every column of the table feeds a
# county total. A tolerance of 0 marks a whole number that must match exactly.
COUNTY_SUM_TOLERANCES = {"cant_see": 0, "not_measurable": 0, "formula_passes": 0, "visible_share": 1e-3,
                         "base_total": 1.0, "sensor_zenith": 1e-2, "lunar_irradiance": 1e-2,
                         "official_customers_out": 0.1, "official_customers_out_30": 0.1,
                         "official_customers_out_90": 0.1, "official_pct_out": 1e-6, "official_pct_out_30": 1e-6,
                         "official_pct_out_90": 1e-6, "customers": 0.1, "housing_units": 0, "wind_band": 0,
                         "coverage": 1e-6, "covered": 0}
NIGHT_TO_PASS = "seconds_night_to_pass"  # per county: seconds from 00:00 UTC of each night's own date to its pass
# A sum skips a missing value, so to every total above a missing value and a zero are the same. The fingerprint
# therefore also counts, for each night and for each county, the values present in every column a total is taken of.
PRESENT = ("pass_utc", *TOLERANCES, "covered")
KEY = ["fips", "night"]
URL_QUERY = re.compile(r"(https?://[^\s'\"?]+)\?[^\s'\"]*")
BEARER = re.compile(r"bearer\s[^'\"]*", re.IGNORECASE)


def redact(text: str) -> str:
    """Text without URL query strings (NASA's redirects carry signed CloudFront/S3 URLs and the account name) and
    without whatever follows the word Bearer up to the next quote: an HTTP library that quotes a header it refused
    must not put the token into the log, the report or the uploaded artifact."""
    return BEARER.sub("Bearer <redacted>", URL_QUERY.sub(r"\1?<redacted>", text))


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    seconds: float = 0.0


@dataclass
class Report:
    level: int
    started_utc: str
    platform: str
    path: Path | None = field(default=None, repr=False)
    checks: list[Check] = field(default_factory=list)
    build: dict | None = None  # build_storm's summary (tiles, problems, minutes) for levels 1 and 2
    complete: bool = False  # main() sets it once the run has reached its end; a killed or interrupted run never does

    @property
    def clean(self) -> bool:
        """No check has failed so far: what lets the next stage start. Not the verdict."""
        return all(c.passed for c in self.checks)

    @property
    def passed(self) -> bool:
        """The verdict: the run reached its end and every check passed. A half-finished run is never a pass."""
        return self.complete and bool(self.checks) and self.clean

    @property
    def verdict(self) -> str:
        if self.passed:
            return "PASS"
        return "INCOMPLETE" if self.clean else "FAIL"

    def add(self, name: str, passed: bool, detail: str, seconds: float = 0.0) -> None:
        self.checks.append(Check(name, bool(passed), redact(detail), round(seconds, 1)))
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {self.checks[-1].detail}", flush=True)
        self.save()

    def payload(self) -> dict:
        return {"level": self.level, "started_utc": self.started_utc, "platform": self.platform,
                "complete": self.complete, "passed": self.passed, "checks": [asdict(c) for c in self.checks],
                "build": self.build}

    def save(self) -> None:
        """Rewrite the JSON report (when --report was given) so it exists, and says how far the run got, however the
        run ends."""
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.payload(), indent=2))


def platform_name() -> str:
    env = os.environ
    if "COLAB_RELEASE_TAG" in env or "COLAB_GPU" in env:  # both are exported by Colab runtimes, GPU or not
        return "colab"
    if env.get("GITHUB_ACTIONS") == "true":
        return "github-actions"
    return "local"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, cwd=REPO, capture_output=True, text=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pinned() -> dict:
    """docs/reproduce/inputs.json: what the EAGLE-I, Census and HURDAT2 downloads hashed to when the committed tables
    were built. NASA's satellite tiles are not in it."""
    return json.loads(INPUTS.read_text())


# --- level 0: offline ---------------------------------------------------------------------------------------------

def level0(report: Report) -> None:
    t = time.time()
    tests = run([sys.executable, "-I", "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider", "-x",
                 "--ignore=tests/realdata"])
    lines = tests.stdout.strip().splitlines()
    failed = [line for line in lines if line.startswith("FAILED")]
    # redact() comes before every cut: a cut that lands inside a URL query or a header would hide it from redact()
    tail = redact(" | ".join([*failed[:3], lines[-1]]))[:300] if lines else redact(tests.stderr.strip())[-300:]
    report.add("unit tests", tests.returncode == 0, tail, time.time() - t)

    t = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        code = f"from blackout.export import export_sample; export_sample(out=__import__('pathlib').Path({tmp!r}))"
        out = run([sys.executable, "-I", "-c", code])
        files = sorted(p.name for p in (Path(tmp) / "ian2022_sample").glob("*")) if out.returncode == 0 else []
    report.add("sample export", out.returncode == 0 and "nights.json" in files,
               f"{len(files)} files written" if out.returncode == 0 else redact(out.stderr.strip())[-300:],
               time.time() - t)

    if FROZEN.exists() and RECORD.exists():
        ok, detail = record_check(json.loads(FROZEN.read_text()), json.loads(RECORD.read_text()), sha256_of(FROZEN))
        report.add("frozen lockbox record", ok, detail)
    else:
        report.add("frozen lockbox record", False, "docs/lockbox_result.json or docs/lockbox_record.json missing")


def record_check(frozen: dict, record: dict, digest: str) -> tuple[bool, str]:
    """docs/lockbox_record.json names docs/lockbox_result.json and carries its SHA-256, which matches the file, and
    the frozen verdict is one the plan allows. A record without the hash fails instead of passing vacuously."""
    verdict = frozen.get("verdict")
    satellite = frozen.get("satellite_test", {}).get("verdict")
    detail = f"verdict {verdict!r}, satellite test {satellite!r}, sha256 {digest[:16]}"
    recorded = record.get("result_sha256")
    if recorded is None:
        return False, detail + " (docs/lockbox_record.json has no result_sha256)"
    if record.get("result_file") != "docs/lockbox_result.json":
        return False, detail + f" (the record names {record.get('result_file')!r}, not docs/lockbox_result.json)"
    if digest != recorded:
        return False, detail + " (differs from docs/lockbox_record.json)"
    if verdict not in ("pass", "partial", "fail"):
        return False, detail + " (unknown verdict)"
    return True, detail


# --- inputs for levels 1 and 2 -----------------------------------------------------------------------------------

def ensure_reference(report: Report, level: int) -> bool:
    """The committed table this level compares against is present, before anything is downloaded."""
    needed = SAMPLE if level == 1 else FINGERPRINT
    present = needed.exists()
    report.add("committed reference", present, f"{needed.relative_to(REPO)}" + ("" if present else " is missing"))
    return present


def ensure_token(report: Report) -> bool:
    from blackout.laads import TokenMissingError, earthdata_token

    try:
        token = earthdata_token()
    except TokenMissingError as err:
        report.add("Earthdata token", False, str(err))
        return False
    t = time.time()
    ok, detail = probe_token(token)
    report.add("Earthdata token", ok, detail, time.time() - t)
    return ok


def probe_token(token: str) -> tuple[bool, str]:
    """One listing call and a one-byte range request on a real Ian tile, so a rejected or expired token fails here
    rather than after the EAGLE-I download, deep inside the build."""
    import httpx

    from blackout.laads import CLOUD, client_for, list_tile_files

    try:
        with client_for(token, timeout=60) as client:
            files = list_tile_files(client, "VNP46A2", "h09v06", PROBE_DATE, PROBE_DATE)
            if not files:
                return False, f"LAADS lists no VNP46A2 h09v06 file for {PROBE_DATE}"
            name = next(iter(files.values())).name
            with client.stream("GET", f"{CLOUD}/VNP46A2/{name}", headers={"Range": "bytes=0-0"}) as response:
                status, host = response.status_code, response.url.host
    except httpx.LocalProtocolError:  # httpx quotes the header it refused, token included: that text goes nowhere
        return False, "EARTHDATA_TOKEN holds characters that cannot go into an HTTP header: paste it again"
    except httpx.HTTPError as err:
        return False, f"could not reach NASA: {type(err).__name__}: {err}"
    if host == "urs.earthdata.nasa.gov" or status in (401, 403):
        return False, (f"rejected by Earthdata (HTTP {status} via {host}); tokens expire 60 days after they are "
                       f"generated: make a new one at urs.earthdata.nasa.gov")
    if status not in (200, 206):
        return False, f"unexpected HTTP {status} from {host} for {name}"
    return True, f"accepted by Earthdata Cloud (HTTP {status} for one byte of {name}); the token is never printed"


def ensure_inputs(report: Report) -> None:
    """EAGLE-I 2022 (as parquet) and the small EAGLE-I files, Census shapes and housing, HURDAT2: downloaded when
    absent, each checked against the hashes in docs/reproduce/inputs.json."""
    eaglei_check(report)
    census_check(report)
    hurdat_check(report)


def eaglei_check(report: Report) -> None:
    t = time.time()
    fetched = run([sys.executable, "-I", "scripts/fetch_eaglei.py", "2022"])
    if fetched.returncode:
        detail = redact(fetched.stderr.strip())[-300:] or redact(fetched.stdout.strip())[-300:]
    else:
        detail = (fetched.stdout.strip().splitlines() or ["ok"])[-1][:200]
    report.add("EAGLE-I 2022 + MCC + coverage (figshare, pinned)", fetched.returncode == 0, detail, time.time() - t)


def census_check(report: Report) -> None:
    import httpx

    from blackout.counties import CENSUS, SOURCES, ensure_census_files

    t = time.time()
    try:
        ensure_census_files()
    except (httpx.HTTPError, OSError) as err:  # a network error or a full disk: the check says so, the run goes on
        report.add("Census shapes and housing units", False, f"{type(err).__name__}: {err}", time.time() - t)
        return
    missing = [name for name in SOURCES if not (CENSUS / name).exists()]
    changed = [name for name, digest in pinned()["census"].items()
               if (CENSUS / name).exists() and sha256_of(CENSUS / name) != digest]
    detail = f"{len(SOURCES)} files present, hashes match docs/reproduce/inputs.json"
    if missing:
        detail = f"missing {missing}"
    elif changed:
        detail = f"{changed} differ from the hashes in docs/reproduce/inputs.json: an upstream Census file changed"
    report.add("Census shapes and housing units", not missing and not changed, detail, time.time() - t)


def hurdat_check(report: Report) -> None:
    import httpx

    from blackout.table import HURDAT

    t = time.time()
    if not HURDAT.exists():
        try:
            download(HURDAT_DIR_URL + HURDAT.name, HURDAT)
        except (httpx.HTTPError, OSError) as err:  # NHC replaces the dated file every spring: a 404 is expected one day
            report.add("HURDAT2", False, f"{HURDAT.name}: {type(err).__name__}: {err} (NHC publishes a new dated "
                       f"file each spring and removes the old one: commit a copy of the pinned file or update HURDAT "
                       f"in src/blackout/table.py)", time.time() - t)
            return
    digest = sha256_of(HURDAT)
    same = digest == pinned()["hurdat2"]["sha256"]
    report.add("HURDAT2", same, f"{HURDAT.name} sha256 {digest[:16]}"
               + ("" if same else " differs from docs/reproduce/inputs.json: not the file the tables were built from"),
               time.time() - t)


def download(url: str, target: Path) -> None:
    import httpx

    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        target.write_bytes(response.content)


# --- comparing tables ----------------------------------------------------------------------------------------------

def _keyed(table: pd.DataFrame) -> pd.DataFrame:
    """Indexed by (fips, night), with fips as five-digit text and night as a datetime whatever the parquet dtypes."""
    fips = table["fips"].astype(str).str.zfill(5)
    return table.assign(fips=fips, night=pd.to_datetime(table["night"])).set_index(KEY).sort_index()


def _labels(index: pd.MultiIndex) -> list[str]:
    return [f"{fips} {night:%Y-%m-%d}" for fips, night in index[:3]]


def compare_tables(built: pd.DataFrame, expected: pd.DataFrame) -> tuple[bool, str]:
    """Row-for-row comparison on (fips, night) of every column: both tables hold exactly the columns compared here,
    the EXACT ones equal as text, pass times to the second, the numbers within TOLERANCES."""
    compared = {*KEY, *EXACT, "pass_utc", *TOLERANCES}
    for side, table in (("rebuilt", built), ("committed", expected)):
        if set(table.columns) != compared:
            return False, (f"the {side} table's columns are not the ones compared: unexpected "
                           f"{sorted(set(table.columns) - compared)}, missing {sorted(compared - set(table.columns))}")
    b, e = _keyed(built), _keyed(expected)
    if not b.index.equals(e.index):
        return False, (f"different county-nights: built {len(b)}, expected {len(e)}; unexpected "
                       f"{_labels(b.index.difference(e.index))}, missing {_labels(e.index.difference(b.index))}")
    problems = []
    for column in EXACT:
        bad = int((b[column].astype(str) != e[column].astype(str)).sum())
        if bad:
            problems.append(f"{column}: {bad} rows differ")
    b_pass, e_pass = pd.to_datetime(b["pass_utc"], utc=True), pd.to_datetime(e["pass_utc"], utc=True)
    bad_pass = ((b_pass - e_pass).abs() > pd.Timedelta(seconds=1)) | (b_pass.isna() != e_pass.isna())
    if bad_pass.any():
        problems.append(f"pass_utc: {int(bad_pass.sum())} rows differ by over a second or are missing on one side")
    for column, tol in TOLERANCES.items():
        x, y = b[column].to_numpy(dtype=float), e[column].to_numpy(dtype=float)
        both_nan = np.isnan(x) & np.isnan(y)
        close = both_nan | (np.abs(x - y) <= tol + 1e-12)
        if not close.all():
            worst = float(np.nanmax(np.abs(x - y)[~both_nan])) if (~both_nan).any() else float("nan")
            problems.append(f"{column}: {int((~close).sum())} rows differ (largest gap {worst:.3g}, tolerance {tol})")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(b)} county-nights match within tolerance"


def _night_summary(part: pd.DataFrame) -> dict:
    """Counts and nan-aware sums of one night's rows. A changed value moves a sum; values swapped between counties on
    the same night do not, and a pass moved by whole days keeps its seconds: both show in _county_sums instead."""
    okp = part[part["status"] == "ok"]
    passes = pd.to_datetime(part["pass_utc"], utc=True)
    seconds = (passes - passes.dt.normalize()).dt.total_seconds()
    summary = {
        "rows": len(part), "ok": len(okp),
        "cant_see": int((part["status"] == "cant_see").sum()),
        "not_measurable": int((part["status"] == "not_measurable").sum()),
        "formula_passes": int((part["pass_source"] == "formula").sum()),
        "sum_pct_darker": round(float(okp["pct_darker"].sum()), 4),
        "sum_pass_seconds": round(float(seconds.sum()), 1),
    }
    for column in ("visible_share", "base_total", "sensor_zenith", "lunar_irradiance", "official_customers_out",
                   "official_customers_out_30", "official_customers_out_90"):
        summary[f"sum_{column}"] = round(float(part[column].sum()), 4)
    return summary


def _county_summary(t: pd.DataFrame) -> dict[str, list]:
    """fips -> [ok nights, sum of pct_darker over them]: catches pct_darker swapped between counties on a night."""
    ok = t["status"] == "ok"
    grouped = t.assign(ok=ok.astype(int), ok_pct=t["pct_darker"].where(ok)).groupby("fips")[["ok", "ok_pct"]].sum()
    return {fips: [int(row["ok"]), round(float(row["ok_pct"]), 4)] for fips, row in grouped.iterrows()}


def _county_sums(t: pd.DataFrame) -> dict[str, list]:
    """Column by column and in fips order, each county's totals over its nights: the other status counts and the
    formula passes, the sum of every other measured column and of the county's own inputs (a missing value adds
    nothing), and the pass times as seconds counted from each night's own date. A value that moved to another county
    on the same night, or a pass that moved by whole days, changes at least one of them."""
    passes = pd.to_datetime(t["pass_utc"], utc=True)
    nights = pd.to_datetime(t["night"]).dt.tz_localize("UTC")
    frame = t.assign(cant_see=t["status"] == "cant_see", not_measurable=t["status"] == "not_measurable",
                     formula_passes=t["pass_source"] == "formula",
                     **{NIGHT_TO_PASS: (passes - nights).dt.total_seconds()})
    sums = frame.groupby("fips")[[*COUNTY_SUM_TOLERANCES, NIGHT_TO_PASS]].sum()
    return {"fips": sums.index.tolist(),
            **{name: [int(v) if COUNTY_SUM_TOLERANCES.get(name) == 0 else round(float(v), 6) for v in sums[name]]
               for name in sums.columns}}


def _lee_series(t: pd.DataFrame) -> dict[str, list]:
    lee = t[t["fips"] == LEE].sort_values("night")
    return {"night": lee["night"].tolist(), "status": lee["status"].tolist(),
            "pct_darker": [None if np.isnan(v) else round(float(v), 6) for v in lee["pct_darker"]],
            "official_customers_out": [None if np.isnan(v) else float(v) for v in lee["official_customers_out"]]}


def _present(t: pd.DataFrame, by: str) -> dict[str, list | int]:
    """How many of each night's (or county's) rows hold a value, for every column in PRESENT. To the sums a missing
    value and a zero are the same table; to these counts they are not. A column's counts are a list in the order of
    the nights (or counties) listed under `by`, or one number where every one of them holds the same count, which
    keeps the committed file small: most columns of Ian's table have no missing value at all."""
    counts = t.groupby(by)[list(PRESENT)].count()
    return {by: counts.index.tolist(),
            **{name: int(counts[name].iloc[0]) if counts[name].nunique() == 1 else counts[name].tolist()
               for name in PRESENT}}


def fingerprint(table: pd.DataFrame) -> dict:
    """A committed summary of a full table: counts and sums of the measured columns per night, counts and sums of
    every column per county (the per-county inputs among them: wind band, customers, housing units, coverage), Lee
    County's whole series, and how many values each summed column holds per night and per county (a sum cannot tell
    a missing value from a zero). It is a summary, not the table: a changed value moves a total, but values
    rearranged so that every night's and every county's totals stay the same would go unseen (level 1 compares its
    three counties row by row)."""
    t = table.assign(fips=table["fips"].astype(str).str.zfill(5),
                     night=pd.to_datetime(table["night"]).dt.strftime("%Y-%m-%d"))
    ok = t[t["status"] == "ok"]
    per_county = t.drop_duplicates("fips").set_index("fips").sort_index()
    by_state = per_county.groupby(per_county.index.str[:2])["coverage"].first()
    return {
        "storm_id": "/".join(sorted(t["storm_id"].astype(str).unique())),  # one name, unless rows disagree
        "satellite": "/".join(sorted(t["satellite"].astype(str).unique())),
        "rows": len(t),
        "counties": int(t["fips"].nunique()),
        "status_counts": {k: int(v) for k, v in t["status"].value_counts().items()},
        "ok_rows_mean_pct_darker": round(float(ok["pct_darker"].mean()), 6),
        "wind_band_counts": {str(k): int(v) for k, v in per_county["wind_band"].value_counts().sort_index().items()},
        "sum_customers": round(float(per_county["customers"].sum()), 1),
        "sum_housing_units": int(per_county["housing_units"].sum()),
        "coverage_by_state": {state: round(float(cov), 6) for state, cov in by_state.items()},
        "nights": {night: _night_summary(part) for night, part in t.groupby("night")},
        "per_county": _county_summary(t),
        "lee_county": _lee_series(t),
        "pass_source_counts": {k: int(v) for k, v in t["pass_source"].value_counts().items()},
        "county_sums": _county_sums(t),
        "present_per_night": _present(t, "night"),
        "present_per_county": _present(t, "fips"),
    }


def _compare_nights(built: dict, expected: dict) -> list[str]:
    problems = []
    for night, exp in expected["nights"].items():
        got = built["nights"].get(night)
        if got is None:
            problems.append(f"{night}: missing")
            continue
        for key in NIGHT_COUNTS:
            if got.get(key) != exp[key]:
                problems.append(f"{night} {key}: {got.get(key)} vs {exp[key]}")
        for key, tol in {**NIGHT_SUM_TOLERANCES, "sum_pass_seconds": float(exp["rows"])}.items():  # 1 s per row
            if got.get(key) is None or abs(got[key] - exp[key]) > tol:
                problems.append(f"{night} {key}: {got.get(key)} vs {exp[key]}")
    return problems


def _compare_counties(built: dict, expected: dict) -> list[str]:
    problems = []
    for fips, exp in expected["per_county"].items():
        got = built["per_county"].get(fips)
        if got is None or got[0] != exp[0] or abs(got[1] - exp[1]) > 1e-3:
            problems.append(f"county {fips}: {got} vs {exp}")
    lee_b, lee_e = built["lee_county"], expected["lee_county"]
    if lee_b["night"] != lee_e["night"] or lee_b["status"] != lee_e["status"]:
        return [*problems, "Lee County: nights or statuses differ"]
    for night, b_val, e_val in zip(lee_e["night"], lee_b["pct_darker"], lee_e["pct_darker"]):
        if (b_val is None) != (e_val is None) or (b_val is not None and abs(b_val - e_val) > 1e-5):
            problems.append(f"Lee {night} pct_darker: {b_val} vs {e_val}")
    if lee_b["official_customers_out"] != lee_e["official_customers_out"]:
        problems.append("Lee County: official customers out differ")
    return problems


def _compare_county_sums(built: dict, expected: dict) -> list[str]:
    got, exp = built["county_sums"], expected.get("county_sums")
    if exp is None or set(exp) != set(got) or exp["fips"] != got["fips"]:
        return [("county_sums: the committed fingerprint has none, or other columns or counties (maintainers refresh "
                 "it with --fingerprint)")]
    problems = []
    for name, tol in {**COUNTY_SUM_TOLERANCES, NIGHT_TO_PASS: float(len(expected["nights"]))}.items():  # 1 s a night
        gap = np.abs(np.asarray(got[name], dtype=float) - np.asarray(exp[name], dtype=float))
        problems += [f"county {exp['fips'][i]} {name} over its nights: {got[name][i]} vs {exp[name][i]}"
                     for i in np.flatnonzero(~(gap <= tol))]
    return problems


def _spread(counts: list | int, n: int) -> list:
    """A column's counts as a list of `n`: _present writes one number where they are all the same."""
    return counts if isinstance(counts, list) else [counts] * n


def _compare_present(built: dict, expected: dict) -> list[str]:
    """The counts of present values, exactly: one more or one fewer is a value that went missing or a gap that was
    filled, which no sum shows when the value is a zero."""
    problems = []
    for key, by, label in (("present_per_night", "night", ""), ("present_per_county", "fips", "county ")):
        got, exp = built[key], expected.get(key)
        if exp is None:
            problems.append(f"{key}: the committed fingerprint has no counts of present values, so it cannot tell a "
                            f"missing value from a zero (maintainers refresh it with --fingerprint)")
        elif set(exp) != set(got) or exp[by] != got[by]:
            problems.append(f"{key}: other columns, nights or counties than in the committed fingerprint "
                            f"(maintainers refresh it with --fingerprint when the counted columns change)")
        else:
            groups = exp[by]
            for name in PRESENT:
                pairs = zip(groups, _spread(got[name], len(groups)), _spread(exp[name], len(groups)), strict=True)
                problems += [f"{label}{group} {name}: {g} values present vs {e}" for group, g, e in pairs if g != e]
    return problems


def compare_fingerprints(built: dict, expected: dict) -> tuple[bool, str]:
    problems = []
    for key in ("storm_id", "satellite", "rows", "counties", "status_counts", "pass_source_counts",
                "wind_band_counts", "sum_housing_units", "coverage_by_state"):
        if built.get(key) != expected.get(key):
            problems.append(f"{key}: {built.get(key)!r} vs {expected.get(key)!r}")
    for key, tol in (("ok_rows_mean_pct_darker", 1e-5), ("sum_customers", 0.0)):
        if abs(float(built[key]) - float(expected[key])) > tol:
            problems.append(f"{key}: {built[key]} vs {expected[key]}")
    problems += _compare_nights(built, expected) + _compare_counties(built, expected)
    problems += _compare_county_sums(built, expected) + _compare_present(built, expected)
    if problems:
        return False, "; ".join(problems[:12]) + (f"; and {len(problems) - 12} more" if len(problems) > 12 else "")
    return True, (f"{expected['rows']} rows, {len(expected['nights'])} nights, {len(expected['per_county'])} counties "
                  f"and Lee County's series match")


# --- levels 1 and 2 ------------------------------------------------------------------------------------------------

def rebuild(report: Report, counties_fips: tuple[str, ...] | None, scratch: Path) -> pd.DataFrame:
    """Build Ian (or a county subset) into `scratch`; keep the build summary in the report and check that every
    satellite file was read, so a failed NASA download is reported as a download failure, not as different numbers.
    The EAGLE-I extract is cut afresh into `scratch` from the yearly file the inputs check has just verified."""
    from blackout.counties import load_counties
    from blackout.storms import get_storm
    from blackout.table import build_storm, eaglei_extract_path

    t = time.time()
    storm = get_storm(STORM)
    counties = load_counties(storm.states)
    if counties_fips is not None:
        counties = counties[counties["fips"].isin(counties_fips)]
    processed, img, interim = scratch_folders(scratch)
    eaglei_extract_path(storm, interim).unlink(missing_ok=True)  # one left by an earlier run is not trusted
    table = build_storm(storm, counties=counties, processed=processed, img=img, interim=interim)
    summary_path = processed / f"county_nights_{STORM}.json"
    summary = json.loads(summary_path.read_text())
    problems = [redact(p) for p in summary.get("problems", [])]
    report.build = {**summary, "problems": problems}
    summary_path.write_text(json.dumps(report.build, indent=2))  # a kept scratch folder holds no signed URL either
    if problems:
        detail = (f"{len(problems)} satellite files could not be read (a download failure, not different numbers; "
                  f"the list is under 'build' in the report): {'; '.join(problems[:3])}")
    else:
        detail = f"{len(summary.get('tiles', []))} tiles x {summary.get('nights')} nights read, no problems"
    report.add("satellite downloads", not problems, detail, time.time() - t)
    return table


def not_compared(report: Report) -> tuple[bool, str] | None:
    """With satellite files missing the rebuilt table cannot match, so the comparison is skipped and fails with the
    reason: a failed download must not read as different numbers as well."""
    missing = len(report.build["problems"])
    if not missing:
        return None
    return False, f"not compared: {missing} satellite files were not read (see 'satellite downloads'); run again"


def level1(report: Report, scratch: Path) -> None:
    table = rebuild(report, SAMPLE_COUNTIES, scratch)
    ok, detail = not_compared(report) or compare_tables(table, pd.read_parquet(SAMPLE))
    report.add("Ian: three sample counties rebuilt from NASA and EAGLE-I", ok, detail)


def level2(report: Report, scratch: Path) -> None:
    table = rebuild(report, None, scratch)
    ok, detail = not_compared(report) or compare_fingerprints(fingerprint(table),
                                                              json.loads(FINGERPRINT.read_text()))
    report.add("Ian: full rebuild against the committed fingerprint", ok, detail)


def write_fingerprint() -> int:
    source = REPO / "data/processed/county_nights_ian2022.parquet"
    if not source.exists():
        print(f"{source} is missing", file=sys.stderr)
        return 1
    FINGERPRINT.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINT.write_text(json.dumps(fingerprint(pd.read_parquet(source)), indent=1) + "\n")
    print(f"wrote {FINGERPRINT.relative_to(REPO)}")
    return 0


# --- main ------------------------------------------------------------------------------------------------------------

def scratch_folders(scratch: Path) -> tuple[Path, Path, Path]:
    """The three folders a rebuild writes into: the table and its summary, the quicklook figures, and the EAGLE-I
    extract (deleted first when one is there)."""
    return scratch, scratch / "img", scratch / "interim"


def same_place(folder: Path, protected: Path) -> bool:
    """`folder` is `protected` under another spelling: DATA for data where case does not count, or a link to it."""
    try:
        return protected.exists() and folder.exists() and folder.samefile(protected)
    except OSError:  # one of the two lies in a folder that may not be entered: no rebuild can write there either
        return False


def in_protected_folder(scratch: Path) -> bool:
    """A rebuild into `scratch` would write inside the repository's data/ or docs/ folder. That is so when `scratch`
    as it was typed is one of the two or lies inside one, and when one of the folders a rebuild writes into
    (scratch_folders), with every link followed, is or lies inside data/, docs/ or a PROTECTED_INSIDE folder, again
    with every link followed. Folders are compared as places on disk and not only as text: on a case-insensitive disk
    DATA/processed is data/processed, and a link is the folder it leads to, be the link data/ itself, data/processed
    (kept on another disk), the scratch folder or the interim/ inside it.

    Folders only, and only these: a link to a single file in a scratch folder is not followed, and any other link
    inside data/ or docs/ than the PROTECTED_INSIDE folders is refused under its own name but not at its target."""
    kept = [REPO / part for part in (*PROTECTED, *PROTECTED_INSIDE)]
    kept += [folder.resolve() for folder in kept]  # where a link leads, also while nothing is there (a disk unplugged)
    places = [Path(os.path.abspath(scratch)), *(folder.resolve() for folder in scratch_folders(scratch))]
    folders = [folder for place in places for folder in (place, *place.parents)]
    return (any(folder in kept for folder in folders)  # by name first: that needs no look at the disk
            or any(same_place(folder, protected) for folder in folders for protected in kept))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--level", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--report", type=Path, default=None,
                        help="where to write the JSON report (rewritten after every check)")
    parser.add_argument("--scratch", type=Path, default=None, help="folder for rebuilt tables (default: a temp dir)")
    parser.add_argument("--keep-scratch", action="store_true")
    parser.add_argument("--fingerprint", action="store_true", help="refresh docs/reproduce/ian2022_fingerprint.json")
    args = parser.parse_args(argv)
    if args.scratch is not None and in_protected_folder(args.scratch):
        parser.error("--scratch must be outside data/ and docs/ (links are followed, those of its img/ and interim/ "
                     "folders too): a rebuild there would overwrite the real tables, EAGLE-I extract or figures")
    if args.report is not None and in_protected_folder(Path(args.report).parent):
        parser.error("--report must be outside data/ and docs/: the report is rewritten after every check and "
                     "would replace a file of that name there")
    return args


def run_level(report: Report, args: argparse.Namespace) -> None:
    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="blackout-reproduce-"))
    try:
        (level1 if args.level == 1 else level2)(report, scratch)
    finally:
        if not args.keep_scratch and args.scratch is None:
            shutil.rmtree(scratch, ignore_errors=True)


def write_step_summary(report: Report) -> None:
    """On GitHub Actions, append the checks as a Markdown table to the run's summary page."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    rows = [f"| {c.name} | {'PASS' if c.passed else 'FAIL'} | {c.detail[:200].replace('|', '/')} | {c.seconds} |"
            for c in report.checks]
    lines = [f"## reproduce level {report.level}: {report.verdict}", "",
             "| check | result | detail | seconds |", "|---|---|---|---|", *rows, ""]
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.fingerprint:
        return write_fingerprint()
    started = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    report = Report(args.level, started, platform_name(), args.report)
    report.save()  # at once, as incomplete: a run killed before its first check must not leave an older report's PASS
    print(f"reproduce: level {args.level} on {report.platform}", flush=True)
    try:
        level0(report)
        if args.level >= 1 and report.clean and ensure_reference(report, args.level) and ensure_token(report):
            ensure_inputs(report)
        if args.level >= 1 and report.clean:
            run_level(report, args)
        report.complete = True  # only here: after an exception, Ctrl-C or a kill the report says it did not finish
    except Exception as err:  # noqa: BLE001 - the last resort: whatever failed, the report must say so and be written
        print(redact(traceback.format_exc()), file=sys.stderr, flush=True)
        report.add("run aborted", False, redact(f"{type(err).__name__}: {err}")[:300])
    finally:
        report.save()
        write_step_summary(report)
    print(f"reproduce: {report.verdict} ({len(report.checks)} checks)", flush=True)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
