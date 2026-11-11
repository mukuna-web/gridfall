"""The satellite pass time: VNP46A1 UTC_Time over the county, the 01:30 mean-solar-time fallback, the 04:00-10:00 UTC
guard and the EAGLE-I window centred on the pass."""

import datetime as dt
import math
import shutil

import h5py
import numpy as np
import pandas as pd
import pytest
from phase0_fakes import (
    COUNTY,
    INNER,
    LAT,
    LON,
    PIXEL,
    SIZE,
    a1_name,
    ian,
    write_a1_tile,
    write_eaglei,
)

SEP_29 = dt.date(2022, 9, 29)
LEE_LON = -81.9  # about Lee County's longitude, as in the plan's test_pass_time_utc


def county_grid_window():
    grid = ian.grid_from_arrays(LAT, LON, (SIZE, SIZE))
    return grid, ian.county_window(COUNTY, grid)


def a1_pass(path, day=SEP_29, lon=LEE_LON) -> dict:
    grid, window = county_grid_window()
    return ian.night_pass(day, ian.parse_tile_name(path, "VNP46A1"), grid, window, lon)


def test_the_pass_is_the_median_vnp46a1_utc_time_over_the_county(tmp_path):
    utc = np.full((SIZE, SIZE), 9.5)  # outside the county: never used
    utc[INNER] = 7.25
    utc[1, 1], utc[2, 2] = -999.9, 8.9  # a fill pixel, and one pixel from a later orbit that the median outvotes
    zenith = np.full((SIZE, SIZE), 7000)
    zenith[INNER] = 2550  # stored in hundredths of a degree
    zenith[3, 3] = -32768
    overpass = a1_pass(write_a1_tile(tmp_path, SEP_29, utc_time=utc, sensor_zenith=zenith))
    assert overpass["pass_utc"] == pd.Timestamp("2022-09-29 07:15", tz="UTC")  # 7.25 decimal hours on the file date
    assert overpass["pass_source"] == "VNP46A1"
    assert overpass["sensor_zenith_median"] == pytest.approx(25.5, abs=1e-5)


def test_utc_time_is_decoded_with_its_own_scale_and_offset(tmp_path):
    path = write_a1_tile(tmp_path, SEP_29, utc_time=3.0)
    with h5py.File(path, "r+") as h5:
        attrs = h5[ian.DATA_GROUP]["UTC_Time"].attrs
        attrs["scale_factor"], attrs["add_offset"] = np.float32(2.0), np.float32(0.5)
        attrs["offset"] = np.float32(100.0)  # the VNP46A2 spelling, which VNP46A1 does not use: ignored
    assert a1_pass(path)["pass_utc"] == pd.Timestamp("2022-09-29 06:30", tz="UTC")  # 3.0 * 2 + 0.5 = 6.5 h


def test_without_vnp46a1_the_pass_is_0130_local_mean_solar_time():
    grid, window = county_grid_window()
    overpass = ian.night_pass(SEP_29, None, grid, window, LEE_LON)
    assert overpass["pass_utc"] == pd.Timestamp("2022-09-29 06:57:36", tz="UTC")  # about 06:58, as the plan says
    assert overpass["pass_source"] == "nominal_solar_time" and math.isnan(overpass["sensor_zenith_median"])


@pytest.mark.parametrize("bad_time", [-999.9, 25.0, -1.0])  # fill, and both sides of the valid range 0-24
def test_no_valid_utc_time_over_the_county_falls_back_to_the_nominal_pass(tmp_path, bad_time):
    utc = np.full((SIZE, SIZE), 7.0)
    utc[INNER] = bad_time  # valid times only outside the county
    overpass = a1_pass(write_a1_tile(tmp_path, SEP_29, utc_time=utc, sensor_zenith=3000))
    assert overpass["pass_utc"] == ian.nominal_pass_utc(SEP_29, LEE_LON)
    assert overpass["pass_source"] == "nominal_solar_time"
    assert overpass["sensor_zenith_median"] == pytest.approx(30.0, abs=1e-5)  # still read from the file


@pytest.mark.parametrize(("hours", "ok"), [(4.0, True), (10.0, True), (3.95, False), (10.05, False), (19.0, False)])
def test_a_pass_outside_0400_to_1000_utc_on_the_file_date_fails_fast(tmp_path, hours, ok):
    path = write_a1_tile(tmp_path, SEP_29, utc_time=hours)
    if ok:
        assert a1_pass(path)["pass_utc"] == pd.Timestamp(SEP_29, tz="UTC") + pd.Timedelta(hours, unit="h")
    else:
        with pytest.raises(ian.InputError, match="outside 04:00-10:00 UTC on the file date"):
            a1_pass(path)


def test_a_nominal_pass_outside_the_window_fails_fast_too():
    grid, window = county_grid_window()
    with pytest.raises(ian.InputError, match="nominal_solar_time pass for the 2022-09-29 file is at 2022-09-29 00:50"):
        ian.night_pass(SEP_29, None, grid, window, lon=10.0)  # 01:30 - 10/15 h: a longitude far from Florida


def test_vnp46a1_must_be_on_the_vnp46a2_grid_and_name_its_offset_add_offset(tmp_path):
    shifted = write_a1_tile(tmp_path / "shifted", SEP_29, lat=LAT - PIXEL)  # one row south
    with pytest.raises(ian.InputError, match="another grid"):
        a1_pass(shifted)
    renamed = write_a1_tile(tmp_path / "renamed", SEP_29, offset_name="offset")
    with pytest.raises(ian.InputError, match="has no add_offset attribute"):
        a1_pass(renamed)
    no_time = write_a1_tile(tmp_path / "no_time", SEP_29, skip=("UTC_Time",))
    with pytest.raises(ian.InputError, match="has no layer UTC_Time"):
        a1_pass(no_time)


def test_vnp46a1_files_are_optional_but_one_per_date(tmp_path):
    assert ian.find_tiles(tmp_path / "absent", "VNP46A1", required=False) == []
    first = write_a1_tile(tmp_path / "a", SEP_29)
    assert [tile.file_date for tile in ian.find_tiles(tmp_path, "VNP46A1", required=False)] == [SEP_29]
    (tmp_path / "b").mkdir()
    shutil.copy(first, tmp_path / "b" / a1_name(SEP_29, stamp="2025001000000"))
    with pytest.raises(ian.InputError, match="more than one file"):
        ian.find_tiles(tmp_path, "VNP46A1", required=False)
    with pytest.raises(ian.InputError, match="is not named VNP46A1"):
        ian.parse_tile_name(first.with_name(first.name.replace("VNP46A1", "VNP46A2")), "VNP46A1")


def night_pixels(day=SEP_29) -> "ian.NightPixels":
    """Four clear county pixels at 2.0 nW/cm2/sr."""
    flags = np.zeros(4, np.uint8)
    return ian.NightPixels(day, np.full(4, 2.0), flags, flags, flags)


def test_the_eaglei_window_is_centred_on_the_pass(tmp_path):
    passed = pd.Timestamp("2022-09-29 07:15", tz="UTC")
    stamps = pd.date_range("2022-09-29 02:00", "2022-09-29 10:00", freq="15min")
    near = abs(stamps - passed.tz_localize(None)) <= ian.EAGLEI_WINDOW  # 06:15 to 08:15: 700 out, else 100
    rows = [("12071", 700 if is_near else 100, stamp) for stamp, is_near in zip(stamps, near)]
    runs = ian.load_lee_runs(write_eaglei(tmp_path / "eaglei.parquet", rows))
    overpass = {"pass_utc": passed, "pass_source": "VNP46A1", "sensor_zenith_median": 25.5}
    row = ian.night_row(night_pixels(), np.full(4, 10.0), runs, 1000, "UTC", overpass)
    assert row["eaglei_target"] == pd.Timestamp("2022-09-29 07:15")
    assert (row["eaglei_n_runs"], row["eaglei_customers_out"], row["eaglei_pct_out"]) == (9, 700.0, 0.7)
    assert (row["pass_utc"], row["pass_source"], row["sensor_zenith_median"]) == (passed, "VNP46A1", 25.5)
    # Read on the New York clock, the same pass is 03:15 EDT; the window moves with it, onto the 100s.
    local = ian.night_row(night_pixels(), np.full(4, 10.0), runs, 1000, "America/New_York", overpass)
    assert local["eaglei_target"] == pd.Timestamp("2022-09-29 03:15")
    assert (local["eaglei_n_runs"], local["eaglei_customers_out"]) == (9, 100.0)
