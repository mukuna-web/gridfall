"""LAADS listing, cloud-first fetching and whole-file downloads, against a mocked httpx transport (offline)."""

import hashlib
from datetime import date

import httpx
import pytest

from blackout import laads


def _listing(names_sizes: list[tuple[str, bytes]]) -> dict:
    return {"n_pages": 1, "content": [
        {"name": n, "downloadsLink": f"https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/{n}",
         "size": len(b), "md5sum": hashlib.md5(b).hexdigest()} for n, b in names_sizes]}


A2 = "VNP46A2.A2022272.h09v06.002.2025134023553.h5"
NEIGHBOUR = "VNP46A2.A2022272.h09v05.002.2025134023553.h5"
BODY = b"hdf5-bytes"


def test_laads_query_params():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=_listing([(A2, BODY), (NEIGHBOUR, BODY)]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        files = laads.list_tile_files(client, "VNP46A2", "h09v06", date(2022, 9, 28), date(2022, 9, 30))
    assert seen[0]["products"] == "VNP46A2"
    assert seen[0]["archiveSet"] == "5200"
    assert seen[0]["temporalRanges"] == "2022-09-28..2022-09-30"
    assert seen[0]["regions"] == "[BBOX]W-89.0 N29.0 E-81.0 S21.0"
    assert seen[0]["page"] == "1"
    assert list(files) == [date(2022, 9, 29)] and files[date(2022, 9, 29)].name == A2


def test_fetch_prefers_cloud_and_checks_md5():
    hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host.startswith("data.laadsdaac"):
            return httpx.Response(200, content=b"corrupted!")
        return httpx.Response(200, content=BODY)

    file = laads.LaadsFile(A2, f"https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/archives/{A2}", len(BODY),
                           hashlib.md5(BODY).hexdigest())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert laads.fetch_bytes(client, file) == BODY
    assert hosts == ["data.laadsdaac.earthdatacloud.nasa.gov", "ladsweb.modaps.eosdis.nasa.gov"]


def test_fetch_raises_when_every_source_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    file = laads.LaadsFile(A2, "https://ladsweb.modaps.eosdis.nasa.gov/x", 3, "abc")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(OSError):
        laads.fetch_bytes(client, file)


def test_download_laads_writes_checked_files(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/details"):
            return httpx.Response(200, json=_listing([(A2, BODY)]))
        return httpx.Response(200, content=BODY)

    real_client = laads.client_for
    monkeypatch.setattr(laads, "client_for", lambda token, timeout=120: httpx.Client(
        transport=httpx.MockTransport(handler), headers=real_client(token).headers))
    paths = laads.download_laads("VNP46A2", "h09v06", [date(2022, 9, 29), date(2022, 9, 30)], "t0ken", tmp_path)
    assert paths == [tmp_path / A2] and paths[0].read_bytes() == BODY
    assert laads.download_laads("VNP46A2", "h09v06", [], "t0ken", tmp_path) == []


def test_missing_token_fails_fast(monkeypatch, tmp_path):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    with pytest.raises(laads.TokenMissingError):
        laads.earthdata_token()


def test_token_is_trimmed_and_a_broken_one_is_refused_without_being_repeated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("EARTHDATA_TOKEN", " \tt0ken.abc-123_x\r\n")  # a secret pasted with its line break
    assert laads.earthdata_token() == "t0ken.abc-123_x"
    for broken in ("t0ken\nabc", "t0ken abc", "t0ken\x7fabc", "t0k\u00e9n"):
        monkeypatch.setenv("EARTHDATA_TOKEN", broken)
        with pytest.raises(laads.TokenMissingError) as refused:
            laads.earthdata_token()
        assert "t0k" not in str(refused.value) and "paste it again" in str(refused.value)
    monkeypatch.setenv("EARTHDATA_TOKEN", " \n")
    with pytest.raises(laads.TokenMissingError, match="is not set"):
        laads.earthdata_token()
    (tmp_path / ".env").write_text('EARTHDATA_TOKEN="t0ken-from-a-file "\n')  # this test's own file, not the repo's
    monkeypatch.delenv("EARTHDATA_TOKEN")
    assert laads.earthdata_token() == "t0ken-from-a-file"


def test_retries_then_gives_up(monkeypatch):
    calls = []
    monkeypatch.setattr(laads.time, "sleep", lambda s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, content=b"ok")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert laads._get(client, "https://example.org/f").content == b"ok"
    assert len(calls) == 3


def test_listing_retries_a_flaky_404_and_reads_every_page(monkeypatch):
    monkeypatch.setattr(laads.time, "sleep", lambda s: None)
    calls = {}
    names = {1: "VNP46A1.A2020208.h07v06.002.2021000000000.h5", 2: "VNP46A1.A2020209.h07v06.002.2021000000000.h5"}

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        calls[page] = calls.get(page, 0) + 1
        if page == 2 and calls[page] == 1:
            return httpx.Response(404)
        return httpx.Response(200, json={"n_pages": 2, "content": [
            {"name": names[page], "downloadsLink": "https://x/" + names[page], "size": 1, "md5sum": "m"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        files = laads.list_tile_files(client, "VNP46A1", "h07v06", date(2020, 7, 26), date(2020, 7, 27))
    assert sorted(files) == [date(2020, 7, 26), date(2020, 7, 27)] and calls[2] == 2
