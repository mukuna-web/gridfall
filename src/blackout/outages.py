"""EAGLE-I outages: loading, feed-dropout flags, county counts at a pass time, customers and coverage.

EAGLE-I stamps every 15-minute scraper run in naive UTC. Three cases must stay apart (docs/plan.md, Review
Focus 1): a county with no row in a live run has zero customers out; an empty count is missing; and a run with
no rows for the whole state was missed by the scraper. Feed dropouts, where the scraper loses one utility's feed
for a few runs, are found by `flag_dropouts` and dropped before taking a median (decision log, 2026-11-08).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

EAGLEI_TZ: str = "UTC"

# USPS code -> 2-digit FIPS for every code in EAGLE-I's coverage_history.csv: 50 states, DC and 5 territories.
STATE_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35",
    "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "AS": "60", "GU": "66", "MP": "69", "PR": "72", "VI": "78",
}

# The dropout rule's constants (decision log, 2026-11-08). HOLD_RUNS is fixed: the steps use runs i-2, i-1, j, j+1.
DIP_RATIO = 0.93
MAX_DIP = pd.Timedelta(hours=3)
FEED_SHARE = 0.5
HOLD_RUNS = 2

COLUMNS = ["fips", "time", "customers_out"]


def _require_aware(ts: pd.Timestamp, name: str) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        raise ValueError(f"{name} must be time-zone aware (EAGLE-I stamps are UTC), got {ts}")
    return ts


def _naive_utc(ts: pd.Timestamp) -> object:
    """DuckDB compares tz-aware bounds in its session zone, so bind bounds as naive UTC."""
    return ts.tz_convert("UTC").tz_localize(None).to_pydatetime()


def _quoted(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _reader(con: duckdb.DuckDBPyConnection, source: Path) -> str:
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return f"read_csv({_quoted(source)}, types={{'fips_code': 'VARCHAR'}})"
    if suffix == ".parquet":
        reader = f"read_parquet({_quoted(source)})"
        kinds = dict(con.execute(f"select column_name, column_type from (describe select * from {reader})").fetchall())
        if kinds.get("fips_code") != "VARCHAR":
            raise ValueError(f"{source.name}: fips_code must be VARCHAR, found {kinds.get('fips_code')}")
        return reader
    raise ValueError(f"{source.name}: expected a .csv or .parquet file")


def load_outages(source: Path, states: set[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Rows of `states` (2-digit FIPS prefixes) with start <= time < end, as fips / time (UTC) / customers_out.

    Every county of each state is kept, because `flag_dropouts` needs whole states. Absent counties are not added
    and empty counts stay NaN.
    """
    start, end = _require_aware(start, "start"), _require_aware(end, "end")
    bad = sorted(s for s in states if not (isinstance(s, str) and len(s) == 2 and s.isdigit()))
    if bad:
        raise ValueError(f"states must be 2-digit FIPS prefixes such as '12' (see STATE_FIPS), got {bad}")
    source = Path(source)
    con = duckdb.connect()
    try:
        reader = _reader(con, source)
        frame = con.execute(
            f"""select fips_code as fips, run_start_time as time, cast(customers_out as double) as customers_out
                from {reader}
                where list_contains(?, left(fips_code, 2)) and run_start_time >= ? and run_start_time < ?
                order by run_start_time, fips_code""",
            [sorted(states), _naive_utc(start), _naive_utc(end)],
        ).df()
    finally:
        con.close()
    return pd.DataFrame({
        "fips": frame["fips"].astype(object),
        "time": pd.to_datetime(frame["time"]).dt.tz_localize(EAGLEI_TZ),
        "customers_out": frame["customers_out"].astype("float64"),
    })


def _empty_flags() -> pd.DataFrame:
    return pd.DataFrame({"fips": pd.Series(dtype=object), "time": pd.Series(dtype="datetime64[ns, UTC]")})


def _dip_end(times: pd.DatetimeIndex, totals: np.ndarray, i: int, level: float) -> int | None:
    """Step 3: the first run j after i where runs j and j+1 are back to DIP_RATIO * level, within MAX_DIP of i-1."""
    floor = DIP_RATIO * level
    j = i + 1
    while j + 1 < len(totals) and times[j] - times[i - 1] <= MAX_DIP:
        if totals[j] >= floor and totals[j + 1] >= floor:
            return j
        j += 1
    return None


def _walk_state(times: pd.DatetimeIndex, values: np.ndarray, counties: list[str]) -> list[tuple[str, pd.Timestamp]]:
    """Steps 2-7 for one state's live runs (rows) by counties (columns), with absent and empty cells read as 0."""
    totals = values.sum(axis=1)
    flags: list[tuple[str, pd.Timestamp]] = []
    i = HOLD_RUNS
    while i < len(totals):
        level = min(totals[i - 2], totals[i - 1])
        if not totals[i] < DIP_RATIO * level:
            i += 1
            continue
        j = _dip_end(times, totals, i, level)
        if j is None:
            i += 1
            continue
        shoulder = values[[i - 2, i - 1, j, j + 1]].min(axis=0)
        dip = values[i:j]
        low = dip < DIP_RATIO * shoulder
        taking_part = low[0]
        county_loss = float((shoulder[taking_part] - dip[:, taking_part].min(axis=0)).sum())
        state_loss = float(min(level, totals[j], totals[j + 1]) - totals[i:j].min())
        if taking_part.any() and county_loss >= FEED_SHARE * state_loss:
            for c in np.flatnonzero(taking_part):
                flags.extend((counties[c], times[i + r]) for r in np.flatnonzero(low[:, c]))
        i = j + HOLD_RUNS
    return flags


def flag_dropouts(outages: pd.DataFrame) -> pd.DataFrame:
    """Feed-dropout readings (fips, time): counties whose drop makes their state's total a short V (Task 2)."""
    if outages is None or outages.empty:
        return _empty_flags()
    flags: list[tuple[str, pd.Timestamp]] = []
    for _, rows in outages.groupby(outages["fips"].str[:2], sort=True):
        wide = rows.pivot(index="time", columns="fips", values="customers_out").sort_index().fillna(0.0)
        flags.extend(_walk_state(wide.index, wide.to_numpy(dtype=float), list(wide.columns)))
    if not flags:
        return _empty_flags()
    out = pd.DataFrame(flags, columns=["fips", "time"])
    out["time"] = pd.to_datetime(out["time"], utc=True)
    return out.sort_values(["time", "fips"]).reset_index(drop=True)


@dataclass(frozen=True)
class _StateRuns:
    times: np.ndarray  # live runs of the state, int64 ns UTC, sorted
    columns: dict[str, int]  # fips -> column in values
    values: np.ndarray  # runs x counties; absent = 0, empty or flagged = NaN


class OutageIndex:
    """Precomputed live runs per state, so county medians at many pass times stay fast (Task 5 builds one per storm).

    Gives the same numbers as `customers_out_at`, which builds a one-off index.
    """

    def __init__(self, outages: pd.DataFrame, dropouts: pd.DataFrame | None) -> None:
        self._states: dict[str, _StateRuns] = {}
        if outages is None or outages.empty:
            return
        flagged: dict[str, list[int]] = {}
        if dropouts is not None and not dropouts.empty:
            stamps = pd.to_datetime(dropouts["time"], utc=True).dt.as_unit("ns").astype("int64")
            for fips, t in zip(dropouts["fips"], stamps):
                flagged.setdefault(fips, []).append(int(t))
        for state, rows in outages.groupby(outages["fips"].str[:2], sort=True):
            wide = rows.pivot(index="time", columns="fips", values="customers_out").sort_index()
            present = rows.assign(_one=1.0).pivot(index="time", columns="fips", values="_one").reindex_like(wide)
            values = wide.to_numpy(dtype=float).copy()
            values[np.isnan(present.to_numpy(dtype=float))] = 0.0  # no row in a live run: zero customers out
            times = wide.index.as_unit("ns").asi8
            columns = {fips: k for k, fips in enumerate(wide.columns)}
            for fips, col in columns.items():
                hits = np.searchsorted(times, flagged.get(fips, []))
                for hit, t in zip(hits, flagged.get(fips, [])):
                    if hit < len(times) and times[hit] == t:
                        values[hit, col] = np.nan
            self._states[state] = _StateRuns(times, columns, values)

    def at(self, fips: str, when: pd.Timestamp, window_minutes: int = 60) -> float:
        """Median over the state's live runs within window_minutes of `when` (both ends included); NaN if none usable."""
        when = _require_aware(when, "when")
        runs = self._states.get(fips[:2])
        if runs is None:
            return float("nan")
        centre = when.tz_convert("UTC").as_unit("ns").value
        half = pd.Timedelta(minutes=window_minutes).value
        lo = np.searchsorted(runs.times, centre - half, side="left")
        hi = np.searchsorted(runs.times, centre + half, side="right")
        if hi <= lo:
            return float("nan")
        col = runs.columns.get(fips)
        window = np.zeros(hi - lo) if col is None else runs.values[lo:hi, col]
        usable = window[~np.isnan(window)]
        return float(np.median(usable)) if usable.size else float("nan")


def customers_out_at(outages: pd.DataFrame, fips: str, when: pd.Timestamp, window_minutes: int = 60,
                     dropouts: pd.DataFrame | None = None) -> float:
    """Median customers out over the state's live runs with |time - when| <= window_minutes, flagged runs dropped.

    A run reads the county's count, or 0.0 when the county has no row; an empty count makes the run unusable.
    `dropouts=None` runs `flag_dropouts(outages)` first. Never filter `outages` to one county beforehand.
    """
    when = _require_aware(when, "when")
    if outages is None or outages.empty:
        return float("nan")
    state_rows = outages[outages["fips"].str[:2] == fips[:2]]
    if dropouts is None:
        dropouts = flag_dropouts(outages)
    return OutageIndex(state_rows, dropouts).at(fips, when, window_minutes)


def load_mcc(csv_path: Path) -> dict[str, int]:
    """EAGLE-I's modeled customer counts per county: BOM and CRLF handled, `Grand Total` dropped, codes padded."""
    counts: dict[str, int] = {}
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as fh:
        rows = csv.reader(fh)
        next(rows)
        for row in rows:
            if not row or row[0].strip() == "Grand Total":
                continue
            counts[row[0].strip().zfill(5)] = int(row[1])
    return counts


def coverage_for(coverage_csv: Path, state: str, year: int) -> float:
    """`max_pct_covered` for a USPS `state` in `year`, falling back to the latest earlier year (file: 2018-2022)."""
    if year < 2018:
        raise ValueError(f"EAGLE-I coverage history starts in 2018, got {year}")
    table = pd.read_csv(coverage_csv, dtype={"state": str})
    table = table.assign(yr=pd.to_datetime(table["year"], format="%m/%d/%y").dt.year)
    rows = table[(table["state"] == state) & (table["yr"] <= year)]
    if rows.empty:
        raise ValueError(f"no coverage row for {state!r} at or before {year}")
    return float(rows.sort_values("yr").iloc[-1]["max_pct_covered"])
