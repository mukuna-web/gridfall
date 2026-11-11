"""Phase 0, agent `geo`: download the Census, ACS and HURDAT2 inputs.

Run from the repo root:

    uv run python -I scripts/phase0/geo_fetch.py              # approved downloads
    uv run python -I scripts/phase0/geo_fetch.py --acs-bulk   # ALSO the keyless ACS file

What it fetches (all public data, no account, no form):

* Census cartographic county boundaries (cb_2022_us_county_500k.zip)
* NHC HURDAT2 best-track file (hurdat2-1851-2025-02272026.txt)
* ACS 2022 5-year B25001_001E through the Census Data API. As of 2026-11-05 that
  API answers every data query with a redirect to ``missing_key.html`` (a key needs
  a sign-up form), so this step is recorded as BLOCKED and the redirect is not followed.
* ``--acs-bulk`` (off by default, needs the user's OK): the same ACS table from the
  keyless bulk file on www2.census.gov.

Everything downloaded is untrusted data. Files are size-capped, signature-checked,
written under data/raw/, never extracted and never executed.

Exit code: 0 an ACS file is on disk, 1 error, 2 partial (no ACS housing-unit file).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_CENSUS = REPO_ROOT / "data" / "raw" / "census"
RAW_HURDAT2 = REPO_ROOT / "data" / "raw" / "hurdat2"
MANIFEST_PATH = REPO_ROOT / "data" / "interim" / "geo_fetch_manifest.json"
ACS_API_JSON = RAW_CENSUS / "acs5_2022_fl_B25001.json"
ACS_BULK_DAT = RAW_CENSUS / "acsdt5y2022-b25001.dat"

USER_AGENT = "blackout-from-space-phase0/geo (public-data research script)"
CHUNK_BYTES = 64 * 1024
HEAD_BYTES = 4096
MiB = 1024 * 1024
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

COUNTY_ZIP_URL = (
    "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_county_500k.zip"
)
HURDAT2_URL = "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-02272026.txt"
ACS_API_URL = (
    "https://api.census.gov/data/2022/acs/acs5"
    "?get=NAME,B25001_001E&for=county:*&in=state:12"
)
ACS_BULK_URL = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/2022/table-based-SF/"
    "data/5YRData/acsdt5y2022-b25001.dat"
)

ZIP_MAGIC = b"PK\x03\x04"
HURDAT2_HEADER = re.compile(rb"^AL\d{6},")
ACS_BULK_HEADER = b"GEO_ID|B25001_E001|B25001_M001"

Validator = Callable[
    [bytes], str | None
]  # error message, or None when the bytes look right


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    dest: Path
    max_bytes: int
    validate: Validator


@dataclass(frozen=True)
class FetchResult:
    key: str
    url: str
    path: str
    status: str  # downloaded | cached | blocked
    http_status: int | None
    size_bytes: int | None
    sha256: str | None
    last_modified: str | None
    etag: str | None
    retrieved_utc: str
    note: str


# ----------------------------------------------------------------------------- helpers
def _now_utc() -> str:
    return datetime.now(UTC).strftime(TIME_FORMAT)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_zip(head: bytes) -> str | None:
    return None if head.startswith(ZIP_MAGIC) else "not a zip archive (bad magic bytes)"


def _check_hurdat2(head: bytes) -> str | None:
    if HURDAT2_HEADER.match(head):
        return None
    return "does not start with a HURDAT2 storm header"


def _check_acs_bulk(head: bytes) -> str | None:
    first_line = head.split(b"\n", 1)[0].strip()
    if first_line == ACS_BULK_HEADER:
        return None
    return f"unexpected header line: {first_line!r}"


def _validate_acs_api_json(body: bytes) -> str | None:
    try:
        rows = json.loads(body)
    except json.JSONDecodeError as error:
        return f"response is not JSON: {error}"
    if not (isinstance(rows, list) and rows and isinstance(rows[0], list)):
        return "response is not a JSON array of arrays"
    if rows[0][:2] != ["NAME", "B25001_001E"]:
        return f"unexpected header row {rows[0]}"
    return None


def load_previous_manifest() -> dict[str, dict]:
    """Earlier manifest entries by key, so a cached re-run keeps its provenance."""
    if not MANIFEST_PATH.exists():
        return {}
    try:
        return {entry["key"]: entry for entry in json.loads(MANIFEST_PATH.read_text())}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def _cached_result(
    key: str, url: str, dest: Path, previous: dict[str, dict]
) -> FetchResult:
    """Describe a file already on disk; carry over download details if the hash matches."""
    stat = dest.stat()
    digest = _sha256(dest)
    prior = previous.get(key, {})
    carried = prior if prior.get("sha256") == digest else {}
    modified = datetime.fromtimestamp(stat.st_mtime, UTC).strftime(TIME_FORMAT)
    return FetchResult(
        key=key,
        url=carried.get("url", url),
        path=_rel(dest),
        status="cached",
        http_status=carried.get("http_status"),
        size_bytes=stat.st_size,
        sha256=digest,
        last_modified=carried.get("last_modified"),
        etag=carried.get("etag"),
        retrieved_utc=carried.get("retrieved_utc", modified),
        note="already on disk; pass --force to re-download",
    )


def _downloaded_result(
    key: str, url: str, dest: Path, response: httpx.Response
) -> FetchResult:
    return FetchResult(
        key=key,
        url=url,
        path=_rel(dest),
        status="downloaded",
        http_status=response.status_code,
        size_bytes=dest.stat().st_size,
        sha256=_sha256(dest),
        last_modified=response.headers.get("last-modified"),
        etag=response.headers.get("etag"),
        retrieved_utc=_now_utc(),
        note="",
    )


# ----------------------------------------------------------------------------- downloads
def _stream_to_part_file(
    client: httpx.Client, source: Source
) -> tuple[Path, httpx.Response]:
    """Download source.url to <dest>.part with a hard size cap and a content check."""
    part = source.dest.with_name(source.dest.name + ".part")
    written = 0
    head = b""
    try:
        with client.stream("GET", source.url) as response:
            response.raise_for_status()
            declared = int(response.headers.get("content-length", "0") or 0)
            if declared > source.max_bytes:
                raise ValueError(
                    f"declared size {declared} exceeds cap {source.max_bytes}"
                )
            with part.open("wb") as handle:
                for chunk in response.iter_bytes(CHUNK_BYTES):
                    written += len(chunk)
                    if written > source.max_bytes:
                        raise ValueError(
                            f"download exceeded the {source.max_bytes}-byte cap"
                        )
                    head += chunk[: HEAD_BYTES - len(head)]
                    handle.write(chunk)
        problem = source.validate(head)
        if problem:
            raise ValueError(problem)
        return part, response
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def fetch_file(
    client: httpx.Client, source: Source, force: bool, previous: dict[str, dict]
) -> FetchResult:
    source.dest.parent.mkdir(parents=True, exist_ok=True)
    if source.dest.exists() and not force:
        return _cached_result(source.key, source.url, source.dest, previous)
    part, response = _stream_to_part_file(client, source)
    os.replace(part, source.dest)
    return _downloaded_result(source.key, str(response.url), source.dest, response)


def _blocked_result(response: httpx.Response) -> FetchResult:
    where = response.headers.get("location", "?")
    flag = response.headers.get("x-datawebapi-keyerror", "-")
    return FetchResult(
        key="acs_api",
        url=ACS_API_URL,
        path=_rel(ACS_API_JSON),
        status="blocked",
        http_status=response.status_code,
        size_bytes=None,
        sha256=None,
        last_modified=None,
        etag=None,
        retrieved_utc=_now_utc(),
        note=(
            f"API needs a key: HTTP {response.status_code} -> {where} "
            f"(x-datawebapi-keyerror: {flag}); redirect not followed, no key requested"
        ),
    )


def fetch_acs_api(
    client: httpx.Client, force: bool, previous: dict[str, dict]
) -> FetchResult:
    """Try the Census Data API exactly as specified; never follow a redirect."""
    if ACS_API_JSON.exists() and not force:
        return _cached_result("acs_api", ACS_API_URL, ACS_API_JSON, previous)
    response = client.get(ACS_API_URL, follow_redirects=False)
    if response.is_redirect:
        return _blocked_result(response)
    response.raise_for_status()
    problem = _validate_acs_api_json(response.content)
    if problem:
        raise ValueError(f"ACS API: {problem}")
    ACS_API_JSON.parent.mkdir(parents=True, exist_ok=True)
    ACS_API_JSON.write_bytes(response.content)
    return _downloaded_result("acs_api", ACS_API_URL, ACS_API_JSON, response)


def build_sources(include_acs_bulk: bool) -> list[Source]:
    approved = [
        Source(
            "county_zip",
            COUNTY_ZIP_URL,
            RAW_CENSUS / "cb_2022_us_county_500k.zip",
            50 * MiB,
            _check_zip,
        ),
        Source(
            "hurdat2",
            HURDAT2_URL,
            RAW_HURDAT2 / "hurdat2-1851-2025-02272026.txt",
            20 * MiB,
            _check_hurdat2,
        ),
    ]
    if not include_acs_bulk:
        return approved
    bulk = Source(
        "acs_bulk_b25001", ACS_BULK_URL, ACS_BULK_DAT, 60 * MiB, _check_acs_bulk
    )
    return [*approved, bulk]


# ----------------------------------------------------------------------------- driver
def write_manifest(results: list[FetchResult]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")


def print_results(results: list[FetchResult]) -> None:
    for r in results:
        print(f"[{r.status:10}] {r.key:16} {r.path}")
        print(
            f"             bytes={r.size_bytes} sha256={r.sha256} http={r.http_status}"
        )
        print(
            f"             last-modified={r.last_modified} etag={r.etag} retrieved={r.retrieved_utc}"
        )
        if r.note:
            print(f"             note: {r.note}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force", action="store_true", help="re-download files already on disk"
    )
    parser.add_argument(
        "--acs-bulk",
        action="store_true",
        help="also fetch the keyless ACS bulk file (17.9 MB); only with the user's approval",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    previous = load_previous_manifest()
    timeout = httpx.Timeout(120.0, connect=20.0)
    try:
        with httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True
        ) as client:
            results = [
                fetch_file(client, source, args.force, previous)
                for source in build_sources(args.acs_bulk)
            ]
            results.append(fetch_acs_api(client, args.force, previous))
    except (httpx.HTTPError, ValueError, OSError) as error:
        print(f"FETCH FAILED: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    write_manifest(results)
    print_results(results)
    if ACS_API_JSON.exists() or ACS_BULK_DAT.exists():
        return 0
    print("PARTIAL: no ACS housing-unit file on disk (API needs a key; see --acs-bulk)")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
