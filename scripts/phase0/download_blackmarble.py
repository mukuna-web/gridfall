"""Phase 0 spike: download Black Marble tiles for Hurricane Ian (Lee County) and verify them.

Written by Claude at the user's request; Week 1 is a by-hand check (see docs/decision-log.md).
Run from the repo root: uv run python -I scripts/phase0/download_blackmarble.py [--products VNP46A2,VNP46A1]

Each product goes to data/raw/blackmarble/<product>/ and is checked against a TLS-verified LAADS listing, file by
file, by name and MD5. VNP46A2 holds the night lights; VNP46A1 adds each night's pass time (UTC_Time) for
scripts/phase0/ian_lee.py. Exit codes: 1 EARTHDATA_TOKEN is missing, 2 a listed file is missing or fails its MD5
(argparse also exits 2 on a bad option), 3 no download: the archive lacks a date, or blackmarblepy stopped.
"""

import argparse
import datetime as dt
import hashlib
import itertools
import os
import re
import sys
from pathlib import Path

import geopandas as gpd
import httpx
from blackmarble.download import BlackMarbleDownloader
from blackmarble.types import Product
from dotenv import load_dotenv
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[2]
RAW_DIR = REPO / "data/raw/blackmarble"  # one folder per product
PRODUCTS = ("VNP46A2", "VNP46A1")  # what --products accepts; VNP46A2 is the default
START, END = dt.date(2022, 8, 25), dt.date(2022, 10, 20)
DATES = tuple(START + dt.timedelta(days=i) for i in range((END - START).days + 1))
# Lee, Charlotte and Collier counties all sit inside tile h09v06.
TILE = "h09v06"
WEST, SOUTH, EAST, NORTH = -82.4, 25.8, -80.8, 27.1
LAADS_DETAILS = "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/details"
NO_TOKEN, BAD_FILES, STOPPED = 1, 2, 3  # exit codes


def product_list(text: str) -> tuple[str, ...]:
    """--products: a comma-separated list drawn from PRODUCTS, kept in the order given, each product once."""
    names = tuple(dict.fromkeys(name.strip() for name in text.split(",")))
    unknown = [name for name in names if name not in PRODUCTS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown product {', '.join(map(repr, unknown))}; "
                                         f"choose from {', '.join(PRODUCTS)}")
    return names


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Black Marble tiles for Hurricane Ian and check each MD5.")
    parser.add_argument("--products", type=product_list, default=PRODUCTS[:1],
                        help=f"comma-separated, from {','.join(PRODUCTS)} (default {PRODUCTS[0]})")
    return parser.parse_args(argv)


def list_archive(product: str) -> dict[str, dict]:
    """List archive files by name, with TLS verification on (blackmarblepy's listing turns it off)."""
    params = {
        "products": product,
        "archiveSet": "5200",
        "temporalRanges": f"{START}..{END}",
        "regions": f"[BBOX]W{WEST} N{NORTH} E{EAST} S{SOUTH}",
    }
    files: dict[str, dict] = {}
    page, pages = 1, 1
    with httpx.Client(timeout=60) as client:
        while page <= pages:
            response = client.get(LAADS_DETAILS, params={**params, "page": page})
            response.raise_for_status()
            body = response.json()
            files.update({f["name"]: f for f in body.get("content", [])})
            pages = body.get("n_pages", 1)
            page += 1
    return files


def archive_gap(product: str, listing: dict[str, dict]) -> list[dt.date]:
    """The dates in START..END with no file for TILE in the listing."""
    name = re.compile(rf"^{product}\.A(\d{{4}})(\d{{3}})\.{TILE}\.")
    listed = {dt.date(int(m[1]), 1, 1) + dt.timedelta(days=int(m[2]) - 1) for m in map(name.match, listing) if m}
    return [day for day in DATES if day not in listed]


def date_spans(days: list[dt.date]) -> str:
    """Sorted dates as runs of consecutive days, such as '2022-09-30, 2022-10-02..2022-10-04'."""
    runs = itertools.groupby(enumerate(days), key=lambda item: item[1] - dt.timedelta(days=item[0]))
    spans = [[day for _, day in run] for _, run in runs]
    return ", ".join(str(span[0]) if len(span) == 1 else f"{span[0]}..{span[-1]}" for span in spans)


def report_gap(product: str, expected: dict[str, dict], reason: str) -> int:
    """Name the archive's missing dates for this product instead of a traceback."""
    gap = archive_gap(product, expected)
    named = f"{date_spans(gap)} ({len(gap)} of {len(DATES)} dates)" if gap else "none: the listing has every date"
    print(f"{product}: download stopped: {reason}\n  {TILE} dates from {START} to {END} with no {product} file in the "
          f"LAADS archive: {named}", file=sys.stderr)
    return STOPPED


def md5_of(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(product: str, expected: dict[str, dict], directory: Path) -> int:
    """Every listed file is on disk with its listed MD5."""
    found = {p.name: p for p in directory.rglob("*.h5")}
    bad = [
        name
        for name, meta in expected.items()
        if name not in found or md5_of(found[name]) != meta.get("md5sum")
    ]
    total_mb = sum(p.stat().st_size for p in found.values()) / 1e6
    print(f"{product}: listed {len(expected)}, on disk {len(found)} ({total_mb:.0f} MB), "
          f"missing or bad md5: {len(bad)}")
    for name in bad:
        print(f"  bad: {name}")
    return 0 if not bad else BAD_FILES


def download_product(product: str, token: str, directory: Path) -> int:
    """Download one product into `directory`, then verify it against the listing. blackmarblepy refuses the whole
    date range with a ValueError when its manifest lacks a date; that is reported as the archive's gap."""
    directory.mkdir(parents=True, exist_ok=True)
    expected = list_archive(product)
    if not expected:  # verify() would pass an empty listing, and blackmarblepy fails on one without a clear message
        return report_gap(product, expected, "the TLS-verified LAADS listing is empty")
    region = gpd.GeoDataFrame(geometry=[box(WEST, SOUTH, EAST, NORTH)], crs="EPSG:4326")
    try:
        BlackMarbleDownloader(token=token, directory=directory).download(
            gdf=region, product_id=Product[product], date_range=list(DATES), skip_if_exists=True
        )
    except ValueError as exc:
        first_line = (str(exc).strip() or repr(exc)).splitlines()[0]
        return report_gap(product, expected, f"blackmarblepy raised ValueError: {first_line}")
    return verify(product, expected, directory)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv(REPO / ".env")
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        print("EARTHDATA_TOKEN is missing: add it to .env (see .env.example).", file=sys.stderr)
        return NO_TOKEN
    return max(download_product(product, token, RAW_DIR / product) for product in args.products)


if __name__ == "__main__":
    sys.exit(main())
