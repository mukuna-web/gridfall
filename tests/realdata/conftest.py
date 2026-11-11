"""Real-data tests: they run only where the built tables exist, and `lockbox`-marked ones only with --run-lockbox.

Every test in this folder is skipped, with a reason naming the missing file, when `data/processed/lockbox_result.json`
is absent (CI, a fresh clone). `lockbox`-marked tests are skipped without `--run-lockbox` (declared in
tests/conftest.py) and when the frozen record `docs/lockbox_result.json` is absent. Fixtures cache the recorded
result, the record of its inputs and the locked tables once per session; nothing here writes under data/ or docs/.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from blackout.storms import Storm, load_storms
from blackout.table import table_path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROCESSED_RESULT = REPO / "data/processed/lockbox_result.json"
FROZEN_RESULT = REPO / "docs/lockbox_result.json"
RECORD = REPO / "docs/lockbox_record.json"
# The allowed skip reasons, each naming the file or flag it waits for (test plan §6, "What may skip").
SKIP_NO_DATA = (f"{PROCESSED_RESULT.relative_to(REPO)} is absent: the built tables and the recorded opening exist "
                "only on the machine that ran `blackout lockbox`")
SKIP_NO_FLAG = "marked lockbox: pass --run-lockbox to read the locked tables and the recorded opening"
SKIP_NO_FROZEN = f"{FROZEN_RESULT.relative_to(REPO)} is absent: freeze the record first (test plan LB-45)"


def _skip_reason(item: pytest.Item, run_lockbox: bool) -> str | None:
    if not PROCESSED_RESULT.exists():
        return SKIP_NO_DATA
    if item.get_closest_marker("lockbox") is None:
        return None
    if not run_lockbox:
        return SKIP_NO_FLAG
    if not FROZEN_RESULT.exists():
        return SKIP_NO_FROZEN
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_lockbox = bool(config.getoption("--run-lockbox"))
    for item in items:
        if not Path(str(item.path)).resolve().is_relative_to(HERE):
            continue
        reason = _skip_reason(item, run_lockbox)
        if reason is not None:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def recorded() -> dict:
    """The frozen result of the one opening, `docs/lockbox_result.json` (LB-45)."""
    return json.loads(FROZEN_RESULT.read_text())


@pytest.fixture(scope="session")
def record() -> dict:
    """The record of the run's inputs, `docs/lockbox_record.json` (LB-44)."""
    if not RECORD.exists():
        raise FileNotFoundError(f"{RECORD.relative_to(REPO)} is missing: run scripts/record_lockbox_inputs.py once")
    return json.loads(RECORD.read_text())


@pytest.fixture(scope="session")
def locked_storms() -> list[Storm]:
    return [s for s in load_storms() if s.role == "lockbox"]


@pytest.fixture(scope="session")
def locked_tables(locked_storms: list[Storm]) -> dict[str, pd.DataFrame]:
    """Each locked storm's own table, read once. Allowed after the opening; it never reaches a fit."""
    return {s.id: pd.read_parquet(table_path(s)) for s in locked_storms}


@pytest.fixture(scope="session")
def git() -> Callable[..., str]:
    """Run git in the repo and return stdout; raises CalledProcessError on a non-zero exit."""
    def run(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()

    return run
