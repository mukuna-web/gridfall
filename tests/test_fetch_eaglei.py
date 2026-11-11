"""scripts/fetch_eaglei.py on a scratch data/raw, with figshare replaced by a mocked transport (offline): the pinned
listing, the small files, and the yearly parquet that is kept only while it can be read and matches its pin."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import duckdb
import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_eaglei", REPO / "scripts/fetch_eaglei.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)
REAL_CLIENT = httpx.Client
YEAR_CSV = "eaglei_outages_2022.csv"
CSV = (b"fips_code,county,state,customers_out,run_start_time\n"
       b"12071,Lee,Florida,5,2022-09-29 07:45:00\n"
       b"12015,Charlotte,Florida,,2022-09-29 07:45:00\n"
       b"01001,Autauga,Alabama,2,2022-09-29 08:00:00\n")
SMALL = {name: f"{name} as figshare serves it\n".encode() for name in fetch.SMALL_FILES}


def listed(name: str, body: bytes) -> dict:
    """One file of figshare's listing."""
    return {"name": name, "size": len(body), "computed_md5": hashlib.md5(body).hexdigest(),
            "download_url": f"https://figshare.test/files/{name}"}


@pytest.fixture
def listing(tmp_path, monkeypatch) -> dict[str, dict]:
    """A scratch repo for the script (data/raw and the pinned inputs) and figshare's listing of one three-row year
    and the small files, pinned as listed."""
    files = {YEAR_CSV: listed(YEAR_CSV, CSV), **{name: listed(name, body) for name, body in SMALL.items()}}
    pins = {name: {"size": meta["size"], "md5": meta["computed_md5"]} for name, meta in files.items()}
    pins[YEAR_CSV]["rows"] = 3
    monkeypatch.setattr(fetch, "REPO", tmp_path)
    monkeypatch.setattr(fetch, "RAW", tmp_path / "data/raw/eaglei")
    monkeypatch.setattr(fetch, "META", tmp_path / "data/raw/docs/figshare.json")
    monkeypatch.setattr(fetch, "PINNED", tmp_path / "docs/reproduce/inputs.json")
    for folder in (fetch.RAW, fetch.META.parent, fetch.PINNED.parent):
        folder.mkdir(parents=True)
    fetch.PINNED.write_text(json.dumps({"eaglei": {"files": pins}}))
    return files


def serve(monkeypatch, bodies: dict[str, bytes]) -> list[str]:
    """Stand in for figshare: every client the script opens answers from `bodies` by the last part of the URL.
    Returns the list the requested names are appended to."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        asked.append(name)
        return httpx.Response(200, content=bodies[name]) if name in bodies else httpx.Response(404)

    monkeypatch.setattr(fetch.httpx, "Client",
                        lambda **kwargs: REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs))
    return asked


def year_parquet() -> Path:
    return fetch.RAW / "eaglei_outages_2022.parquet"


def test_check_pinned_stops_when_a_listed_file_changed_or_is_gone(listing):
    fetch.check_pinned(listing)  # the listing is what was pinned
    with pytest.raises(SystemExit, match="MCC.csv"):
        fetch.check_pinned({**listing, "MCC.csv": listed("MCC.csv", b"a new upload")})
    without_year = {name: meta for name, meta in listing.items() if name != YEAR_CSV}
    with pytest.raises(SystemExit, match=YEAR_CSV):
        fetch.check_pinned(without_year)  # it used to be skipped, and fetch_year then died on a KeyError


def test_small_files_are_fetched_once_checked_and_replaced_when_damaged(listing, monkeypatch):
    asked = serve(monkeypatch, SMALL)
    fetch.fetch_small(listing)
    assert sorted(asked) == sorted(SMALL) and (fetch.RAW / "MCC.csv").read_bytes() == SMALL["MCC.csv"]
    fetch.fetch_small(listing)  # all three are there with the listed MD5: nothing is asked for again
    assert len(asked) == 3
    (fetch.RAW / "DQI.csv").write_bytes(b"cut sho")
    fetch.fetch_small(listing)
    assert asked[3:] == ["DQI.csv"] and (fetch.RAW / "DQI.csv").read_bytes() == SMALL["DQI.csv"]
    (fetch.RAW / "MCC.csv").unlink()
    serve(monkeypatch, {**SMALL, "MCC.csv": b"not what figshare listed"})
    with pytest.raises(SystemExit, match="MCC.csv: MD5 mismatch"):
        fetch.fetch_small(listing)


def test_a_year_is_converted_under_a_part_name_and_kept_while_it_matches_the_pin(listing, monkeypatch, capsys):
    asked = serve(monkeypatch, {YEAR_CSV: CSV})
    out = fetch.fetch_year(2022, listing)
    assert out == year_parquet() and fetch.parquet_rows(out) == 3
    assert [path.name for path in fetch.RAW.iterdir()] == [out.name]  # no CSV and no .part file left
    first = duckdb.connect().execute(f"""select fips_code, typeof(fips_code), typeof(customers_out), customers_out,
                                         typeof(run_start_time) from read_parquet('{out}') order by fips_code""")
    assert first.fetchone() == ("01001", "VARCHAR", "DOUBLE", 2.0, "TIMESTAMP")  # the code keeps its leading zero

    assert fetch.fetch_year(2022, listing) == out and asked == [YEAR_CSV]  # readable, pinned rows: kept as it is
    assert "already have eaglei_outages_2022.parquet (3 rows, as pinned)" in capsys.readouterr().out

    out.write_bytes(b"PAR1 and then the conversion was killed")
    assert fetch.parquet_rows(out) is None
    fetch.fetch_year(2022, listing)
    assert len(asked) == 2 and fetch.parquet_rows(out) == 3 and "cannot be read" in capsys.readouterr().out

    short = out.with_suffix(".short")
    duckdb.connect().execute(f"copy (select * from read_parquet('{out}') limit 2) to '{short}' (format parquet)")
    os.replace(short, out)
    fetch.fetch_year(2022, listing)
    assert len(asked) == 3 and fetch.parquet_rows(out) == 3
    assert "has 2 rows, not the pinned 3" in capsys.readouterr().out


def test_a_conversion_that_misses_the_pinned_row_count_leaves_no_parquet(listing, monkeypatch):
    pins = json.loads(fetch.PINNED.read_text())
    pins["eaglei"]["files"][YEAR_CSV]["rows"] = 4
    fetch.PINNED.write_text(json.dumps(pins))
    serve(monkeypatch, {YEAR_CSV: CSV})
    with pytest.raises(SystemExit, match="3 rows, not the 4 pinned"):
        fetch.fetch_year(2022, listing)
    assert not year_parquet().exists() and not list(fetch.RAW.glob("*.part"))


def test_a_year_without_a_pinned_row_count_is_kept_when_it_can_be_read(listing, monkeypatch):
    asked = serve(monkeypatch, {})
    assert fetch.pinned_rows(2022) == 3 and fetch.pinned_rows(2021) is None
    other = fetch.RAW / "eaglei_outages_2021.parquet"
    duckdb.connect().execute(f"copy (select '12071' as fips_code) to '{other}' (format parquet)")
    assert fetch.fetch_year(2021, listing) == other and asked == []
    fetch.PINNED.unlink()
    assert fetch.pinned_rows(2022) is None


def test_main_fetches_the_listing_once_and_checks_the_pins_before_anything_else(listing, monkeypatch):
    article = json.dumps({"files": [*listing.values()]}).encode()
    asked = serve(monkeypatch, {**SMALL, YEAR_CSV: CSV, str(fetch.ARTICLE_VERSION): article})
    assert fetch.ARTICLE.endswith(f"/articles/24237376/versions/{fetch.ARTICLE_VERSION}")
    assert fetch.main(["2022"]) == 0 and fetch.parquet_rows(year_parquet()) == 3
    assert sorted(asked) == sorted([*SMALL, YEAR_CSV, str(fetch.ARTICLE_VERSION)])
    del asked[:]
    assert fetch.main(["2022"]) == 0 and asked == []  # the listing is cached and every file is in place

    changed = [listed(name, b"changed upstream") if name == "MCC.csv" else meta for name, meta in listing.items()]
    fetch.META.write_text(json.dumps({"files": changed}))
    with pytest.raises(SystemExit, match="upstream EAGLE-I input changed"):
        fetch.main(["2022"])
    assert asked == []
