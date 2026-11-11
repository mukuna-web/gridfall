"""Task 4: storms, wind bands and the county table (docs/plan.md, Week 3)."""

from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from blackout.counties import CENSUS, MCC, housing_units, load_counties
from blackout.storms import get_storm, load_storms, storm_from_record
from blackout.winds import parse_hurdat2, storm_track, wind_band_by_county

REPO = Path(__file__).resolve().parents[1]
REAL_HURDAT = REPO / "data/raw/hurdat2/hurdat2-1851-2025-02272026.txt"
HURDAT = REAL_HURDAT if REAL_HURDAT.exists() else Path(__file__).parent / "fixtures/hurdat2_small.txt"
HAVE_CENSUS = (CENSUS / "cb_2022_us_county_500k.zip").exists() and MCC.exists()
needs_census = pytest.mark.skipif(not HAVE_CENSUS, reason="needs the Census files in data/raw/census")


@pytest.fixture(scope="module")
def hurdat() -> pd.DataFrame:
    return parse_hurdat2(HURDAT)


def test_storm_ids_exist_in_hurdat2(hurdat):
    for storm in load_storms():
        if storm.atcf_id is None:
            assert storm.role == "stress"
            continue
        landfalls = hurdat[(hurdat["atcf_id"] == storm.atcf_id) & (hurdat["record"] == "L")]
        assert not landfalls.empty, storm.id
        gaps = [abs(t.date() - storm.landfall) for t in landfalls["time"]]
        assert min(gaps) <= timedelta(days=1), storm.id


def test_landfall_times_match_hurdat2(hurdat):
    for storm in load_storms():
        if storm.atcf_id is None:
            assert storm.landfall_time == pd.Timestamp("2021-02-15 07:25", tz="UTC")
            continue
        records = hurdat[(hurdat["atcf_id"] == storm.atcf_id) & (hurdat["record"] == "L")]["time"]
        assert (records == storm.landfall_time).any(), storm.id


def test_beryl_uses_noaa20_and_table_names_follow_the_storm():
    from blackout.table import table_path

    beryl, ian = get_storm("beryl2024"), get_storm("ian2022")
    assert beryl.satellite == "VJ146A2" and ian.satellite == "VNP46A2"
    assert table_path(beryl).name == "county_nights_beryl2024.parquet"
    assert table_path(beryl, "VNP46A2").name == "county_nights_beryl2024_vnp46a2.parquet"
    assert table_path(ian, "VJ146A2").name == "county_nights_ian2022_vj146a2.parquet"
    with pytest.raises(ValueError):
        storm_from_record({"id": "x", "name": "X", "landfall": "2020-01-01", "role": "main", "states": ["FL"],
                           "satellite": "MODIS"})


def test_milton_baseline_before_helene():
    assert get_storm("milton2024").baseline_end < get_storm("helene2024").landfall


def test_defaults_and_uri():
    ian = get_storm("ian2022")
    assert ian.baseline_end == ian.landfall - timedelta(days=3)
    assert ian.baseline_start == ian.baseline_end - timedelta(days=30)
    assert ian.window_end == ian.landfall + timedelta(days=21)
    uri = get_storm("uri2021")
    assert (uri.role, uri.states, uri.allow_snow, str(uri.landfall)) == ("stress", ("TX",), True, "2021-02-15")
    with pytest.raises(ValueError):
        storm_from_record({"id": "x", "name": "X", "landfall": "2020-01-01", "role": "main", "states": ["ZZ"]})
    with pytest.raises(KeyError):
        get_storm("nope1999")


def test_parse_hurdat2_columns(hurdat):
    ian = hurdat[hurdat["atcf_id"] == "AL092022"]
    landfall = ian[(ian["record"] == "L") & (ian["time"] == pd.Timestamp("2022-09-28 19:05", tz="UTC"))].iloc[0]
    assert (landfall["lat"], landfall["lon"], landfall["vmax_kt"]) == (26.7, -82.2, 130)
    assert landfall["r64_ne"] > 0
    assert str(ian["time"].dt.tz) == "UTC"


def _track(lat: float, lon: float, r34: dict, r64: dict, hours: int = 2, r50: dict | None = None) -> pd.DataFrame:
    rows = []
    for k in range(hours):
        row = {"atcf_id": "AL992099", "time": pd.Timestamp("2099-09-01 00:00", tz="UTC") + pd.Timedelta(hours=6 * k),
               "record": "", "status": "HU", "lat": lat, "lon": lon, "vmax_kt": 120.0}
        for kt, radii in ((34, r34), (50, r50 or {}), (64, r64)):
            for q in ("ne", "se", "sw", "nw"):
                row[f"r{kt}_{q}"] = float(radii.get(q, 0))
        rows.append(row)
    return pd.DataFrame(rows)


def _county(fips: str, lon: float, lat: float) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"fips": [fips]}, geometry=[box(lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05)],
                            crs="EPSG:4326")


def test_band_inside_64kt():
    track = _track(27.0, -82.0, {q: 150 for q in ("ne", "se", "sw", "nw")}, {q: 40 for q in ("ne", "se", "sw", "nw")})
    counties = pd.concat([_county("12001", -82.2, 27.1), _county("12003", -80.0, 27.0), _county("12005", -70, 27)])
    bands = wind_band_by_county(track, gpd.GeoDataFrame(counties, crs="EPSG:4326"))
    assert bands["12001"] == 64  # ~12 nm away
    assert bands["12003"] == 34  # ~107 nm away
    assert bands["12005"] == 0


def test_quadrants():
    track = _track(27.0, -82.0, {"ne": 200, "se": 20, "sw": 20, "nw": 20}, {})
    counties = gpd.GeoDataFrame(pd.concat([_county("12001", -80.8, 28.0), _county("12003", -83.2, 26.0)]),
                                crs="EPSG:4326")
    bands = wind_band_by_county(track, counties)
    assert bands["12001"] == 34 and bands["12003"] == 0


def test_hourly_interpolation_closes_gaps():
    a = _track(27.0, -84.0, {q: 30 for q in ("ne", "se", "sw", "nw")}, {})
    a.loc[1, ["lat", "lon"]] = [27.0, -80.0]  # 240 km jump in 6 h with only a 30 nm wind field
    county = gpd.GeoDataFrame(_county("12001", -82.0, 27.0), crs="EPSG:4326")
    assert wind_band_by_county(a, county)["12001"] == 34


def test_storm_track_keeps_tropical_fixes(hurdat):
    track = storm_track(hurdat, "AL092024")
    assert set(track["status"]) <= {"TS", "HU"}
    with pytest.raises(ValueError):
        storm_track(hurdat, "AL000000")


@needs_census
def test_states_cover_wind_zone(hurdat):
    every = sorted({s for storm in load_storms() for s in storm.states} | {"AR", "KY", "TN", "OH", "IN", "IL", "WV",
                                                                         "MA", "RI", "NH", "VT", "ME", "OK"})
    counties = load_counties(tuple(every))
    for storm in load_storms():
        if storm.atcf_id is None:
            continue
        bands = wind_band_by_county(storm_track(hurdat, storm.atcf_id), counties)
        hit = set(counties.loc[counties["fips"].map(bands) >= 34, "state"])
        assert hit <= set(storm.states), (storm.id, hit - set(storm.states))


@needs_census
def test_no_county_lost_in_join():
    fl = load_counties(("FL",))
    assert len(fl) == 67
    assert fl["customers"].notna().all() and (fl["housing_units"] > 0).all()
    assert list(fl.columns) == ["fips", "name", "state", "geometry", "housing_units", "customers", "customers_source"]


@needs_census
def test_north_carolina_customers_repaired():
    nc = load_counties(("NC",)).set_index("fips")
    assert (nc["customers_source"] == "housing").all()
    assert nc.loc["37119", "customers"] > 400_000  # Mecklenburg: MCC.csv says 28,172
    assert nc["customers"].notna().all()


@needs_census
def test_connecticut_keeps_old_counties():
    ct = load_counties(("CT",))
    assert list(ct["fips"]) == ["09001", "09003", "09005", "09007", "09009", "09011", "09013", "09015"]
    assert ct["customers"].notna().all()


def test_repair_customers_rules():
    from blackout.counties import repair_customers

    frame = pd.DataFrame({"fips": ["37001", "37003", "12001", "12003", "12005"], "state": ["NC", "NC", "FL", "FL", "FL"],
                          "housing_units": [100, 300, 1000, 1000, 1000],
                          "customers": pd.array([10, 20, 1100, 40, None], dtype="Int64")})
    totals = pd.Series({"NC": 800.0, "FL": 1200.0})
    out = repair_customers(frame, totals).set_index("fips")
    assert out.loc["37001", "customers"] == 200 and out.loc["37003", "customers"] == 600  # scaled to NC's total
    assert out.loc["12001", "customers_source"] == "mcc" and out.loc["12001", "customers"] == 1100
    assert out.loc["12003", "customers_source"] == "housing" and out.loc["12003", "customers"] == 1100  # 0.04 is broken
    assert out.loc["12005", "customers_source"] == "housing" and out.loc["12005", "customers"] == 1100  # no MCC row
    assert frame["customers"].tolist()[3] == 40  # input untouched


def test_housing_units_reads_summary_file(tmp_path):
    dat = tmp_path / "b25001.dat"
    dat.write_text("GEO_ID|B25001_E001|B25001_M001\n0100000US|140943613|3164\n0500000US12071|420000|900\n")
    assert housing_units(dat).to_dict() == {"12071": 420000}


def test_unknown_state_rejected():
    with pytest.raises(ValueError):
        load_counties(("ZZ",))
