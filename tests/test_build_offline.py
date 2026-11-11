"""Task 5 end to end, offline: build_storm on a made-up storm with tiny fake tiles served in place of NASA."""

import hashlib
import io
import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from make_fake_tile import write_a1, write_a2
from shapely.geometry import box

import blackout.table as table_mod
from blackout import aggregate as agg
from blackout.laads import LaadsFile
from blackout.storms import Storm

SIZE = 8
PX = 1 / 240


def fake_storm() -> Storm:
    landfall = date(2022, 9, 28)
    return Storm(id="fake2022", name="Fake", atcf_id=None, landfall=landfall,
                 baseline_start=landfall - timedelta(days=9), baseline_end=landfall - timedelta(days=3),
                 window_end=landfall + timedelta(days=2), role="stress", states=("FL",))


def fake_counties() -> gpd.GeoDataFrame:
    # Two counties in the top-left 8 x 8 block of h09v06: rows 0-3 and rows 4-7.
    west, north = -90.0, 30.0
    top = box(west, north - 4 * PX, west + SIZE * PX, north)
    bottom = box(west, north - 8 * PX, west + SIZE * PX, north - 4 * PX)
    return gpd.GeoDataFrame({"fips": ["12071", "12015"], "name": ["Lee", "Charlotte"], "state": ["FL", "FL"],
                             "housing_units": [400, 100], "customers": pd.array([600, 120], dtype="Int64")},
                            geometry=[top, bottom], crs="EPSG:4326")


def fake_files(tmp_path: Path, storm: Storm) -> dict[str, dict[date, LaadsFile]]:
    """One VNP46A2 and one VNP46A1 file per night. Lee goes 60% dark from landfall; the night after landfall is
    cloudy over Charlotte."""
    store: dict[str, dict[date, LaadsFile]] = {"VNP46A2": {}, "VNP46A1": {}}
    for night in storm.nights:
        day = night + timedelta(days=1)
        stamp = f"A{day.year}{day.timetuple().tm_yday:03d}"
        radiance = np.full((SIZE, SIZE), 200.0, np.float32)  # 32 px x 200 > DARK_MIN
        if night >= storm.landfall:
            radiance[:4] = 80.0
        cloud = np.full((SIZE, SIZE), 50, np.uint16)
        if night == storm.landfall + timedelta(days=1):
            cloud[4:] = 242
        a2 = write_a2(tmp_path, f"VNP46A2.{stamp}.h09v06.002.2025000000000.h5", radiance, cloud=cloud)
        a1 = write_a1(tmp_path, f"VNP46A1.{stamp}.h09v06.002.2025000000000.h5", np.full((SIZE, SIZE), 7.4675))
        for product, path in (("VNP46A2", a2), ("VNP46A1", a1)):
            data = path.read_bytes()
            store[product][day] = LaadsFile(path.name, f"https://example.org/{path.name}", len(data),
                                            hashlib.md5(data).hexdigest())
    return store


def offline(tmp_path, monkeypatch) -> tuple[Storm, dict[str, dict[date, LaadsFile]], list]:
    """The made-up storm with NASA, EAGLE-I and the counties replaced; the folders the outages were asked from are
    appended to the returned list."""
    storm = fake_storm()
    store = fake_files(tmp_path, storm)
    times = pd.date_range("2022-09-19 00:00", "2022-10-02 00:00", freq="15min", tz="UTC")
    outages = pd.DataFrame([(f, t, 300.0 if (f == "12071" and t >= pd.Timestamp("2022-09-28 18:00", tz="UTC"))
                             else 0.0) for t in times for f in ("12071", "12015")],
                           columns=["fips", "time", "customers_out"])
    interims = []
    monkeypatch.setattr(table_mod, "TILE_SHAPE", (SIZE, SIZE))
    monkeypatch.setattr(table_mod, "PROCESSED", tmp_path / "processed")
    monkeypatch.setattr(table_mod, "IMG", tmp_path / "img")
    monkeypatch.setattr(table_mod, "load_counties", lambda states: fake_counties())
    monkeypatch.setattr(table_mod, "load_storm_outages", lambda s, interim=None: interims.append(interim) or outages)
    monkeypatch.setattr(table_mod, "coverage_for", lambda path, state, year: 0.98)
    monkeypatch.setattr(table_mod, "tiles_for", lambda counties: ["h09v06"])
    monkeypatch.setattr(table_mod, "list_tile_files", lambda client, product, tile, first, last: store[product])
    monkeypatch.setattr(table_mod, "fetch_bytes", lambda client, file: (tmp_path / file.name).read_bytes())
    monkeypatch.setattr(agg, "LABEL_CACHE", tmp_path / "labels")
    monkeypatch.setattr(table_mod, "_local", lambda product, name: None)
    return storm, store, interims


@pytest.fixture
def offline_build(tmp_path, monkeypatch):
    storm, _, _ = offline(tmp_path, monkeypatch)
    return storm, table_mod.build_storm(storm, token="t0ken")


def test_offline_build_table(offline_build):
    storm, table = offline_build
    assert list(table.columns) == table_mod.TABLE_COLUMNS
    assert len(table) == 2 * len(storm.nights)
    lee = table[table["fips"] == "12071"].set_index("night")
    assert lee.loc[storm.landfall - timedelta(days=1), "pct_darker"] == pytest.approx(0.0)
    assert lee.loc[storm.landfall, "pct_darker"] == pytest.approx(0.6)
    assert lee.loc[storm.landfall, "pass_utc"] == pd.Timestamp("2022-09-29 07:28:03", tz="UTC")
    assert lee.loc[storm.landfall, "pass_source"] == "VNP46A1"
    assert lee.loc[storm.landfall, "official_customers_out"] == 300.0
    assert lee.loc[storm.landfall, "official_pct_out"] == pytest.approx(0.5)
    assert (table["wind_band"] == -1).all() and table["covered"].all()
    charlotte = table[table["fips"] == "12015"].set_index("night")
    cloudy = charlotte.loc[storm.landfall + timedelta(days=1)]
    assert cloudy["status"] == "cant_see" and np.isnan(cloudy["pct_darker"])


def test_offline_build_writes_summary_and_quicklooks(offline_build):
    storm, _ = offline_build
    summary = pd.read_json(io.StringIO(table_mod.table_path(storm).with_suffix(".json").read_text()), typ="series")
    assert summary["rows"] == 2 * len(storm.nights) and summary["problems"] == []
    assert table_mod.table_path(storm).exists()
    assert len(summary["quicklooks"]) == 3


def test_missing_night_is_unseen_not_zero(tmp_path, monkeypatch):
    storm = fake_storm()
    counties = fake_counties()
    labels = agg.county_label_grid("h09v06", counties, shape=(SIZE, SIZE), cache=None)
    reading = table_mod.read_night(storm.landfall, None, None, None, labels, 2, False)
    assert reading.clear is None and any("not in the archive" in p for p in reading.problems)


def test_build_hooks_redirect_every_output_and_a_missing_a1_file_is_a_problem(tmp_path, monkeypatch):
    storm, store, interims = offline(tmp_path, monkeypatch)
    del store["VNP46A1"][storm.landfall + timedelta(days=1)]  # NASA lists no pass-time file for the landfall night
    monkeypatch.setattr(table_mod, "load_counties", lambda states: pytest.fail("the counties were given"))
    out = tmp_path / "elsewhere"
    table = table_mod.build_storm(storm, token="t0ken", counties=fake_counties(), processed=out, img=out / "img",
                                  interim=out / "interim")
    assert interims == [out / "interim"]
    assert not (tmp_path / "processed").exists() and not (tmp_path / "img").exists()  # the real folders' stand-ins
    assert (out / "county_nights_fake2022.parquet").exists()
    summary = json.loads((out / "county_nights_fake2022.json").read_text())
    assert summary["problems"] == [f"A1 {storm.landfall}: not in the archive"]
    assert len(summary["quicklooks"]) == 3 and all(Path(p).parent == out / "img" for p in summary["quicklooks"])
    formula = table["pass_source"] == "formula"
    assert formula.sum() == 2 and (table.loc[formula, "night"] == storm.landfall).all()


def test_eaglei_extract_is_cut_into_the_given_interim_folder(tmp_path, monkeypatch):
    source = tmp_path / "eaglei_outages_2022.parquet"
    csv = Path(__file__).parent / "fixtures" / "eaglei_small.csv"
    duckdb.connect().execute(f"""copy (select * from read_csv('{csv}', header=true,
                                 types={{'fips_code': 'VARCHAR', 'customers_out': 'DOUBLE'}}))
                                 to '{source}' (format parquet)""")
    monkeypatch.setattr(table_mod, "INTERIM", tmp_path / "default")
    storm = fake_storm()
    out = table_mod.extract_eaglei(storm, source=source, interim=tmp_path / "scratch")
    assert out == tmp_path / "scratch" / "eaglei_fake2022.parquet" and not (tmp_path / "default").exists()
    assert table_mod.eaglei_extract_path(storm) == tmp_path / "default" / "eaglei_fake2022.parquet"
    rows = duckdb.connect().execute(f"select count(*), min(fips_code), max(fips_code) from read_parquet('{out}')")
    count, first, last = rows.fetchone()
    assert count == 1939 and first[:2] == last[:2] == "12"  # the fixture's two Florida windows inside the storm's dates
    assert len(table_mod.load_storm_outages(storm, tmp_path / "scratch")) == count
