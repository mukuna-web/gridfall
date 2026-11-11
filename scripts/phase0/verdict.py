"""Phase 0 spike: score the Ian / Lee County night table against the rule logged before any satellite data.

Written by Claude at the user's request (see docs/decision-log.md, "Phase 0 calls"). The rule, applied as written:
- only nights after landfall where the county is visible (status ok), file dates Sep 29 to Oct 19, 2022;
- peak timing: the darkest night is within 1 night of the night with the highest official % out;
- recovery timing: the first night % darker falls below half its peak is within 2 nights of the first night the
  official % out falls below half its peak;
- same direction: Spearman rank correlation >= 0.6 when there are at least 5 visible nights;
- pass if peak and recovery timing hold, and same direction holds whenever it can be computed;
  inconclusive (too cloudy) with fewer than 3 visible nights; fail otherwise.
Run from the repo root: uv run python -I scripts/phase0/verdict.py
Reads data/interim/phase0_lee_nights.csv; writes data/interim/phase0_verdict.json and prints the same JSON.
"""

import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
NIGHTS_CSV = REPO / "data/interim/phase0_lee_nights.csv"
VERDICT_JSON = REPO / "data/interim/phase0_verdict.json"
FIRST_FILE, LAST_FILE = dt.date(2022, 9, 29), dt.date(2022, 10, 19)
PEAK_TOLERANCE_NIGHTS, RECOVERY_TOLERANCE_NIGHTS = 1, 2
MIN_NIGHTS_TO_JUDGE, MIN_NIGHTS_FOR_RANK, MIN_RANK_CORRELATION = 3, 5, 0.6
REQUIRED = ("file_date", "night", "status", "pct_darker", "eaglei_pct_out", "in_baseline", "after_landfall")


def load_nights(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing: run scripts/phase0/ian_lee.py first")
    table = pd.read_csv(path, parse_dates=["file_date", "night"])
    missing = [column for column in REQUIRED if column not in table.columns]
    if missing:
        raise ValueError(f"{path} lacks columns {missing}")
    return table.assign(file_date=table["file_date"].dt.date, night=table["night"].dt.date)


def visible_after_landfall(table: pd.DataFrame) -> pd.DataFrame:
    """The nights the rule judges: after landfall, status ok, both values present, in the logged date range."""
    in_range = table["file_date"].between(FIRST_FILE, LAST_FILE)
    usable = table["status"].eq("ok") & table["pct_darker"].notna() & table["eaglei_pct_out"].notna()
    return table[in_range & table["after_landfall"].astype(bool) & usable].sort_values("night")


def peak_night(series: pd.Series, nights: pd.Series) -> dt.date:
    return nights.loc[series.idxmax()]


def half_recovery_night(series: pd.Series, nights: pd.Series) -> dt.date | None:
    """The first night after the peak whose value falls below half the peak; None if it never does."""
    peak_at = series.idxmax()
    after = series.loc[nights > nights.loc[peak_at]]
    below = after[after < series.loc[peak_at] / 2]
    return nights.loc[below.index[0]] if len(below) else None


def spearman(a: pd.Series, b: pd.Series) -> float:
    ranks_a, ranks_b = a.rank().to_numpy(float), b.rank().to_numpy(float)
    if np.std(ranks_a) == 0 or np.std(ranks_b) == 0:
        return math.nan
    return float(np.corrcoef(ranks_a, ranks_b)[0, 1])


def nights_apart(a: dt.date | None, b: dt.date | None) -> int | None:
    return None if a is None or b is None else abs((a - b).days)


def judge(table: pd.DataFrame) -> dict:
    seen = visible_after_landfall(table)
    baseline = table[table["in_baseline"].astype(bool) & table["status"].eq("ok") & table["pct_darker"].notna()]
    noise = {"n_nights": len(baseline),
             "mean_pct_darker": float(baseline["pct_darker"].mean()) if len(baseline) else None,
             "sd_pct_darker": float(baseline["pct_darker"].std()) if len(baseline) > 1 else None}
    result = {"rule": "docs/decision-log.md, 2026-11-06 Phase 0 calls", "n_visible_nights": len(seen),
              "visible_nights": [str(night) for night in seen["night"]], "baseline_noise": noise}
    if len(seen) < MIN_NIGHTS_TO_JUDGE:
        return {**result, "verdict": "inconclusive: too cloudy", "reason": f"{len(seen)} visible nights after "
                f"landfall, fewer than {MIN_NIGHTS_TO_JUDGE}"}

    darker, out, nights = seen["pct_darker"], seen["eaglei_pct_out"], seen["night"]
    peaks = {"darker": peak_night(darker, nights), "official": peak_night(out, nights)}
    recoveries = {"darker": half_recovery_night(darker, nights), "official": half_recovery_night(out, nights)}
    peak_gap = nights_apart(peaks["darker"], peaks["official"])
    recovery_gap = nights_apart(recoveries["darker"], recoveries["official"])
    rho = spearman(darker, out) if len(seen) >= MIN_NIGHTS_FOR_RANK else math.nan

    checks = {
        "peak_timing": {"darker_peak_night": str(peaks["darker"]), "official_peak_night": str(peaks["official"]),
                        "nights_apart": peak_gap, "holds": peak_gap <= PEAK_TOLERANCE_NIGHTS},
        "recovery_timing": {"darker_half_night": str(recoveries["darker"]),
                            "official_half_night": str(recoveries["official"]), "nights_apart": recovery_gap,
                            "holds": None if recovery_gap is None else recovery_gap <= RECOVERY_TOLERANCE_NIGHTS},
        "same_direction": {"spearman": None if math.isnan(rho) else round(rho, 3),
                           "holds": None if math.isnan(rho) else rho >= MIN_RANK_CORRELATION},
    }
    if checks["recovery_timing"]["holds"] is None:
        both_missing = recoveries["darker"] is None and recoveries["official"] is None
        if both_missing:
            return {**result, "checks": checks, "verdict": "inconclusive: neither line recovers to half its peak",
                    "reason": "the recovery rule cannot be applied inside the logged window"}
        checks["recovery_timing"]["holds"] = False  # one line recovered and the other did not
    timing_ok = checks["peak_timing"]["holds"] and checks["recovery_timing"]["holds"]
    direction_ok = checks["same_direction"]["holds"] is not False
    verdict = "pass" if timing_ok and direction_ok else "fail"
    return {**result, "checks": checks, "verdict": verdict}


def main() -> int:
    try:
        result = judge(load_nights(NIGHTS_CSV))
    except (FileNotFoundError, ValueError) as exc:
        print(f"verdict.py: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2)
    VERDICT_JSON.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
