"""County shapes, housing units and customers (Task 4).

Shapes: Census cartographic boundaries (500k), clipped to the shoreline. Housing units: ACS 5-year table B25001
from the keyless summary files on www2.census.gov (api.census.gov now needs a key). Customers: EAGLE-I's MCC.csv, checked against housing units (repair_customers).

Connecticut is the one join that differs: in 2022 the Census replaced its 8 counties with 9 planning regions, but
EAGLE-I and MCC.csv still use the old county codes (09001-09015). So Connecticut comes from the 2021 shapes and the
2021 ACS, which still have the old counties (decision log, 2026-11-08).
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import httpx
import pandas as pd

from blackout.outages import STATE_FIPS, load_mcc

REPO = Path(__file__).resolve().parents[2]
CENSUS = REPO / "data/raw/census"
MCC = REPO / "data/raw/eaglei/MCC.csv"
COVERAGE = REPO / "data/raw/eaglei/coverage_history.csv"
# MCC.csv sums to ~100% of coverage_history's total_customers in every storm state except North Carolina (34%),
# where Wake reads 0.10 customers per housing unit and New Hanover 0.02. See repair_customers.
MCC_STATE_SHARE_MIN = 0.8
RATIO_RANGE = (1 / 3, 3.0)  # customers per housing unit outside this is a broken MCC row (median is 1.1)
OLD_COUNTY_STATES = {"CT"}
SOURCES = {
    "cb_2022_us_county_500k.zip": "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_county_500k.zip",
    "cb_2021_us_county_500k.zip": "https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_county_500k.zip",
    "acsdt5y2022-b25001.dat": "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/"
                              "data/5YRData/acsdt5y2022-b25001.dat",
    "acsdt5y2021-b25001.dat": "https://www2.census.gov/programs-surveys/acs/summary_file/2021/table-based-SF/"
                              "data/5YRData/acsdt5y2021-b25001.dat",
}


def ensure_census_files(folder: Path = CENSUS) -> None:
    """Download any missing Census file (public, keyless)."""
    folder.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        target = folder / name
        if not target.exists():
            with httpx.Client(timeout=300, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                target.write_bytes(response.content)


def housing_units(dat: Path) -> pd.Series:
    """fips -> housing units from an ACS summary-file table (pipe-delimited, county rows are 0500000US<fips>)."""
    table = pd.read_csv(dat, sep="|", dtype={"GEO_ID": str})
    counties = table[table["GEO_ID"].str.startswith("0500000US")]
    return pd.Series(counties["B25001_E001"].astype(int).to_numpy(), index=counties["GEO_ID"].str[-5:].to_numpy())


def _shapes(zip_path: Path, states: set[str]) -> gpd.GeoDataFrame:
    shapes = gpd.read_file(f"zip://{zip_path}")
    shapes = shapes[shapes["STUSPS"].isin(states)]
    return gpd.GeoDataFrame({"fips": shapes["GEOID"].astype(str).to_numpy(), "name": shapes["NAME"].to_numpy(),
                             "state": shapes["STUSPS"].to_numpy()}, geometry=shapes.geometry.to_numpy(),
                            crs=shapes.crs)


def state_totals(coverage_csv: Path = COVERAGE) -> pd.Series:
    """USPS state -> total customers in EAGLE-I's coverage history, latest year in the file."""
    table = pd.read_csv(coverage_csv, dtype={"state": str})
    table = table.assign(yr=pd.to_datetime(table["year"], format="%m/%d/%y").dt.year)
    latest = table.sort_values("yr").groupby("state").tail(1)
    return latest.set_index("state")["total_customers"].astype(float)


def repair_customers(counties: pd.DataFrame, totals: pd.Series) -> pd.DataFrame:
    """A copy with MCC customer counts replaced where they fail a check against Census housing units.

    - A state whose MCC rows add up to under MCC_STATE_SHARE_MIN of EAGLE-I's own state total (North Carolina:
      1.8M of 5.3M) gets housing units scaled to that total for every county.
    - Elsewhere, a county with no MCC row, or customers per housing unit outside RATIO_RANGE, gets housing units
      times the MCC-to-housing ratio of its state's other, plausible counties.
    `customers_source` says which: "mcc" or "housing". Without this, Wilmington, NC reads 44x its customers.
    """
    out = counties.copy()
    mcc = out["customers"].astype("Float64")
    housing = out["housing_units"].astype(float)
    source = pd.Series("mcc", index=out.index, dtype=object)
    repaired = mcc.copy()
    for state, rows in out.groupby("state"):
        idx = rows.index
        mcc_sum = float(mcc[idx].sum(skipna=True))
        housing_sum = float(housing[idx].sum())
        total = float(totals.get(state, float("nan")))
        if total > 0 and mcc_sum < MCC_STATE_SHARE_MIN * total:
            repaired[idx] = (housing[idx] * total / housing_sum).round()
            source[idx] = "housing"
            continue
        ratio = mcc[idx].astype(float) / housing[idx]
        bad = mcc[idx].isna().to_numpy(dtype=bool) | ~ratio.between(*RATIO_RANGE).fillna(False).to_numpy(dtype=bool)
        good_idx, bad_idx = idx[~bad], idx[bad]
        good_housing = float(housing[good_idx].sum())
        state_ratio = float(mcc[good_idx].sum()) / good_housing if good_housing else 1.1
        repaired[bad_idx] = (housing[bad_idx] * state_ratio).round()
        source[bad_idx] = "housing"
    out["customers"] = repaired.astype("Int64")
    out["customers_source"] = source
    return out


def load_counties(states: tuple[str, ...], census: Path = CENSUS, mcc: Path = MCC,
                  coverage: Path = COVERAGE) -> gpd.GeoDataFrame:
    """fips, name, state, geometry, housing_units, customers, customers_source for every county of the USPS
    `states`, in EPSG:4326. Customers come from MCC.csv unless repair_customers replaces a broken count."""
    unknown = sorted(set(states) - set(STATE_FIPS))
    if unknown:
        raise ValueError(f"unknown USPS codes {unknown}")
    new, old = set(states) - OLD_COUNTY_STATES, set(states) & OLD_COUNTY_STATES
    parts, housing = [], []
    if new:
        parts.append(_shapes(census / "cb_2022_us_county_500k.zip", new))
        housing.append(housing_units(census / "acsdt5y2022-b25001.dat"))
    if old:
        parts.append(_shapes(census / "cb_2021_us_county_500k.zip", old))
        housing.append(housing_units(census / "acsdt5y2021-b25001.dat"))
    counties = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs).to_crs("EPSG:4326")
    units = pd.concat(housing)
    units = units[~units.index.duplicated(keep="first")]
    customers = load_mcc(mcc)
    counties["housing_units"] = counties["fips"].map(units)
    counties["customers"] = counties["fips"].map(customers)
    no_housing = counties[counties["housing_units"].isna()]
    if not no_housing.empty:
        raise ValueError(f"housing-unit join lost {len(no_housing)} counties: {sorted(no_housing['fips'])[:10]}")
    counties = counties.astype({"housing_units": int, "customers": "Int64"})
    counties = repair_customers(counties, state_totals(coverage))
    return counties.sort_values("fips").reset_index(drop=True)
