"""Task 5: county label grids, per-night sums, % darker and the official count at the pass (docs/plan.md, Week 3)."""

from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import MultiPolygon, box

from blackout import aggregate as agg
from blackout.nightlights import TileNight
from blackout.outages import flag_dropouts, load_outages
from blackout.storms import get_storm
from blackout.table import TABLE_COLUMNS, drop_check, official_columns, tiles_for

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = Path(__file__).resolve().parents[1] / "data/sample/county_nights_ian_sample.parquet"
PX = 1 / 240


def tile(tile_id: str, radiance, cloud=None, quality=None, snow=None) -> TileNight:
    radiance = np.asarray(radiance, dtype=np.float32)
    shape = radiance.shape
    return TileNight(tile_id, date(2022, 9, 30), radiance,
                     np.zeros(shape, np.uint8) if quality is None else np.asarray(quality, np.uint8),
                     np.zeros(shape, np.uint8) if cloud is None else np.asarray(cloud, np.uint8),
                     np.zeros(shape, np.uint8) if snow is None else np.asarray(snow, np.uint8))


def counties(*geoms) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"fips": [f"12{k:03d}" for k in range(1, 2 * len(geoms), 2)]}, geometry=list(geoms),
                            crs="EPSG:4326")


def top_left_block(tile_id: str, rows: int, cols: int):
    west, north = (-90.0, 40.0) if tile_id == "h09v05" else (-90.0, 30.0)
    return box(west, north - rows * PX, west + cols * PX, north)


def test_label_grid_top_left_and_cache(tmp_path):
    c = counties(top_left_block("h09v06", 2, 2))
    labels = agg.county_label_grid("h09v06", c, cache=tmp_path)
    assert labels.shape == (2400, 2400) and labels.dtype == np.int32
    assert labels[:2, :2].tolist() == [[1, 1], [1, 1]] and labels[2:, :].max() == 0 and labels[:, 2:].max() == 0
    assert len(list(tmp_path.glob("*.npz"))) == 1
    assert np.array_equal(agg.county_label_grid("h09v06", c, cache=tmp_path), labels)


def test_straddling_county_sums_both_tiles():
    c = counties(MultiPolygon([top_left_block("h09v05", 2, 2), top_left_block("h09v06", 2, 2)]))
    assert tiles_for(c) == ["h09v05", "h09v06"]
    total = None
    for tile_id, light in (("h09v05", 1000.0), ("h09v06", 3000.0)):
        labels = agg.county_label_grid(tile_id, c, cache=None)[:4, :4]
        base = np.full((4, 4), light, np.float32)
        total = agg.add_sums(total, agg.county_night(tile(tile_id, np.full((4, 4), light / 2)), base, labels, False, 1))
    assert total["base_total"][0] == pytest.approx(4 * 1000 + 4 * 3000)
    assert total["tonight"][0] == pytest.approx(4 * 500 + 4 * 1500)
    row = agg.finalize(total, list(c["fips"])).iloc[0]
    assert row["pct_darker"] == pytest.approx(0.5) and row["status"] == "ok"


def test_all_cloudy_is_cant_see():
    labels = np.ones((4, 4), np.int32)
    sums = agg.county_night(tile("h09v06", np.full((4, 4), 900.0), cloud=np.full((4, 4), 3)),
                            np.full((4, 4), 1000, np.float32), labels, False)
    row = agg.finalize(sums, ["12071"]).iloc[0]
    assert row["status"] == "cant_see" and np.isnan(row["pct_darker"]) and row["visible_share"] == 0


def test_dark_county_not_measurable():
    labels = np.ones((4, 4), np.int32)
    sums = agg.county_night(tile("h09v06", np.full((4, 4), 0.1)), np.full((4, 4), 0.5, np.float32), labels, False)
    row = agg.finalize(sums, ["12071"]).iloc[0]
    assert row["status"] == "not_measurable" and np.isnan(row["pct_darker"])


def test_same_pixels_only():
    labels = np.ones((2, 2), np.int32)
    base = np.array([[1000, 1000], [1000, np.nan]], np.float32)  # pixel (1, 1) has no baseline
    tonight = np.array([[500, 500], [500, 99999]], np.float32)  # ...but is clear and bright tonight
    sums = agg.county_night(tile("h09v06", tonight), base, labels, False)
    assert sums["tonight"][0] == 1500 and sums["base_visible"][0] == 3000 and sums["base_total"][0] == 3000
    assert agg.finalize(sums, ["12071"]).iloc[0]["pct_darker"] == pytest.approx(0.5)


def test_brighter_than_baseline_kept():
    labels = np.ones((2, 2), np.int32)
    sums = agg.county_night(tile("h09v06", np.full((2, 2), 1500)), np.full((2, 2), 1000, np.float32), labels, False)
    assert agg.finalize(sums, ["12071"]).iloc[0]["pct_darker"] == pytest.approx(-0.5)


def test_half_hidden_is_cant_see_and_snow_rule():
    labels = np.ones((2, 2), np.int32)
    cloud = np.array([[3, 3], [0, 0]])
    sums = agg.county_night(tile("h09v06", np.full((2, 2), 800), cloud=cloud),
                            np.array([[1000, 1000], [999, 999]], np.float32), labels, False)
    assert agg.finalize(sums, ["12071"]).iloc[0]["status"] == "cant_see"  # 1998 / 3998 < 0.5
    snowy = tile("h09v06", np.full((2, 2), 800), snow=np.ones((2, 2)))
    assert np.isnan(agg.clear_radiance(snowy, allow_snow=False)).all()
    assert not np.isnan(agg.clear_radiance(snowy, allow_snow=True)).any()


def test_baseline_needs_five_clear_nights():
    nights = [np.full((2, 2), v, np.float32) for v in (10, 20, 30, 40)]
    nights.append(np.array([[50, np.nan], [50, 50]], np.float32))
    base = agg.baseline_from_clear(nights, rows_per_chunk=1)
    assert base[0, 0] == 30 and np.isnan(base[0, 1])
    with pytest.raises(ValueError):
        agg.baseline_from_clear([])
    t = tile("h09v06", np.full((2, 2), 7.0))
    assert np.array_equal(agg.baseline_median([t] * 5, False), np.full((2, 2), 7.0, np.float32))


def test_group_median_and_downsample():
    labels = np.array([[1, 1, 2, 0]])
    med, count = agg.group_median(np.array([[1.0, 3.0, np.nan, 9.0]]), labels, 3)
    assert med[0] == 2.0 and np.isnan(med[1]) and np.isnan(med[2]) and list(count) == [2, 0, 0]
    small = agg.downsample(np.arange(16, dtype=np.float32).reshape(4, 4), factor=2)
    assert small.tolist() == [[2.5, 4.5], [10.5, 12.5]]


def test_official_at_pass_time():
    outages = load_outages(FIXTURES / "eaglei_small.csv", {"12"}, pd.Timestamp("2022-09-30 05:30", tz="UTC"),
                           pd.Timestamp("2022-09-30 09:15", tz="UTC"))
    flags = flag_dropouts(outages)
    got = official_columns(outages, flags, "12071", date(2022, 9, 29), -81.9, 7.4675)
    assert got["pass_utc"] == pd.Timestamp("2022-09-30 07:28:03", tz="UTC")
    assert got["pass_source"] == "VNP46A1"
    assert got["official_customers_out"] == 411615.0
    assert got["official_customers_out_30"] == 411676.0
    assert got["official_customers_out_90"] == 411614.5
    formula = official_columns(outages, flags, "12071", date(2022, 9, 29), -81.9, float("nan"))
    assert formula["pass_source"] == "formula" and formula["pass_utc"] == pd.Timestamp("2022-09-30 06:57:36", tz="UTC")


def test_drop_rule():
    ian = get_storm("ian2022")
    rows = []
    for k, fips in enumerate(["12001", "12003", "12005", "12007"]):
        rows.append({"fips": fips, "night": ian.landfall, "wind_band": 64, "status": "ok" if k < 1 else "cant_see"})
    rows.append({"fips": "12009", "night": ian.landfall, "wind_band": 0, "status": "ok"})
    verdict = drop_check(pd.DataFrame(rows), ian)
    assert verdict == {"hit_counties": 4, "hit_with_ok_night": 1, "share": 0.25, "dropped": True}


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample not built yet")
def test_sample_table_schema():
    sample = pd.read_parquet(SAMPLE)
    assert list(sample.columns) == TABLE_COLUMNS
    assert set(sample["fips"]) == {"12071", "12015", "12021"}
    assert sample["fips"].map(len).eq(5).all()


def test_with_customers_recomputes_pct_out():
    from blackout.table import with_customers

    table = pd.DataFrame({"fips": ["37119", "37119"], "customers": [28172.0, 28172.0],
                          "official_customers_out": [10000.0, np.nan], "official_customers_out_30": [9000.0, 1.0],
                          "official_customers_out_90": [11000.0, 2.0], "official_pct_out": [0.35, np.nan],
                          "official_pct_out_30": [0.3, 0.0], "official_pct_out_90": [0.4, 0.0]})
    counties = pd.DataFrame({"fips": ["37119"], "customers": pd.array([500000], dtype="Int64")})
    out = with_customers(table, counties)
    assert out["official_pct_out"].iloc[0] == pytest.approx(0.02) and np.isnan(out["official_pct_out"].iloc[1])
    assert out["official_pct_out_30"].iloc[0] == pytest.approx(0.018)
    assert table["customers"].iloc[0] == 28172.0  # input untouched


def test_cross_check_keeps_only_counties_inside_the_tiles():
    from blackout.table import cross_check_counties

    inside = box(-89.5, 25.5, -89.0, 26.0)  # h09v06
    straddle = box(-90.5, 25.5, -89.5, 26.0)  # h08v06 and h09v06
    c = counties(inside, straddle)
    kept = cross_check_counties(c, ["h09v06"])
    assert list(kept["fips"]) == ["12001"]
    assert len(cross_check_counties(c, ["h08v06", "h09v06"])) == 2
