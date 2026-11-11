"""Record the inputs of the one lockbox run, so any later rebuild is visible (test plan §0.3, LB-44).

Run once from the repo root, after `docs/lockbox_result.json` is frozen (LB-45):

    uv run python -I scripts/record_lockbox_inputs.py

It writes `docs/lockbox_record.json`: the sha256 of every table the run read (8 main, 2 locked, Uri, and the three
NOAA-20 cross-check tables), of `uv.lock` and of the frozen result; the Python, numpy, pandas, scikit-learn, scipy and
pyarrow versions; each file's mtime beside `provenance.run_at_utc`, flagging any table newer than the run; the drop
rule and the customer check on each locked table (facts the recorded code did not apply, LB-40 and LB-43); and when
each predictions file was written (the one-run evidence of LB-41). It reads the locked tables for those facts only,
fits nothing, and writes nothing under data/.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from blackout.storms import Storm, load_storms
from blackout.table import PROCESSED, drop_check, table_path

REPO = Path(__file__).resolve().parents[1]
FROZEN = REPO / "docs/lockbox_result.json"
LOCAL = PROCESSED / "lockbox_result.json"
RECORD = REPO / "docs/lockbox_record.json"
LIBRARIES = ("numpy", "pandas", "scikit-learn", "scipy", "pyarrow")
# noaa20_agreement reads both satellites' tables for these storms, and lee_on_noaa20 reads Ian's NOAA-20 table.
CROSS_CHECKS = (("ian2022", "VJ146A2"), ("ida2021", "VJ146A2"), ("beryl2024", "VNP46A2"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mtime_utc(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def file_facts(path: Path, run_at: datetime) -> dict:
    """Hash, size and when the file was last written, relative to the run."""
    written = mtime_utc(path)
    return {"sha256": sha256(path), "bytes": path.stat().st_size, "mtime_utc": written.isoformat(),
            "minutes_before_run": round((run_at - written).total_seconds() / 60, 2),
            "newer_than_run": written > run_at}


def table_record(storm: Storm, run_at: datetime, satellite: str | None = None) -> dict:
    path = table_path(storm, satellite)
    return {"storm_id": storm.id, "role": storm.role, "satellite": satellite or storm.satellite, "table": path.name,
            "rows": pq.read_metadata(path).num_rows, **file_facts(path, run_at)}


def environment() -> dict:
    return {"python": sys.version.split()[0], **{lib: importlib.metadata.version(lib) for lib in LIBRARIES}}


def customers_check(storm: Storm, table: pd.DataFrame) -> dict:
    """Does the locked table carry the repaired customer counts (LB-43)? Compared county by county."""
    from blackout.counties import load_counties

    per_fips = table.groupby("fips")["customers"].first().astype(float)
    repaired = load_counties(storm.states).set_index("fips")["customers"].astype(float).reindex(per_fips.index)
    differ = per_fips.index[~np.isclose(per_fips.to_numpy(), repaired.to_numpy(), equal_nan=True)]
    return {"counties": len(per_fips), "differ": len(differ), "match": bool(len(differ) == 0),
            "differing_fips": sorted(differ)[:20]}


def locked_facts(locked: list[Storm]) -> tuple[dict, dict]:
    """The drop rule and the customer check on each locked table; the tables are read for these facts only."""
    from blackout.counties import CENSUS

    drops, customers = {}, {"available": CENSUS.exists(), "per_storm": {}}
    for storm in locked:
        table = pd.read_parquet(table_path(storm), columns=["fips", "night", "status", "wind_band", "customers"])
        drops[storm.id] = drop_check(table, storm)
        if customers["available"]:
            customers["per_storm"][storm.id] = customers_check(storm, table)
    if not customers["available"]:
        customers["reason"] = f"{CENSUS.relative_to(REPO)} is absent, so load_counties cannot run"
    return drops, customers


def predictions_facts(storms: list[Storm], run_at: datetime) -> list[dict]:
    out = []
    for storm in storms:
        path = PROCESSED / f"predictions_{storm.id}.parquet"
        if path.exists():
            written = mtime_utc(path)
            out.append({"storm_id": storm.id, "file": path.name, "mtime_utc": written.isoformat(),
                        "minutes_from_run": round((written - run_at).total_seconds() / 60, 2)})
    return out


def build_record(frozen: Path = FROZEN) -> dict:
    result = json.loads(frozen.read_text())
    provenance = result["provenance"]
    run_at = datetime.fromisoformat(provenance["run_at_utc"])
    storms = load_storms()
    tables = [table_record(s, run_at) for s in storms]
    cross = [table_record(next(s for s in storms if s.id == sid), run_at, satellite) for sid, satellite in CROSS_CHECKS]
    drops, customers = locked_facts([s for s in storms if s.role == "lockbox"])
    return {
        "recorded_at_utc": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "result_file": str(frozen.relative_to(REPO)),
        "result_sha256": sha256(frozen),
        "run_at_utc": provenance["run_at_utc"],
        "git_head": provenance["git_head"],
        "environment": environment(),
        "uv_lock_sha256": sha256(REPO / "uv.lock"),
        "tables": tables,
        "cross_check_tables": cross,
        "rebuilt_after_run": any(t["newer_than_run"] for t in [*tables, *cross]),
        "predictions": predictions_facts(storms, run_at),
        "drop_rule": drops,
        "customers_check": customers,
    }


def main() -> int:
    if not FROZEN.exists():
        print(f"{FROZEN.relative_to(REPO)} is missing: copy data/processed/lockbox_result.json there first (LB-45)",
              file=sys.stderr)
        return 1
    if LOCAL.exists() and LOCAL.read_bytes() != FROZEN.read_bytes():
        print("the frozen record differs from data/processed/lockbox_result.json: nothing recorded", file=sys.stderr)
        return 1
    record = build_record()
    RECORD.write_text(json.dumps(record, indent=2) + "\n")
    newer = [t["table"] for t in [*record["tables"], *record["cross_check_tables"]] if t["newer_than_run"]]
    print(f"wrote {RECORD.relative_to(REPO)}: {len(record['tables'])} tables, {len(record['cross_check_tables'])} "
          f"cross-check tables, {len(record['predictions'])} predictions files; rebuilt after the run: {newer or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
