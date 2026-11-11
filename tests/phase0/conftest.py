"""Pytest setup for the Phase 0 Ian / Lee County tests.

All inputs are synthetic (phase0_fakes.py); nothing reaches the network or the real tiles. This makes the helper
module importable whatever pytest import mode is in use.
"""

import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
