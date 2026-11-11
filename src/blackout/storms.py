"""Storm records from config/storms.yaml (Task 4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml

from blackout.outages import STATE_FIPS

REPO = Path(__file__).resolve().parents[2]
STORMS_YAML = REPO / "config/storms.yaml"
BASELINE_GAP = timedelta(days=3)
BASELINE_LENGTH = timedelta(days=30)
WINDOW_LENGTH = timedelta(days=21)
ROLES = ("main", "lockbox", "stress")
SATELLITES = ("VNP46A2", "VJ146A2")


@dataclass(frozen=True)
class Storm:
    id: str
    name: str
    atcf_id: str | None
    landfall: date
    baseline_start: date
    baseline_end: date
    window_end: date
    role: Literal["main", "lockbox", "stress"]
    states: tuple[str, ...]
    allow_snow: bool = False
    landfall_utc: str | None = None
    satellite: str = "VNP46A2"  # the storm's own table; VJ146A2 only where Suomi NPP has a gap

    @property
    def landfall_time(self) -> pd.Timestamp:
        """When the clock starts for waiting periods: the HURDAT2 landfall record's UTC time, else 00:00 UTC."""
        if self.landfall_utc:
            return pd.Timestamp(self.landfall_utc).tz_convert("UTC")
        return pd.Timestamp(self.landfall, tz="UTC")

    @property
    def nights(self) -> list[date]:
        """Every night the table covers, baseline_start to window_end inclusive."""
        return [self.baseline_start + timedelta(days=k) for k in range((self.window_end - self.baseline_start).days + 1)]

    @property
    def baseline_nights(self) -> list[date]:
        return [n for n in self.nights if n <= self.baseline_end]

    @property
    def state_prefixes(self) -> set[str]:
        return {STATE_FIPS[s] for s in self.states}


def _date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def storm_from_record(record: dict) -> Storm:
    landfall = _date(record["landfall"])
    baseline_end = _date(record.get("baseline_end", landfall - BASELINE_GAP))
    role = record["role"]
    if record.get("satellite", "VNP46A2") not in SATELLITES:
        raise ValueError(f"{record['id']}: satellite must be one of {SATELLITES}")
    if role not in ROLES:
        raise ValueError(f"{record['id']}: role must be one of {ROLES}, got {role!r}")
    states = tuple(record["states"])
    unknown = [s for s in states if s not in STATE_FIPS]
    if unknown:
        raise ValueError(f"{record['id']}: unknown USPS codes {unknown}")
    return Storm(
        id=record["id"],
        name=record["name"],
        atcf_id=record.get("atcf_id"),
        landfall=landfall,
        baseline_start=_date(record.get("baseline_start", baseline_end - BASELINE_LENGTH)),
        baseline_end=baseline_end,
        window_end=_date(record.get("window_end", landfall + WINDOW_LENGTH)),
        role=role,
        states=states,
        allow_snow=bool(record.get("allow_snow", False)),
        landfall_utc=record.get("landfall_utc"),
        satellite=record.get("satellite", "VNP46A2"),
    )


def load_storms(path: Path = STORMS_YAML) -> list[Storm]:
    records = yaml.safe_load(Path(path).read_text())["storms"]
    storms = [storm_from_record(r) for r in records]
    ids = [s.id for s in storms]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate storm ids in storms.yaml")
    return storms


def get_storm(storm_id: str, path: Path = STORMS_YAML) -> Storm:
    for storm in load_storms(path):
        if storm.id == storm_id:
            return storm
    raise KeyError(f"no storm {storm_id!r} in {path}")
