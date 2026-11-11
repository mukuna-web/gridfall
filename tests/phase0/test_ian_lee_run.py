"""End to end on a synthetic Ian: the night table, the pass times, the four checks, the chart, the CLI, the JSON
summary file and the input rules."""

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest
from phase0_fakes import (
    A1_FILES,
    COUNTY,
    DATA_GROUP,
    DIM_BASELINE_FILE,
    FILE_DATES,
    LAYERS,
    REPO,
    build_ian_root,
    ian,
    write_a1_tile,
    write_county_gpkg,
    write_county_zip,
)


@pytest.fixture(scope="module")
def ian_run(tmp_path_factory):
    root = build_ian_root(tmp_path_factory.mktemp("ian"))
    summary = ian.run(root)
    table = pd.read_csv(root / ian.OUT_CSV, parse_dates=["eaglei_target"])
    return root, summary, table.set_index("file_date")


def test_night_table_has_one_row_per_file_date(ian_run):
    _, _, table = ian_run
    assert table.index.tolist() == [day.isoformat() for day in FILE_DATES]
    nights = pd.to_datetime(table["night"]) + pd.Timedelta(1, unit="D")
    assert (nights.dt.date.astype(str) == table.index).all()  # night = file date - 1
    assert set(table["n_county_pixels"]) == {16}  # the outer ring of 1000s never enters a sum
    cant_see = table.index[table["status"] == "cant_see"].tolist()
    assert cant_see == ["2022-08-28", "2022-09-04", "2022-09-08", "2022-09-12", "2022-09-16", "2022-09-20",
                        "2022-09-24", "2022-09-30"]
    assert set(table.loc[~table.index.isin(cant_see), "status"]) == {"ok"}


def test_night_values(ian_run):
    _, _, table = ian_run
    expected = {"2022-09-28": 0.0, "2022-09-29": 0.75, "2022-10-01": 0.6, "2022-10-02": 0.4, "2022-10-03": 0.1}
    assert table.loc[list(expected), "pct_darker"].to_numpy() == pytest.approx(list(expected.values()))
    dim = table.loc[DIM_BASELINE_FILE.isoformat()]  # a seen baseline night past the dark cutoff, weeks before Ian
    assert (dim["status"], dim["in_baseline"]) == ("ok", True) and dim["pct_darker"] == pytest.approx(0.4)
    assert np.isnan(table.loc["2022-09-30", "pct_darker"])  # can't see is never zero
    sep_29 = table.loc["2022-09-29"]
    assert (sep_29["tonight"], sep_29["base_visible"], sep_29["base_total"]) == (40.0, 160.0, 160.0)
    # Was 05:30 (01:30 New York). The pass is now the fake VNP46A1 UTC_Time over the county: 07:00 UTC on Sep 29.
    assert sep_29["eaglei_target"] == pd.Timestamp("2022-09-29 07:00")
    assert (sep_29["eaglei_n_runs"], sep_29["eaglei_customers_out"], sep_29["eaglei_pct_out"]) == (8, 700.0, 0.7)
    assert table.loc["2022-10-01", "visible_share"] == pytest.approx(0.5)
    assert np.isnan(table.loc["2022-09-01", "eaglei_pct_out"])  # no EAGLE-I runs that early in the fake
    assert table.loc["2022-09-01", "eaglei_n_runs"] == 0


def test_baseline_and_grid_in_the_summary(ian_run):
    _, summary, _ = ian_run
    baseline, grid = summary["baseline"], summary["grid"]
    assert (baseline["n_files"], baseline["n_pixels_with_baseline"], baseline["base_total"]) == (31, 16, 160.0)
    assert baseline["clear_nights_per_pixel_min_median_max"] == [24, 24.0, 24]
    assert grid["lat_lon_mark"] == "centres" and grid["data_group"] == "/" + DATA_GROUP
    assert grid["ntl_attributes"]["valid_range"] == ">=0.0 \n"
    assert summary["county"] == {"fips": "12071", "polygon_source": ian.COUNTIES_GPKG, "n_pixels": 16,
                                 "mcc_customers": 1000}


def test_check_1_gap_filled_layer_hides_the_blackout(ian_run):
    _, summary, _ = ian_run
    rows = {row["file_date"]: row for row in summary["checks"]["1_gap_filled_vs_corrected"]}
    assert list(rows) == [dt.date(2022, 9, 29), dt.date(2022, 9, 30), dt.date(2022, 10, 1)]
    cloudy = rows[dt.date(2022, 9, 30)]
    assert cloudy["status"] == "cant_see" and np.isnan(cloudy["pct_darker"])
    assert cloudy["pct_darker_gap_filled"] == pytest.approx(0.0)  # pre-storm light pasted into the clouds
    assert cloudy["visible_share_gap_filled"] == pytest.approx(1.0)
    assert (cloudy["n_pixels_gap_filled_only"], cloudy["latest_hq_retrieval_days_median"]) == (16, 2.0)
    assert rows[dt.date(2022, 9, 29)]["pct_darker_gap_filled"] == pytest.approx(0.75)


def test_check_2_quality_code_1(ian_run):
    _, summary, _ = ian_run
    rows = {row["file_date"]: row for row in summary["checks"]["2_quality_code_1"]}
    assert list(rows) == list(FILE_DATES[34:])  # every file after the Sep 28 landfall
    oct_1 = rows[dt.date(2022, 10, 1)]
    assert oct_1["mqf_counts"] == {0: 8, 1: 8} and oct_1["mqf1_share"] == 0.5
    assert oct_1["pct_darker"] == pytest.approx(0.6)
    assert oct_1["pct_darker_keep_mqf1"] == pytest.approx(0.775)
    assert oct_1["pct_darker_mqf1_only"] == pytest.approx(0.95)


def test_check_3_surge_and_check_4_first_dark_file(ian_run):
    _, summary, _ = ian_run
    surge = summary["checks"]["3_eaglei_surge_timing"]
    assert surge["first_10%_out"]["hours_after_landfall_if_utc"] == pytest.approx(-23 / 6)
    assert surge["first_10%_out"]["hours_after_landfall_if_new_york"] == pytest.approx(1 / 6)
    dark = summary["checks"]["4_first_dark_file"]
    # The dim Sep 3 baseline night is dark too, but only files after the baseline are searched.
    assert (dark["file_date"], dark["night"]) == (dt.date(2022, 9, 29), dt.date(2022, 9, 28))
    assert dark["file_date"] == dark["expected_file_date"] and dark["days_after_nasa_date"] == -1
    assert dark["eaglei_pct_out"] == pytest.approx(0.7) and dark["verdict"] == "confirmed"
    controls = {row["file_date"]: row for row in dark["controls"]}
    assert list(controls) == [dt.date(2022, 9, 28), dt.date(2022, 9, 29)]
    lit, out = controls[dt.date(2022, 9, 28)], controls[dt.date(2022, 9, 29)]
    assert (lit["status"], lit["dark"], lit["pct_darker"], lit["eaglei_pct_out"]) == ("ok", False, 0.0, 0.005)
    assert (out["status"], out["dark"], out["eaglei_pct_out"]) == ("ok", True, 0.7)
    assert out["pct_darker"] == pytest.approx(0.75)


def test_chart_is_written(ian_run):
    root, _, _ = ian_run
    assert (root / ian.OUT_PNG).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_each_night_records_its_pass(ian_run):
    _, _, table = ian_run
    passes = pd.to_datetime(table["pass_utc"], utc=True)
    nominal = pd.Timestamp("2022-09-30 06:57:57", tz="UTC")  # 01:30 + 81.9875/15 h at the fake county's longitude
    expected = {
        "2022-09-28": ("2022-09-28 06:30", "VNP46A1", 10.0),
        "2022-09-29": ("2022-09-29 07:00", "VNP46A1", 25.5),  # one fill pixel and one other-orbit pixel left out
        "2022-09-30": (str(nominal.tz_localize(None)), "nominal_solar_time", None),  # no VNP46A1 file
        "2022-10-01": ("2022-10-01 06:57:57", "nominal_solar_time", 40.0),  # VNP46A1 there, but UTC_Time is fill
    }
    for day, (when, source, zenith) in expected.items():
        assert passes[day] == pd.Timestamp(when, tz="UTC") and table.loc[day, "pass_source"] == source
        if zenith is None:
            assert np.isnan(table.loc[day, "sensor_zenith_median"])
        else:
            assert table.loc[day, "sensor_zenith_median"] == pytest.approx(zenith, abs=1e-4)
    others = table.index[~table.index.isin(list(expected))]
    assert set(table.loc[others, "pass_source"]) == {"nominal_solar_time"}
    assert table.loc[others, "sensor_zenith_median"].isna().all()
    assert ((passes - passes.dt.normalize()) == nominal - nominal.normalize()).loc[others].all()
    # EAGLE-I is read around each night's own pass, on the EAGLE-I clock (UTC here).
    assert (pd.to_datetime(table["eaglei_target"]) == passes.dt.tz_localize(None)).all()


def test_the_summary_says_how_each_pass_was_found(ian_run):
    root, summary, _ = ian_run
    found = summary["pass"]
    assert found["source_counts"] == {"nominal_solar_time": len(FILE_DATES) - 2, "VNP46A1": 2}
    assert found["n_vnp46a1_files"] == len(A1_FILES) == 3
    assert found["vnp46a1_without_valid_utc_time"] == [dt.date(2022, 10, 1)]
    assert found["representative_point_lon"] == pytest.approx(-81.9875)
    assert found["hours_utc_min_median_max"] == pytest.approx([6.5, 6.9658333, 7.0], abs=1e-6)
    assert "01:30 local mean solar time" in found["rule"] and "EDT" not in json.dumps(ian.jsonable(found))
    assert summary["eaglei"]["centred_on"].startswith("each night's pass_utc")
    assert summary["outputs"]["json"] == ian.OUT_JSON
    assert json.loads((root / ian.OUT_JSON).read_text(encoding="utf-8")) == ian.jsonable(summary)


def test_a_vnp46a1_pass_outside_0400_to_1000_utc_fails_fast(tmp_path, capsys):
    root = build_ian_root(tmp_path)
    day = dt.date(2022, 9, 29)
    stale = next((root / ian.A1_DIR).rglob(f"VNP46A1.A2022{day.timetuple().tm_yday:03d}.*.h5"))
    stale.unlink()
    write_a1_tile(stale.parent, day, utc_time=11.5)  # an afternoon time: the night label would be wrong
    assert ian.main(["--root", str(root)]) == 1
    message = capsys.readouterr().err
    assert "VNP46A1 pass for the 2022-09-29 file is at 2022-09-29 11:30 UTC" in message
    assert "outside 04:00-10:00 UTC" in message
    assert not any((root / out).exists() for out in (ian.OUT_CSV, ian.OUT_PNG, ian.OUT_JSON))  # nothing half-written


def test_main_prints_a_json_summary(tmp_path, capsys):
    root = build_ian_root(tmp_path, county="zip")  # also covers the documented gpkg-to-zip fallback
    assert ian.main(["--root", str(root), "--eaglei-tz", "America/New_York"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["eaglei"]["clock"] == "America/New_York"
    assert summary["county"]["polygon_source"] == str(ian.COUNTIES_ZIP)
    check_4 = summary["checks"]["4_first_dark_file"]
    assert (check_4["file_date"], check_4["verdict"]) == ("2022-09-29", "confirmed")
    assert [row["file_date"] for row in check_4["controls"]] == ["2022-09-28", "2022-09-29"]
    table = pd.read_csv(root / ian.OUT_CSV).set_index("file_date")
    # Was 01:30 (the old 01:30 New York pass). The Sep 29 pass is 07:00 UTC, read on the New York clock: 03:00 EDT.
    assert table.loc["2022-09-29", "eaglei_target"] == "2022-09-29 03:00:00"
    assert json.loads((root / ian.OUT_JSON).read_text(encoding="utf-8")) == summary  # the file matches stdout


def test_missing_inputs_fail_fast_and_name_each_file(tmp_path, capsys):
    assert ian.main(["--root", str(tmp_path)]) == 1
    message = capsys.readouterr().err
    for needed in ("VNP46A2 tiles", "county polygon", "EAGLE-I Florida extract", "MCC.csv"):
        assert needed in message
    assert not any((tmp_path / out).exists() for out in (ian.OUT_CSV, ian.OUT_PNG, ian.OUT_JSON))


def test_unknown_eaglei_clock_fails_fast(tmp_path, capsys):
    assert ian.main(["--root", str(tmp_path), "--eaglei-tz", "Mars/Olympus"]) == 1
    assert "IANA time zone" in capsys.readouterr().err


def test_county_gpkg_wins_and_the_zip_is_only_a_fallback(tmp_path):
    paths = ian.Paths.under(tmp_path)
    write_county_zip(paths.counties_zip)
    geometry, source = ian.load_county(paths)
    assert source == ian.COUNTIES_ZIP and geometry.bounds == pytest.approx(COUNTY.bounds)
    write_county_gpkg(paths.counties_gpkg)
    assert ian.load_county(paths)[1] == ian.COUNTIES_GPKG
    paths.counties_zip.unlink()
    paths.counties_gpkg.unlink()
    with pytest.raises(ian.InputError, match="missing both"):
        ian.load_county(paths)


def test_constants_match_the_reconciled_facts():
    facts = json.loads((REPO / "docs" / "phase0" / "blackmarble-facts.json").read_text(encoding="utf-8"))
    layers = {entry["name"]: entry for entry in facts["layers"]}
    assert facts["hdf5_data_group"] == "/" + ian.DATA_GROUP == "/" + DATA_GROUP
    for name, (dtype, fill, scale, offset, _) in LAYERS.items():
        entry = layers[name]
        assert (entry["dtype"], entry["fill_value"], entry["scale_factor"], entry["offset"]) == (dtype, fill, scale, offset)
    assert {ian.NTL, ian.GAP_FILLED_NTL, ian.QUALITY, ian.CLOUD_MASK, ian.SNOW, ian.LATEST_HQ} <= set(layers)
    assert (ian.NTL_FILL, ian.CLOUD_MASK_FILL) == (layers[ian.NTL]["fill_value"], layers[ian.CLOUD_MASK]["fill_value"])
    assert ian.PIXEL_DEG == facts["tile_grid"]["pixel_deg"]
    meanings = {row["value"]: row["meaning"] for row in facts["mandatory_quality_flag"]}
    assert meanings[0].startswith("High-quality") and "Outlier" in meanings[ian.POOR_OUTLIER_OR_CLOUD]
    cloud_bits = {row["bits"]: row["values"] for row in facts["cloud_mask_bits"]}
    assert "00 = Confident Clear; 01 = Probably Clear" in cloud_bits["6-7"]
