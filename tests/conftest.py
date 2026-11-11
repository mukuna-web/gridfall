"""Shared pytest setup: the fixture builders in tests/fixtures/ are importable as plain modules, and the
`--run-lockbox` flag gates the tests that read the locked tables (tests/realdata/, test plan RH-02).

The flag is declared here rather than in tests/realdata/conftest.py because pytest reads options only from the
conftests it loads at start-up: those of the directories named on the command line and their parents. Declaring it
here makes `uv run pytest --run-lockbox` work from the repo root as well as from tests/realdata.
"""

import sys
from pathlib import Path

import pytest

FIXTURES = str(Path(__file__).resolve().parent / "fixtures")
if FIXTURES not in sys.path:
    sys.path.insert(0, FIXTURES)

RUN_LOCKBOX = "--run-lockbox"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(RUN_LOCKBOX, action="store_true", default=False,
                     help="run the tests marked `lockbox`: they read the locked Helene and Milton tables and the "
                          "recorded opening (docs/lockbox_result.json); allowed after the opening, never for a fit")
