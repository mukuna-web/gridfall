"""Synthetic policies and claims for the app's portfolio example (Task 10).

No real policyholder data may be used (design, anti-goals), so the book is made up: policies are placed in counties in
proportion to Census housing units, and claims are drawn around each county's official restoration day, with a share
deliberately inflated past it so the app's claim check has something to flag. Both are deterministic for a seed, so a
fresh clone rebuilds the exact same demo.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

POLICY_COUNT = 100_000
BUSINESS_SHARE = 0.05
SEED = 20261105
CLAIM_COUNT = 200
INFLATED_SHARE = 0.1
NEAR_FACTOR = (0.3, 1.0)  # an honest claim: somewhere between 30% and 100% of the county's official restore day
INFLATED_FACTOR = (1.6, 3.0)  # an inflated claim: 1.6x to 3x the official day ...
MIN_INFLATION_DAYS = 3.0  # ... and at least 3 days past it, so short outages still give a clear flag
PORTFOLIO_COLUMNS = ["policy_id", "fips", "kind"]
CLAIM_COLUMNS = ["claim_id", "policy_id", "fips", "claimed_days_out"]


def _check_count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return int(value)


def _check_share(value: float, name: str) -> float:
    if not (isinstance(value, (int, float, np.floating)) and 0.0 <= float(value) <= 1.0):
        raise ValueError(f"{name} must be a share between 0 and 1, got {value!r}")
    return float(value)


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{label} lacks columns {missing}")


def housing_weights(counties: pd.DataFrame) -> pd.Series:
    """Each county's share of all housing units, indexed by fips and sorted by it.

    Sorting makes the book independent of the input's row order. A county join that went wrong (duplicate or
    malformed fips, missing or negative housing) raises here rather than skewing the book.
    """
    _require_columns(counties, ("fips", "housing_units"), "counties")
    fips = counties["fips"].astype(str)
    malformed = sorted(fips[~fips.str.fullmatch(r"\d{5}")])
    if malformed:
        raise ValueError(f"fips must be 5-digit strings, got {malformed[:5]}")
    if fips.duplicated().any():
        raise ValueError(f"duplicate fips in counties: {sorted(fips[fips.duplicated()])[:5]}")
    housing = pd.to_numeric(counties["housing_units"], errors="coerce").astype(float)
    if housing.isna().any() or (housing < 0).any() or not np.isfinite(housing).all():
        raise ValueError("housing_units must be finite and non-negative for every county")
    total = housing.sum()
    if total <= 0:
        raise ValueError("counties have no housing units, so there is nowhere to place policies")
    return pd.Series((housing / total).to_numpy(), index=fips.to_numpy()).sort_index()


def make_portfolio(counties: pd.DataFrame, n: int = POLICY_COUNT, business_share: float = BUSINESS_SHARE,
                   seed: int = SEED) -> pd.DataFrame:
    """`n` synthetic policies: policy_id ("P000001", ...), fips and kind ("home" or "business").

    Policies per county are one multinomial draw over housing shares, and each policy's kind is drawn from the same
    generator, so one seed fixes the whole book.
    """
    n = _check_count(n, "n")
    business_share = _check_share(business_share, "business_share")
    weights = housing_weights(counties)
    rng = np.random.default_rng(seed)
    per_county = rng.multinomial(n, weights.to_numpy())
    is_business = rng.random(n) < business_share
    return pd.DataFrame({
        "policy_id": [f"P{k:06d}" for k in range(1, n + 1)],
        "fips": np.repeat(weights.index.to_numpy(), per_county),
        "kind": np.where(is_business, "business", "home"),
    }, columns=PORTFOLIO_COLUMNS)


def usable_restore_days(official_restore: Mapping[str, float | None]) -> dict[str, float]:
    """Counties whose official restore day can anchor a claim: finite and after landfall.

    A county with no restore day (EAGLE-I never showed it restored, or had no usable count) or with a day at or
    before landfall had no outage to claim against, so it gets no claims.
    """
    days = {}
    for fips, day in official_restore.items():
        if day is None:
            continue
        value = float(day)
        if np.isfinite(value) and value > 0:
            days[str(fips)] = value
    return days


def make_claims(portfolio: pd.DataFrame, official_restore: Mapping[str, float | None], n: int = CLAIM_COUNT,
                inflated_share: float = INFLATED_SHARE, seed: int = SEED) -> pd.DataFrame:
    """Synthetic claims: claim_id ("C0001", ...), policy_id, fips and claimed_days_out (days, one decimal).

    Claims go to distinct policies in counties with a usable official restore day; at most `n`, fewer when the book
    has fewer such policies. Honest claims sit at 0.3x-1.0x of the county's day (rounded down, so never past it);
    `inflated_share` of them are inflated to 1.6x-3x and at least 3 days past it (rounded up), so the claim check
    can tell the two apart.
    """
    n = _check_count(n, "n")
    inflated_share = _check_share(inflated_share, "inflated_share")
    _require_columns(portfolio, ("policy_id", "fips"), "portfolio")
    days = usable_restore_days(official_restore)
    eligible = portfolio[portfolio["fips"].isin(list(days))]
    size = min(n, len(eligible))
    if size == 0:
        return pd.DataFrame({c: pd.Series(dtype=float if c == "claimed_days_out" else object) for c in CLAIM_COLUMNS})
    rng = np.random.default_rng(seed)
    picked = eligible.iloc[rng.choice(len(eligible), size=size, replace=False)]  # random order mixes counties
    restore = picked["fips"].map(days).to_numpy(dtype=float)
    inflated = np.zeros(size, dtype=bool)
    inflated[rng.choice(size, size=round(inflated_share * size), replace=False)] = True
    near = np.floor(rng.uniform(*NEAR_FACTOR, size) * restore * 10) / 10
    far = np.ceil(np.maximum(rng.uniform(*INFLATED_FACTOR, size) * restore, restore + MIN_INFLATION_DAYS) * 10) / 10
    return pd.DataFrame({
        "claim_id": [f"C{k:04d}" for k in range(1, size + 1)],
        "policy_id": picked["policy_id"].to_numpy(),
        "fips": picked["fips"].to_numpy(),
        "claimed_days_out": np.where(inflated, far, near),
    }, columns=CLAIM_COLUMNS)
