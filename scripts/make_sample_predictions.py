"""Write data/sample/predictions_ian_sample.parquet and its metadata, predictions_ian_sample.json.

The parquet holds the final fit's estimates for the three sample counties, cut from data/processed/
predictions_ian2022.parquet (written by `uv run blackout lockbox`). The metadata says where the rows came from: the
source file and its sha256, the lockbox run they belong to (data/processed/lockbox_result.json's provenance), the
sample's own sha256 and its row counts. tests/test_export_integrity.py reads it, so a sample that is stale, hand-made
or cut from another run fails a test instead of passing as a demo (test-plan PX-01, RD-35).

Run from the repo root after the lockbox run: uv run python -I scripts/make_sample_predictions.py
The sample table (county_nights_ian_sample.parquet) and shapes are already committed; this adds est / lo / hi so
`blackout export --sample` shows real estimates offline. The parquet is rewritten only when its rows change, so a
rerun that changes nothing leaves the committed bytes (and their sha256) alone.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "data/processed/predictions_ian2022.parquet"
LOCKBOX = REPO / "data/processed/lockbox_result.json"
TABLE = REPO / "data/sample/county_nights_ian_sample.parquet"
TARGET = REPO / "data/sample/predictions_ian_sample.parquet"
COUNTIES = ("12071", "12015", "12021")  # Lee, Charlotte, Collier


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cut_sample(source: Path, table: Path, counties: tuple[str, ...] = COUNTIES) -> pd.DataFrame:
    """The source's rows for the sample counties; every county-night of the sample table must have one."""
    if not source.exists():
        raise FileNotFoundError(f"{source} is missing: run `uv run blackout lockbox` first")
    predictions = pd.read_parquet(source)
    sample = predictions[predictions["fips"].isin(counties)].reset_index(drop=True)
    rows = pd.read_parquet(table)
    missing = set(zip(rows["fips"], rows["night"])) - set(zip(sample["fips"], sample["night"]))
    if missing:
        raise ValueError(f"{len(missing)} sample county-nights have no prediction row in {source.name}")
    return sample


def lockbox_provenance(lockbox: Path) -> dict[str, str]:
    """The commit and time of the lockbox run the source predictions were written by."""
    if not lockbox.exists():
        raise FileNotFoundError(f"{lockbox} is missing: the sample is cut from the lockbox run's predictions")
    provenance = json.loads(lockbox.read_text(encoding="utf-8"))["provenance"]
    return {"lockbox_git_head": str(provenance["git_head"]), "lockbox_run_at_utc": str(provenance["run_at_utc"])}


def write_parquet_if_changed(sample: pd.DataFrame, target: Path) -> bool:
    """Write `sample` unless `target` already holds exactly these rows; returns whether it was written."""
    if target.exists() and pd.read_parquet(target).equals(sample):
        return False
    sample.to_parquet(target, index=False)
    return True


def metadata(sample: pd.DataFrame, source: Path, target: Path, provenance: dict[str, str], repo: Path) -> dict:
    """What predictions_ian_sample.json records: where the rows came from, what was written, and the lockbox run."""
    counts = sample["status"].value_counts().sort_index()
    return {
        "source": source.relative_to(repo).as_posix(),
        "source_sha256": sha256(source),
        "sample": target.relative_to(repo).as_posix(),
        "sample_sha256": sha256(target),
        "counties": sorted(set(sample["fips"].astype(str))),
        "rows": len(sample),
        "rows_with_estimate": int(sample["est"].notna().sum()),
        "rows_by_status": {str(status): int(count) for status, count in counts.items()},
        **provenance,
    }


def write_sample(source: Path, table: Path, target: Path, lockbox: Path, repo: Path) -> dict:
    """Cut the sample, write the parquet (when its rows changed) and its metadata JSON; returns the metadata."""
    sample = cut_sample(source, table)
    provenance = lockbox_provenance(lockbox)  # before any write: a missing lockbox record leaves nothing behind
    write_parquet_if_changed(sample, target)
    meta = metadata(sample, source, target, provenance, repo)
    target.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main() -> int:
    try:
        meta = write_sample(SOURCE, TABLE, TARGET, LOCKBOX, REPO)
    except (FileNotFoundError, ValueError, KeyError) as err:
        print(err, file=sys.stderr)
        return 1
    print(f"{meta['sample']}: {meta['rows']} rows, {meta['rows_with_estimate']} with an estimate, from "
          f"{meta['source']} (sha256 {meta['source_sha256'][:16]}, lockbox run at {meta['lockbox_git_head'][:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
