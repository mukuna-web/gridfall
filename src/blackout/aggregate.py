"""County label grids, per-night county sums and "% darker" (Task 5).

Per night, a county is compared with its own baseline over the same pixels only: those clear tonight that also
have a baseline value. `pct_darker = 1 - tonight / base_visible`. A county that is mostly hidden tonight is
"cant_see", and one with almost no baseline light is "not_measurable"; neither gets a number, so "can't see"
never turns into zero (docs/plan.md, Review Focus 4).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from rasterio.transform import from_origin

from blackout.nightlights import PIXELS_PER_DEGREE, TileNight, clear_mask, tile_origin

TILE_PIXELS = 2400
MIN_CLEAR_NIGHTS = 5
VISIBLE_MIN = 0.5
# DARK_MIN: a county whose baseline light, summed over its pixels with a baseline value, is under this is
# "not_measurable". Units: nW/(cm^2 sr) summed over 1/240-degree pixels. 2,000 is about 4,000 pixels (~8 km^2 of
# land at ~0.5 nW, the Black Marble noise floor) of light. Chosen in Task 5 and logged (decision log, 2026-11-08).
DARK_MIN = 2_000.0
SUM_KEYS = ("tonight", "base_visible", "base_total", "clear_pixels", "pixels")
REPO = Path(__file__).resolve().parents[2]
LABEL_CACHE = REPO / "data/interim/labels"


def _grid_key(tile_id: str, counties: gpd.GeoDataFrame, shape: tuple[int, int]) -> str:
    digest = hashlib.sha1()
    digest.update(f"{tile_id}{shape}".encode())
    for fips, geom in zip(counties["fips"], counties.geometry):
        digest.update(fips.encode())
        digest.update(geom.wkb)
    return digest.hexdigest()[:16]


def county_label_grid(tile_id: str, counties: gpd.GeoDataFrame, shape: tuple[int, int] = (TILE_PIXELS, TILE_PIXELS),
                      cache: Path | None = LABEL_CACHE) -> np.ndarray:
    """int32 grid of 1-based row numbers of `counties` (in their given order); 0 means no county.

    Pixel centres decide membership (`all_touched=False`). Grids are cached in data/interim/labels/.
    """
    target = None
    if cache is not None:
        target = Path(cache) / f"{tile_id}_{_grid_key(tile_id, counties, shape)}.npz"
        if target.exists():
            with np.load(target) as saved:
                return saved["labels"]
    west, north = tile_origin(tile_id)
    transform = from_origin(west, north, 1 / PIXELS_PER_DEGREE, 1 / PIXELS_PER_DEGREE)
    shapes = [(geom, k + 1) for k, geom in enumerate(counties.to_crs("EPSG:4326").geometry) if geom is not None]
    labels = rasterize(shapes, out_shape=shape, transform=transform, fill=0, all_touched=False, dtype="int32")
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(target, labels=labels)
    return labels


def clear_radiance(t: TileNight, allow_snow: bool) -> np.ndarray:
    """Tonight's radiance where the pixel is clear, NaN elsewhere."""
    return np.where(clear_mask(t, allow_snow), t.radiance, np.float32(np.nan)).astype(np.float32)


def baseline_from_clear(stack: list[np.ndarray], rows_per_chunk: int = 200) -> np.ndarray:
    """Per-pixel median of the clear values; NaN where fewer than MIN_CLEAR_NIGHTS nights are clear."""
    if not stack:
        raise ValueError("no baseline nights")
    shape = stack[0].shape
    out = np.full(shape, np.nan, dtype=np.float32)
    for top in range(0, shape[0], rows_per_chunk):
        block = np.stack([a[top:top + rows_per_chunk] for a in stack])
        enough = np.sum(~np.isnan(block), axis=0) >= MIN_CLEAR_NIGHTS
        if enough.any():
            with np.errstate(all="ignore"):
                med = np.nanmedian(block[:, enough], axis=0)
            out[top:top + rows_per_chunk][enough] = med
    return out


def baseline_median(tiles: list[TileNight], allow_snow: bool) -> np.ndarray:
    return baseline_from_clear([clear_radiance(t, allow_snow) for t in tiles])


def county_sums(clear: np.ndarray, base: np.ndarray, labels: np.ndarray, n_counties: int) -> dict[str, np.ndarray]:
    """Arrays indexed by county row (label - 1): light tonight and at baseline over the pixels seen tonight that
    have a baseline, baseline light over all pixels with a baseline, and pixel counts."""
    counted = labels > 0
    has_base = counted & ~np.isnan(base)
    seen = has_base & ~np.isnan(clear)
    size = n_counties + 1

    def total(mask: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
        return np.bincount(labels[mask], weights=None if weights is None else weights[mask], minlength=size)[1:]

    return {
        "tonight": total(seen, clear.astype(np.float64)),
        "base_visible": total(seen, base.astype(np.float64)),
        "base_total": total(has_base, base.astype(np.float64)),
        "clear_pixels": total(seen).astype(np.float64),
        "pixels": total(counted).astype(np.float64),
    }


def county_night(t: TileNight, base: np.ndarray, labels: np.ndarray, allow_snow: bool,
                 n_counties: int | None = None) -> dict[str, np.ndarray]:
    n = int(labels.max()) if n_counties is None else n_counties
    return county_sums(clear_radiance(t, allow_snow), base, labels, n)


def add_sums(a: dict[str, np.ndarray] | None, b: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Elementwise sum across tiles (a new dict; inputs untouched)."""
    if a is None:
        return {k: b[k].copy() for k in SUM_KEYS}
    return {k: a[k] + b[k] for k in SUM_KEYS}


def finalize(sums: dict[str, np.ndarray], fips: list[str]) -> pd.DataFrame:
    """fips, pct_darker, visible_share, base_total, status from summed arrays (county rows in `fips` order)."""
    base_total = np.asarray(sums["base_total"], dtype=float)
    base_visible = np.asarray(sums["base_visible"], dtype=float)
    tonight = np.asarray(sums["tonight"], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        visible_share = np.where(base_total > 0, base_visible / base_total, 0.0)
        darker = np.where(base_visible > 0, 1 - tonight / base_visible, np.nan)
    status = np.where(base_total < DARK_MIN, "not_measurable", np.where(visible_share < VISIBLE_MIN, "cant_see", "ok"))
    return pd.DataFrame({
        "fips": list(fips),
        "pct_darker": np.where(status == "ok", darker, np.nan),
        "visible_share": visible_share,
        "base_total": base_total,
        "status": status,
    })


def group_median(values: np.ndarray, labels: np.ndarray, n_counties: int) -> tuple[np.ndarray, np.ndarray]:
    """(median, count) of the finite values per county row; NaN and 0 where a county has none."""
    keep = (labels > 0) & np.isfinite(values)
    med = np.full(n_counties, np.nan)
    count = np.zeros(n_counties)
    if keep.any():
        grouped = pd.Series(values[keep].astype(np.float64)).groupby(labels[keep] - 1)
        med[grouped.median().index.to_numpy()] = grouped.median().to_numpy()
        count[grouped.size().index.to_numpy()] = grouped.size().to_numpy()
    return med, count


def downsample(a: np.ndarray, factor: int = 8) -> np.ndarray:
    """Block mean ignoring NaN (NaN where a block has no value), for quicklook images."""
    rows, cols = (a.shape[0] // factor) * factor, (a.shape[1] // factor) * factor
    blocks = a[:rows, :cols].reshape(rows // factor, factor, cols // factor, factor)
    finite = np.isfinite(blocks)
    count = finite.sum(axis=(1, 3))
    total = np.where(finite, blocks, 0).sum(axis=(1, 3), dtype=np.float64)
    out = np.full(count.shape, np.nan, dtype=np.float32)
    np.divide(total, count, out=out, where=count > 0, casting="unsafe")
    return out
