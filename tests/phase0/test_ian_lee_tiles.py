"""Reading VNP46A2 tiles: fill and scale handling, the clear mask, the grid transform and file names."""

import datetime as dt
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest
from phase0_fakes import (
    COUNTY,
    DATA_GROUP,
    GAP_FILLED,
    LAT,
    LON,
    NORTH,
    NTL,
    PIXEL,
    SIZE,
    WEST,
    cloud_mask_bits,
    ian,
    pixel_box,
    tile_name,
    write_tile,
)

DAY = dt.date(2022, 9, 29)


def county_grid_window(path: Path):
    with h5py.File(path, "r") as h5:
        grid = ian.read_grid(h5, path)
    return grid, ian.county_window(COUNTY, grid)


def county_pixels(path: Path) -> "ian.NightPixels":
    """The main path over the synthetic county: 16 pixels, rows 1-4 by columns 1-4, in row-major order."""
    grid, window = county_grid_window(path)
    return ian.read_night(ian.parse_tile_name(path), grid, window)


def test_fill_becomes_nan(tmp_path):
    ntl = np.full((SIZE, SIZE), 7.0)
    ntl[1, 1] = -999.9  # the first county pixel holds the fill value
    night = county_pixels(write_tile(tmp_path, DAY, ntl=ntl))
    assert np.isnan(night.radiance[0])
    assert np.all(night.radiance[1:] == 7.0)
    assert not ian.clear_mask(night)[0]


def test_fill_and_negative_radiance_become_nan(tmp_path):
    path = write_tile(tmp_path, DAY)
    raw = np.array([-999.9, -0.5, 0.0, 3.25], dtype=np.float32)
    assert np.float64(-999.9) != raw[0]  # why the fill is matched in float32, not after upcasting
    with h5py.File(path, "r") as h5:
        decoded = ian.decode_radiance(raw, h5[DATA_GROUP][NTL].attrs, "test")
    assert np.isnan(decoded[:2]).all()
    assert decoded[2:].tolist() == [0.0, 3.25]
    assert decoded.dtype == np.float64


def test_scale_and_offset_come_from_the_attributes(tmp_path):
    path = write_tile(tmp_path, DAY, ntl=4.0)
    with h5py.File(path, "r+") as h5:
        attrs = h5[DATA_GROUP][NTL].attrs
        attrs["scale_factor"], attrs["offset"] = np.float32(0.5), np.float32(1.0)
        attrs["add_offset"] = np.float32(100.0)  # the CF spelling, which VNP46A2 does not use: ignored
    assert np.allclose(county_pixels(path).radiance, 4.0 * 0.5 + 1.0)


def test_missing_offset_attribute_fails_fast(tmp_path):
    path = write_tile(tmp_path, DAY)
    with h5py.File(path, "r+") as h5:
        attrs = h5[DATA_GROUP][NTL].attrs
        del attrs["offset"]
        attrs["add_offset"] = np.float32(0.0)
    with pytest.raises(ian.InputError, match="offset"):
        county_pixels(path)


def test_main_path_never_reads_the_gap_filled_layer(tmp_path):
    fill, bright = np.full((SIZE, SIZE), -999.9), np.full((SIZE, SIZE), 500.0)
    with_gap = write_tile(tmp_path / "with", DAY, ntl=fill, gap_filled=bright)
    assert np.isnan(county_pixels(with_gap).radiance).all()  # bright gap-filled values never leak in
    without_gap = write_tile(tmp_path / "without", DAY, ntl=5.0, skip=(GAP_FILLED,))
    assert np.all(county_pixels(without_gap).radiance == 5.0)  # works with the layer absent: never opened
    grid, window = county_grid_window(with_gap)
    gap, _ = ian.read_gap_filled(ian.parse_tile_name(with_gap), grid, window)
    assert np.all(gap == 500.0)  # only check 1 reads it


def test_cloudy_pixels_are_excluded(tmp_path):
    confidence = np.zeros((SIZE, SIZE), dtype=np.uint16)
    confidence[1, 1:5] = [0, 1, 2, 3]  # confident clear, probably clear, probably cloudy, confident cloudy
    raw = cloud_mask_bits(confidence)
    raw[2, 1] = 65535  # cloud mask fill
    night = county_pixels(write_tile(tmp_path, DAY, cloud_mask=raw))
    assert night.cloud[:5].tolist() == [0, 1, 2, 3, ian.NO_CLOUD_INFO]
    assert ian.clear_mask(night)[:5].tolist() == [True, True, False, False, False]


def test_quality_code_1_is_excluded_from_clear_pixels(tmp_path):
    quality = np.zeros((SIZE, SIZE), dtype=np.uint8)
    quality[1, 1:5] = [0, 1, 2, 3]
    quality[2, 1:4] = [4, 5, 255]
    night = county_pixels(write_tile(tmp_path, DAY, quality=quality))
    assert ian.clear_mask(night)[:7].tolist() == [True] + [False] * 6
    assert ian.clear_mask(night, (0, 1))[:3].tolist() == [True, True, False]  # check 2 keeps code 1


def test_snow_and_snow_fill_are_excluded(tmp_path):
    snow = np.zeros((SIZE, SIZE), dtype=np.uint8)
    snow[1, 1:4] = [0, 1, 255]
    night = county_pixels(write_tile(tmp_path, DAY, snow=snow))
    assert ian.clear_mask(night)[:3].tolist() == [True, False, False]


def test_transform_comes_from_the_file_lat_lon_arrays(tmp_path):
    path = write_tile(tmp_path, DAY)
    with h5py.File(path, "r") as h5:
        assert h5[DATA_GROUP]["lat"][0] == pytest.approx(26.497917, abs=1e-6)  # a pixel centre
        grid = ian.read_grid(h5, path)
    a, b, c, d, e, f = tuple(grid.transform)[:6]
    assert grid.convention == "centres" and grid.shape == (SIZE, SIZE)
    assert (b, d) == (0.0, 0.0)
    assert a == pytest.approx(PIXEL, abs=1e-12) and e == pytest.approx(-PIXEL, abs=1e-12)
    # The origin is where this file's arrays put the grid (-82.0, 26.5), not the tile corner (-90, 30).
    assert c == pytest.approx(WEST, abs=1e-12) and f == pytest.approx(NORTH, abs=1e-12)


def test_full_tile_arrays_as_centres_or_edges_give_the_tile_bounds():
    index = np.arange(2400)
    centres = ian.grid_from_arrays(30 - (index + 0.5) / 240, -90 + (index + 0.5) / 240, (2400, 2400))
    edges = ian.grid_from_arrays(30 - index / 240, -90 + index / 240, (2400, 2400))
    assert (centres.convention, edges.convention) == ("centres", "edges")
    for grid in (centres, edges):
        assert ian.grid_bounds(grid) == pytest.approx((-90.0, 20.0, -80.0, 30.0), abs=1e-9)
        assert ian.is_full_tile(grid)


@pytest.mark.parametrize(
    ("lat", "lon", "message"),
    [
        (NORTH - (np.arange(SIZE) + 0.5) / 120, LON, "spacing"),
        (LAT - PIXEL / 4, LON, "neither a pixel centre nor a pixel edge"),
        (LAT, WEST + np.arange(SIZE) * PIXEL, "lat marks pixel centres but lon marks pixel edges"),
        (LAT, LON - 9.0, "outside tile h09v06"),
    ],
)
def test_grid_rejects_arrays_off_the_tile_grid(lat, lon, message):
    with pytest.raises(ian.InputError, match=message):
        ian.grid_from_arrays(lat, lon, (len(lat), len(lon)))


def float32(values) -> np.ndarray:
    """Values rounded to float32 and back, as a producer working in single precision would store them."""
    return np.asarray(values, dtype=np.float32).astype(np.float64)


INDEX = np.arange(2400)
TILE_LAT, TILE_LON = 30 - (INDEX + 0.5) / 240, -90 + (INDEX + 0.5) / 240  # every pixel centre of h09v06


def test_grid_tolerance_is_about_a_metre():
    assert ian.GRID_TOL_DEG == 1e-5  # 1.1 m north-south, and 1.0 m east-west at 26.5 N


@pytest.mark.parametrize("convention", ["centres", "edges"])
def test_float32_precision_pixel_positions_pass(convention):
    offset = 0.5 if convention == "centres" else 0.0
    lat, lon = float32(30 - (INDEX + offset) / 240), float32(-90 + (INDEX + offset) / 240)
    assert np.max(np.abs(np.abs(np.diff(lon)) - PIXEL)) > 1e-6  # the old 1e-6 tolerance rejected this rounding
    grid = ian.grid_from_arrays(lat, lon, (2400, 2400))
    assert grid.convention == convention and ian.is_full_tile(grid)
    assert ian.grid_bounds(grid) == pytest.approx((-90.0, 20.0, -80.0, 30.0), abs=ian.GRID_TOL_DEG)
    window = ian.grid_from_arrays(float32(LAT), float32(LON), (SIZE, SIZE))
    assert ian.county_window(COUNTY, window).mask.sum() == 16


@pytest.mark.parametrize(
    ("lat", "lon", "message"),
    [
        (30 - (INDEX + 0.5) / 120, TILE_LON, "spacing"),
        (TILE_LAT - PIXEL / 4, TILE_LON, "neither a pixel centre nor a pixel edge"),
        (TILE_LAT, -90 + INDEX / 240, "lat marks pixel centres but lon marks pixel edges"),
        (TILE_LAT, TILE_LON - 10, "outside tile h09v06"),
        (TILE_LAT + 3e-5, TILE_LON, "neither a pixel centre nor a pixel edge"),
        (NORTH - (np.arange(SIZE) + 0.5) / 120, LON, "spacing"),
        (LAT - PIXEL / 4, LON, "neither a pixel centre nor a pixel edge"),
        (LAT, WEST + np.arange(SIZE) * PIXEL, "lat marks pixel centres but lon marks pixel edges"),
        (LAT, LON - 9.0, "outside tile h09v06"),
    ],
    ids=["doubled-spacing", "quarter-pixel-phase", "mixed-centres-and-edges", "off-tile", "3-metre-shift",
         "window-doubled-spacing", "window-quarter-pixel-phase", "window-mixed-centres-and-edges", "window-off-tile"],
)
def test_float32_grids_off_the_tile_grid_still_fail(lat, lon, message):
    """At float32 precision, on the full tile and on the small window alike, the looser tolerance still fails these."""
    with pytest.raises(ian.InputError, match=message):
        ian.grid_from_arrays(float32(lat), float32(lon), (len(lat), len(lon)))


def test_county_pixels_are_those_whose_centres_fall_inside():
    grid = ian.grid_from_arrays(LAT, LON, (SIZE, SIZE))
    window = ian.county_window(COUNTY, grid)
    assert (window.rows, window.cols) == (slice(1, 5), slice(1, 5)) and window.mask.all()
    # Touches pixels 0-3 but holds only the centres of 1 and 2 on each axis. A half-pixel shift in the transform
    # would give 3 x 3 pixels here, and all_touched=True would give 4 x 4.
    narrow = ian.county_window(pixel_box(0.9, 3.1, 0.9, 3.1), grid)
    assert (narrow.rows, narrow.cols, int(narrow.mask.sum())) == (slice(1, 3), slice(1, 3), 4)


def test_night_label_is_the_file_date_minus_one():
    tile = ian.parse_tile_name(Path("VNP46A2.A2022272.h09v06.002.2024147200718.h5"))
    assert tile.file_date == dt.date(2022, 9, 29)
    assert ian.night_of(tile.file_date) == dt.date(2022, 9, 28)
    assert ian.parse_tile_name(Path(tile_name(dt.date(2022, 10, 1)))).file_date == dt.date(2022, 10, 1)


@pytest.mark.parametrize(
    "name",
    [
        "VNP46A2.A2022272.h09v05.002.2024147200718.h5",  # another tile
        "VNP46A2.A2022272.h09v06.001.2024147200718.h5",  # Collection 1
        "VNP46A2.A2022366.h09v06.002.2024147200718.h5",  # day 366 of a 365-day year
        "VNP46A2.A2022272.h09v06.002.h5",  # no production stamp
    ],
)
def test_unexpected_tile_names_fail_fast(name):
    with pytest.raises(ian.InputError):
        ian.parse_tile_name(Path(name))


def test_two_files_for_one_date_fail_fast(tmp_path):
    first = write_tile(tmp_path / "a", DAY)
    (tmp_path / "b").mkdir()
    shutil.copy(first, tmp_path / "b" / tile_name(DAY, stamp="2025001000000"))
    with pytest.raises(ian.InputError, match="more than one file"):
        ian.find_tiles(tmp_path)
