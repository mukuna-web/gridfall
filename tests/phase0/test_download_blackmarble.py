"""scripts/phase0/download_blackmarble.py without the network: --products, the token check, the archive-gap message and
the MD5 check. The script is loaded from its path; the LAADS listing and blackmarblepy are replaced by fakes, and the
real .env is never read."""

import datetime as dt
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase0" / "download_blackmarble.py"
TOKEN = "placeholder-not-a-token"  # what the fakes receive; nothing is ever sent


def load_script():
    spec = importlib.util.spec_from_file_location("download_blackmarble", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # leave no __pycache__ in scripts/phase0
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


download = load_script()


def no_network(*args, **kwargs):
    raise AssertionError("this path must not reach the LAADS listing or blackmarblepy")


def listing(product: str, missing: tuple = ()) -> dict[str, dict]:
    """A LAADS-like listing of one file per date of the download window, except the `missing` dates."""
    names = [f"{product}.A{day:%Y}{day.timetuple().tm_yday:03d}.h09v06.002.2024065214519.h5"
             for day in download.DATES if day not in missing]
    return {name: {"name": name, "md5sum": hashlib.md5(name.encode()).hexdigest()} for name in names}


def test_products_default_to_vnp46a2():
    assert download.parse_args([]).products == ("VNP46A2",)


@pytest.mark.parametrize(
    ("text", "products"),
    [
        ("VNP46A2,VNP46A1", ("VNP46A2", "VNP46A1")),
        ("VNP46A1", ("VNP46A1",)),
        (" VNP46A1 , VNP46A2,VNP46A1", ("VNP46A1", "VNP46A2")),  # spaces trimmed, order kept, each product once
    ],
)
def test_products_takes_a_comma_separated_list(text, products):
    assert download.parse_args(["--products", text]).products == products


@pytest.mark.parametrize("text", ["VNP46A3", "VNP46A2,VJ146A2", "vnp46a1", "VNP46A2,", ""])
def test_unknown_products_are_rejected(text, capsys):
    with pytest.raises(SystemExit) as stopped:
        download.parse_args(["--products", text])
    assert stopped.value.code == 2  # argparse's usage error
    assert "unknown product" in capsys.readouterr().err


def test_a_missing_token_fails_fast_before_any_listing_or_download(monkeypatch, capsys):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setattr(download, "load_dotenv", lambda *args, **kwargs: False)  # never read the real .env
    monkeypatch.setattr(download, "list_archive", no_network)
    monkeypatch.setattr(download, "BlackMarbleDownloader", no_network)
    assert download.main(["--products", "VNP46A2,VNP46A1"]) == download.NO_TOKEN == 1
    assert "EARTHDATA_TOKEN is missing" in capsys.readouterr().err


def test_each_product_goes_to_its_own_folder_and_the_worst_exit_code_wins(monkeypatch):
    calls, codes = [], {"VNP46A2": 0, "VNP46A1": download.STOPPED}

    def fake_download(product, token, directory):
        calls.append((product, token, directory))
        return codes[product]

    monkeypatch.setenv("EARTHDATA_TOKEN", TOKEN)
    monkeypatch.setattr(download, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(download, "download_product", fake_download)
    assert download.main(["--products", "VNP46A2,VNP46A1"]) == download.STOPPED
    assert calls == [(product, TOKEN, download.RAW_DIR / product) for product in ("VNP46A2", "VNP46A1")]
    assert download.RAW_DIR == download.REPO / "data" / "raw" / "blackmarble"


class StoppingDownloader:
    """blackmarblepy's BlackMarbleDownloader when its manifest lacks a date: a ValueError before any download."""

    def __init__(self, token, directory):
        self.directory = directory

    def download(self, gdf, product_id, date_range, skip_if_exists):
        raise ValueError("The manifest retrieved from NASA DAAC (https://ladsweb.modaps.eosdis.nasa.gov) indicates "
                         "that 3 required files could not found.\nSome files may be missing due to recent data removals.")


def test_an_archive_gap_is_named_instead_of_a_traceback(monkeypatch, tmp_path, capsys):
    gap = (dt.date(2022, 9, 30), dt.date(2022, 10, 1), dt.date(2022, 10, 5))
    monkeypatch.setattr(download, "list_archive", lambda product: listing(product, gap))
    monkeypatch.setattr(download, "BlackMarbleDownloader", StoppingDownloader)
    assert download.download_product("VNP46A1", TOKEN, tmp_path / "VNP46A1") == download.STOPPED
    err = capsys.readouterr().err
    assert "VNP46A1: download stopped: blackmarblepy raised ValueError: The manifest retrieved from NASA DAAC" in err
    assert "with no VNP46A1 file in the LAADS archive: 2022-09-30..2022-10-01, 2022-10-05 (3 of 57 dates)" in err
    assert "Traceback" not in err


def test_an_empty_listing_is_reported_as_a_gap_without_calling_blackmarblepy(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(download, "list_archive", lambda product: {})
    monkeypatch.setattr(download, "BlackMarbleDownloader", no_network)
    assert download.download_product("VNP46A2", TOKEN, tmp_path) == download.STOPPED
    assert "2022-08-25..2022-10-20 (57 of 57 dates)" in capsys.readouterr().err


def test_downloads_are_checked_against_the_listed_md5(monkeypatch, tmp_path, capsys):
    files = listing("VNP46A1")
    corrupt, seen = sorted(files)[3], {}

    class WritingDownloader:
        """Writes every listed file with bytes that match its MD5, except one."""

        def __init__(self, token, directory):
            seen["directory"] = directory

        def download(self, gdf, product_id, date_range, skip_if_exists):
            seen.update(product=product_id, dates=date_range, skip=skip_if_exists)
            for name in files:
                (seen["directory"] / name).write_bytes(b"truncated" if name == corrupt else name.encode())

    monkeypatch.setattr(download, "list_archive", lambda product: files)
    monkeypatch.setattr(download, "BlackMarbleDownloader", WritingDownloader)
    assert download.download_product("VNP46A1", TOKEN, tmp_path / "VNP46A1") == download.BAD_FILES
    assert seen == {"directory": tmp_path / "VNP46A1", "product": download.Product.VNP46A1,
                    "dates": list(download.DATES), "skip": True}
    out = capsys.readouterr().out
    assert "VNP46A1: listed 57, on disk 57" in out and f"bad: {corrupt}" in out
    (tmp_path / "VNP46A1" / corrupt).write_bytes(corrupt.encode())
    assert download.verify("VNP46A1", files, tmp_path / "VNP46A1") == 0
