"""Task 10: the synthetic book of policies and claims (docs/plan.md, Week 6).

Everything is synthetic: a handful of made-up counties with housing-unit counts, and made-up official restore days.
"""

import math

import numpy as np
import pandas as pd
import pytest

from blackout.portfolio import make_claims, make_portfolio

HOUSING = {"12071": 300_000, "12015": 120_000, "12021": 230_000, "13051": 50_000, "12087": 0}
RESTORE = {"12071": 6.0, "12015": 4.0, "12021": 2.0, "13051": math.nan}
CLAIM_COLUMNS = ["claim_id", "policy_id", "fips", "claimed_days_out"]


def county_table(housing: dict[str, float] = HOUSING) -> pd.DataFrame:
    return pd.DataFrame({"fips": list(housing), "housing_units": list(housing.values())})


def test_portfolio_deterministic():
    counties = county_table()
    before = counties.copy()
    book = make_portfolio(counties)
    pd.testing.assert_frame_equal(book, make_portfolio(counties))
    pd.testing.assert_frame_equal(book, make_portfolio(counties.iloc[::-1].reset_index(drop=True)))  # row order
    pd.testing.assert_frame_equal(counties, before)  # the input is never modified
    assert list(book.columns) == ["policy_id", "fips", "kind"]
    assert len(book) == 100_000 and book["policy_id"].is_unique
    assert (book["policy_id"].iloc[0], book["policy_id"].iloc[-1]) == ("P000001", "P100000")
    assert set(book["kind"]) == {"home", "business"}
    assert not make_portfolio(counties, seed=1)["fips"].equals(book["fips"])


def test_portfolio_follows_housing():
    """Each county's share of the book is within 1% of the book (1 percentage point) of its share of housing."""
    counties = county_table()
    book = make_portfolio(counties)
    share = book["fips"].value_counts(normalize=True)
    housing = counties.set_index("fips")["housing_units"]
    for fips, want in (housing / housing.sum()).items():
        assert abs(share.get(fips, 0.0) - want) <= 0.01, fips
    assert "12087" not in share.index  # no homes, no policies
    assert abs((book["kind"] == "business").mean() - 0.05) <= 0.005
    small = make_portfolio(counties, n=1_000, business_share=0.0)
    assert len(small) == 1_000 and set(small["kind"]) == {"home"}


@pytest.mark.parametrize("housing", [{}, {"12071": 0}, {"12071": -5, "12015": 10}, {"12071": math.nan}])
def test_portfolio_rejects_bad_housing(housing):
    with pytest.raises(ValueError):
        make_portfolio(county_table(housing))


def test_portfolio_rejects_bad_arguments():
    with pytest.raises(ValueError):
        make_portfolio(pd.DataFrame({"fips": ["12071", "12071"], "housing_units": [1, 2]}))
    with pytest.raises(ValueError):
        make_portfolio(pd.DataFrame({"fips": ["1207"], "housing_units": [1]}))
    with pytest.raises(ValueError):
        make_portfolio(pd.DataFrame({"fips": ["12071"]}))
    with pytest.raises(ValueError):
        make_portfolio(county_table(), business_share=1.5)
    with pytest.raises(ValueError):
        make_portfolio(county_table(), n=-1)


def test_claims_deterministic_and_near_the_county_day():
    book = make_portfolio(county_table())
    before = book.copy()
    claims = make_claims(book, RESTORE)
    pd.testing.assert_frame_equal(claims, make_claims(book, RESTORE))
    pd.testing.assert_frame_equal(book, before)
    assert list(claims.columns) == CLAIM_COLUMNS
    assert len(claims) == 200 and claims["claim_id"].is_unique and claims["policy_id"].is_unique
    assert claims["claim_id"].iloc[0] == "C0001"
    assert set(claims["fips"]) == {"12071", "12015", "12021"}  # 13051 has no official restore day
    owners = book.set_index("policy_id")["fips"]
    assert (claims["policy_id"].map(owners) == claims["fips"]).all()

    day = claims["fips"].map(RESTORE)
    inflated = claims["claimed_days_out"] > day
    assert inflated.sum() == 20  # inflated_share 0.1 of 200
    near, near_day = claims.loc[~inflated, "claimed_days_out"], day[~inflated]
    assert ((near >= 0.3 * near_day - 0.1) & (near <= near_day)).all()
    far, far_day = claims.loc[inflated, "claimed_days_out"], day[inflated]
    assert (far >= np.maximum(1.6 * far_day, far_day + 3)).all()
    assert (far <= np.maximum(3 * far_day, far_day + 3) + 0.1).all()


def test_claims_skip_counties_without_a_restore_day():
    book = make_portfolio(county_table())
    none = make_claims(book, {"12071": math.nan, "12015": math.inf, "12021": None, "13051": 0.0})
    assert none.empty and list(none.columns) == CLAIM_COLUMNS
    tiny = make_portfolio(county_table({"12071": 10}), n=5)
    assert len(make_claims(tiny, {"12071": 3.0})) == 5  # capped at the policies available


def test_claims_reject_bad_arguments():
    book = make_portfolio(county_table(), n=1_000)
    with pytest.raises(ValueError):
        make_claims(book, RESTORE, inflated_share=-0.1)
    with pytest.raises(ValueError):
        make_claims(book, RESTORE, n=-3)
    with pytest.raises(ValueError):
        make_claims(book.drop(columns="policy_id"), RESTORE)
