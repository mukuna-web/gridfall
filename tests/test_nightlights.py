"""Task 3: Black Marble tile reader, clear mask, nights and pass times (docs/plan.md, Week 2)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from make_fake_tile import write_a1, write_a2

from blackout.nightlights import (
    clear_mask,
    find_a1,
    night_of,
    parse_name,
    pass_time_utc,
    read_pass,
    read_tile,
    read_utc_time,
    tile_ids_for_bbox,
    tile_origin,
)

A2_NAME = "VNP46A2.A2022272.h09v06.002.2025134023553.h5"
A1_NAME = "VNP46A1.A2022272.h09v06.002.2024276031337.h5"


def test_tile_ids_lee_county():
    assert tile_ids_for_bbox(-82.3, 26.3, -81.6, 26.8) == ["h09v06"]


def test_tile_ids_straddle():
    assert tile_ids_for_bbox(-85, 29.5, -84, 30.5) == ["h09v05", "h09v06"]


def test_tile_ids_edge():
    assert tile_ids_for_bbox(-90, 20, -80, 30) == ["h09v06"]
    with pytest.raises(ValueError):
        tile_ids_for_bbox(-80, 20, -90, 30)
    with pytest.raises(ValueError):
        tile_ids_for_bbox(-90, 30, -80, 20)


def test_tile_origin_is_top_left():
    assert tile_origin("h09v06") == (-90.0, 30.0)


def test_name_gives_tile_and_date(tmp_path):
    t = read_tile(write_a2(tmp_path, A2_NAME, np.ones((3, 4))))
    assert t.tile_id == "h09v06"
    assert t.file_date == date(2022, 9, 29)
    assert t.radiance.shape == (3, 4)
    assert parse_name("VJ146A2.A2024284.h09v06.002.2025001000000.h5") == ("VJ146A2", date(2024, 10, 10), "h09v06")
    with pytest.raises(ValueError):
        parse_name("VNP46A3.A2022272.h09v06.002.2025134023553.h5")
    with pytest.raises(ValueError):
        read_tile(write_a1(tmp_path, A1_NAME, np.ones((3, 4))))


def test_fill_becomes_nan(tmp_path):
    radiance = np.array([[5.0, -999.9], [7.0, 8.0]], dtype=np.float32)
    t = read_tile(write_a2(tmp_path, A2_NAME, radiance))
    assert np.isnan(t.radiance[0, 1]) and t.radiance[0, 0] == 5.0
    utc = np.array([[7.5, -999.9], [7.25, 7.0]], dtype=np.float32)
    got = read_utc_time(write_a1(tmp_path, A1_NAME, utc))
    assert np.isnan(got[0, 1]) and got[0, 0] == np.float32(7.5)


def test_scaled_layers(tmp_path):
    zenith = np.array([[1234, -32768]], dtype=np.int16)
    p = read_pass(write_a1(tmp_path, A1_NAME, np.array([[7.0, 7.1]]), zenith))
    assert p.sensor_zenith[0, 0] == pytest.approx(12.34, abs=1e-4) and np.isnan(p.sensor_zenith[0, 1])
    t = read_tile(write_a2(tmp_path, A2_NAME, np.ones((1, 2)), lunar=np.array([[123, 65535]], dtype=np.uint16)))
    assert t.lunar_irradiance[0, 0] == pytest.approx(12.3, abs=1e-4) and np.isnan(t.lunar_irradiance[0, 1])


def test_never_reads_gap_filled(tmp_path):
    radiance = np.array([[-999.9, 3.0]], dtype=np.float32)
    gap_filled = np.array([[40.0, 3.0]], dtype=np.float32)
    t = read_tile(write_a2(tmp_path, A2_NAME, radiance, gap_filled=gap_filled))
    assert np.isnan(t.radiance[0, 0])


def test_cloudy_masked(tmp_path):
    radiance = np.full((1, 3), 10.0, dtype=np.float32)
    cloud = np.array([[242, 50, 50]], dtype=np.uint16)
    snow = np.array([[0, 0, 255]], dtype=np.uint8)
    t = read_tile(write_a2(tmp_path, A2_NAME, radiance, cloud=cloud, snow=snow))
    assert list(clear_mask(t)[0]) == [False, True, False]
    assert list(clear_mask(t, allow_snow=True)[0]) == [False, True, False]


def test_quality_and_snow_rules(tmp_path):
    radiance = np.array([[1.0, 1.0, 1.0, 1.0, -999.9]], dtype=np.float32)
    quality = np.array([[0, 1, 2, 0, 0]], dtype=np.uint8)
    cloud = np.array([[0b01000000, 0, 0, 0, 0]], dtype=np.uint16)  # probably clear counts as clear
    snow = np.array([[0, 0, 0, 1, 0]], dtype=np.uint8)
    t = read_tile(write_a2(tmp_path, A2_NAME, radiance, quality=quality, cloud=cloud, snow=snow))
    assert list(clear_mask(t)[0]) == [True, False, False, False, False]
    assert list(clear_mask(t, allow_snow=True)[0]) == [True, False, False, True, False]


def test_night_of():
    assert night_of(date(2022, 9, 29)) == date(2022, 9, 28)


def test_pass_time_utc():
    assert pass_time_utc(date(2022, 9, 29), -81.9) == pd.Timestamp("2022-09-29 06:57:36", tz="UTC")
    assert pass_time_utc(date(2022, 9, 29), -81.9, utc_hours=7.78) == pd.Timestamp("2022-09-29 07:46:48", tz="UTC")
    assert pass_time_utc(date(2022, 9, 29), -81.9, utc_hours=float("nan")) == pd.Timestamp(
        "2022-09-29 06:57:36", tz="UTC")


def test_find_a1_by_date_and_tile(tmp_path):
    write_a1(tmp_path, A1_NAME, np.ones((1, 1)))
    write_a1(tmp_path, "VNP46A1.A2022273.h09v06.002.2024276031337.h5", np.ones((1, 1)))
    assert find_a1(tmp_path / A2_NAME, tmp_path) == tmp_path / A1_NAME
    assert find_a1(tmp_path / "VJ146A2.A2022272.h09v06.002.2025134023553.h5", tmp_path) is None
