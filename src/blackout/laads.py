"""NASA access for Black Marble: list files on LAADS, then fetch whole files into memory from Earthdata Cloud.

Measured on 2026-11-08: LAADS serves this account at 3-4 MB/s in total however many connections are open, while
the same files on Earthdata Cloud (data.laadsdaac.earthdatacloud.nasa.gov, redirected to CloudFront) come at
~18 MB/s with 6 at once. Range requests that skip unneeded layers were slower on both, because h5py's metadata
reads become many round trips. So the build fetches whole files into memory, checks each MD5 from the LAADS
listing, reads the layers it needs, and never writes the tile to disk. LAADS is the fallback.
TLS verification stays on (blackmarblepy turns it off when listing files).
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import h5py
import httpx

from blackout.nightlights import PassNight, TileNight, parse_name, pass_night_from_h5, tile_night_from_h5, tile_origin

DETAILS = "https://ladsweb.modaps.eosdis.nasa.gov/api/v2/content/details"
ARCHIVE_SET = "5200"  # Collection 2
CLOUD = "https://data.laadsdaac.earthdatacloud.nasa.gov/prod-lads"
RETRIES = 5
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_LISTING = RETRY_STATUS | {404}
LISTING_WORKERS = 8
TOKEN_CHARACTERS = re.compile(r"[\x21-\x7e]+")  # printable ASCII, no spaces: all a token is made of


class TokenMissingError(RuntimeError):
    pass


def earthdata_token() -> str:
    """The token from the EARTHDATA_TOKEN env var, or from a gitignored .env in the working directory. Fails fast.

    Spaces and line breaks around a pasted token are dropped. Anything else that cannot go into an HTTP header is
    refused here, without echoing the value: httpx would quote the whole header, token included, in its error.
    """
    token = (os.environ.get("EARTHDATA_TOKEN") or "").strip()
    env_file = Path.cwd() / ".env"
    if not token and env_file.exists():
        from dotenv import dotenv_values

        token = (dotenv_values(env_file).get("EARTHDATA_TOKEN") or "").strip()
    if not token:
        raise TokenMissingError("EARTHDATA_TOKEN is not set: create a token at urs.earthdata.nasa.gov and put "
                                "EARTHDATA_TOKEN=... in .env (gitignored) or your shell profile")
    if not TOKEN_CHARACTERS.fullmatch(token):
        raise TokenMissingError("EARTHDATA_TOKEN contains whitespace, control or non-ASCII characters: paste it again")
    return token


def client_for(token: str, timeout: float = 120) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=True, headers={"Authorization": f"Bearer {token}"},
                        limits=httpx.Limits(max_connections=16, max_keepalive_connections=16))


@dataclass(frozen=True)
class LaadsFile:
    name: str
    url: str
    size: int
    md5: str


def query_params(product: str, tile_id: str, first: date, last: date, page: int = 1) -> dict[str, str]:
    """The /api/v2/content/details query blackmarblepy sends, for one tile (box inset so neighbours stay out)."""
    west, north = tile_origin(tile_id)
    return {
        "products": product,
        "archiveSet": ARCHIVE_SET,
        "temporalRanges": f"{first}..{last}",
        "regions": f"[BBOX]W{west + 1} N{north - 1} E{west + 9} S{north - 9}",
        "page": str(page),
    }


def _page(client: httpx.Client, product: str, tile_id: str, first: date, last: date, page: int) -> dict:
    # The details API sometimes answers 404 for a page that exists a moment later, so 404 is retried here.
    return _get(client, DETAILS, params=query_params(product, tile_id, first, last, page), retry=RETRY_LISTING).json()


def list_tile_files(client: httpx.Client, product: str, tile_id: str, first: date, last: date) -> dict[date, LaadsFile]:
    """Archive files of one product and tile with file dates in [first, last], by file date.

    The API returns one day per page, so a 55-night storm is 55 pages; pages after the first are fetched at once.
    """
    first_page = _page(client, product, tile_id, first, last, 1)
    pages = int(first_page.get("n_pages", 1) or 1)
    with ThreadPoolExecutor(LISTING_WORKERS) as pool:
        rest = list(pool.map(lambda k: _page(client, product, tile_id, first, last, k), range(2, pages + 1)))
    found: dict[date, LaadsFile] = {}
    for body in [first_page, *rest]:
        for item in body.get("content", []):
            name_product, file_date, name_tile = parse_name(item["name"])
            if name_product == product and name_tile == tile_id and first <= file_date <= last:
                found[file_date] = LaadsFile(item["name"], item["downloadsLink"], int(item["size"]), item["md5sum"])
    return found


def _get(client: httpx.Client, url: str, retry: frozenset[int] = RETRY_STATUS, **kwargs) -> httpx.Response:
    """GET with retries and backoff for timeouts and the `retry` status codes."""
    for attempt in range(RETRIES):
        try:
            response = client.get(url, **kwargs)
            if response.status_code in retry:
                raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as err:
            retryable = not isinstance(err, httpx.HTTPStatusError) or err.response.status_code in retry
            if not retryable or attempt == RETRIES - 1:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def fetch_bytes(client: httpx.Client, file: LaadsFile) -> bytes:
    """The whole file, from Earthdata Cloud first and LAADS if that fails, checked against the listing's MD5."""
    product = file.name.split(".")[0]
    errors = []
    for url in (f"{CLOUD}/{product}/{file.name}", file.url):
        try:
            data = _get(client, url).content  # httpx drops the token when redirected to CloudFront
        except httpx.HTTPError as err:
            errors.append(f"{url.split('/')[2]}: {err}")
            continue
        if len(data) == file.size and hashlib.md5(data).hexdigest() == file.md5:
            return data
        errors.append(f"{url.split('/')[2]}: size or MD5 mismatch")
    raise OSError(f"{file.name}: " + "; ".join(errors))


def read_remote(client: httpx.Client, file: LaadsFile) -> TileNight | PassNight:
    """An A2 file's TileNight or an A1 file's PassNight, read from memory."""
    data = fetch_bytes(client, file)
    with h5py.File(io.BytesIO(data), "r") as h5:
        if file.name.startswith(("VNP46A2", "VJ146A2")):
            return tile_night_from_h5(h5, file.name)
        return pass_night_from_h5(h5, file.name)


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download_laads(product: str, tile_id: str, dates: list[date], token: str, out_dir: Path) -> list[Path]:
    """Download whole files of one product and tile for `dates` into out_dir, checking each MD5. Returns the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = sorted(set(dates))
    if not wanted:
        return []
    paths = []
    with client_for(token, timeout=600) as client:
        listing = list_tile_files(client, product, tile_id, wanted[0], wanted[-1])
        for day in wanted:
            file = listing.get(day)
            if file is None:
                continue
            path = out_dir / file.name
            if not (path.exists() and path.stat().st_size == file.size and _md5(path) == file.md5):
                path.write_bytes(fetch_bytes(client, file))
            paths.append(path)
    return paths
