"""Chart for the Phase 0 spike (scripts/phase0/ian_lee.py): % darker and EAGLE-I % out by night, landfall marked.

Written by Claude at the user's request as part of the Phase 0 spike (see docs/decision-log.md), and split out of
ian_lee.py so that each file stays under 800 lines. ian_lee.py imports it by path, because scripts/ is not a
package. It draws from the night table only and never opens a downloaded file.
"""

import datetime as dt
import math
from pathlib import Path

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter

# A colour-blind-safe blue/orange pair (checked with a CVD validator) on recessive grey chrome.
SURFACE, INK, INK_SECONDARY, INK_MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID_LINE, AXIS_LINE, HIDDEN_WASH = "#e1e0d9", "#c3c2b7", "#f0efec"
DARKER_COLOR, EAGLEI_COLOR = "#2a78d6", "#eb6834"
MIN_LABEL_GAP_PCT = 8.0
HIDDEN_STYLES = (("cant_see", "x", "Can't see: under half of the baseline light is visible tonight"),
                 ("not_measurable", "^", "Not measurable: no baseline light"))
# How ian_lee.py found each pass (its pass_source column), in words for the chart.
PASS_SOURCE_TEXT = {"VNP46A1": "median VNP46A1 UTC_Time over the county",
                    "nominal_solar_time": "01:30 local mean solar time at the county's longitude"}


def style_axes(ax, xlabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID_LINE, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS_LINE)
    ax.axhline(0, color=AXIS_LINE, linewidth=0.8, zorder=1)
    ax.tick_params(axis="both", length=0, labelsize=8.5, labelcolor=INK_MUTED)
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.DayLocator(bymonthday=(1, 8, 15, 22)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    ax.set_xlabel(xlabel, fontsize=8.5, color=INK_SECONDARY)
    ax.set_ylabel("Percent", fontsize=8.5, color=INK_SECONDARY)


def mark_hidden_nights(ax, x: np.ndarray, status: np.ndarray) -> None:
    """Nights without an estimate: a shaded slot and a marker along the top, never a value of zero."""
    for name, marker, label in HIDDEN_STYLES:
        hidden = x[status == name]
        for night in hidden:
            ax.axvspan(night - 0.5, night + 0.5, color=HIDDEN_WASH, linewidth=0, zorder=0)
        if hidden.size:
            ax.scatter(hidden, np.full(hidden.size, 0.97), transform=ax.get_xaxis_transform(), marker=marker, s=30,
                       color=INK_MUTED, linewidths=1.2, label=label, zorder=4, clip_on=False)


def pass_numbers(table: pd.DataFrame) -> np.ndarray:
    """Each row's pass_utc as a matplotlib date number (UTC)."""
    return mdates.date2num(pd.to_datetime(table["pass_utc"], utc=True).dt.tz_localize(None).to_numpy())


def moment_x(moment: pd.Timestamp, passes: np.ndarray, x: np.ndarray) -> float:
    """Where a moment sits on the night axis. Night N is drawn at date N but seen at its pass early on N + 1, so the
    moment goes between the two passes around it, or keeps the nearest pass's offset when it falls outside them."""
    order = np.argsort(passes)
    passes, x = passes[order], x[order]
    t = float(mdates.date2num(moment.tz_convert("UTC").tz_localize(None)))
    if passes[0] <= t <= passes[-1]:
        return float(np.interp(t, passes, x))
    end = 0 if t < passes[0] else -1
    return t - float(passes[end] - x[end])


def mark_landfall(ax, landfall_utc: pd.Timestamp, local_tz: str, passes: np.ndarray, x: np.ndarray) -> None:
    """A line at landfall, placed between the passes before and after it, labelled on the local clock."""
    at, local = moment_x(landfall_utc, passes, x), landfall_utc.tz_convert(local_tz)
    ax.axvline(at, color=INK_SECONDARY, linewidth=1.0, zorder=2)
    ax.annotate(f"Ian landfall\n{local:%b %d, %H:%M %Z}", xy=(at, 0.90), xycoords=ax.get_xaxis_transform(),
                xytext=(-5, 0), textcoords="offset points", ha="right", va="top", fontsize=8.5, color=INK_SECONDARY)


def label_line_ends(ax, x: np.ndarray, series: list[tuple[np.ndarray, str]]) -> None:
    """Direct labels at each line's last point, skipped when the two would collide (the legend names both)."""
    ends = [(x[np.isfinite(v)][-1], v[np.isfinite(v)][-1], text) for v, text in series if np.isfinite(v).any()]
    if len(ends) == 2 and abs(ends[0][0] - ends[1][0]) < 3 and abs(ends[0][1] - ends[1][1]) < MIN_LABEL_GAP_PCT:
        return
    for end_x, end_y, text in ends:
        ax.annotate(text, (end_x, end_y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8.5,
                    color=INK_SECONDARY)


def pass_text(table: pd.DataFrame) -> tuple[str, str]:
    """The x-axis label and a note on how the pass times were found, both read from the table's pass columns."""
    times = pd.to_datetime(table["pass_utc"], utc=True).dt.strftime("%H:%M")
    xlabel = (f"Night (UTC file date − 1); each point is that night's satellite pass, {times.min()}–{times.max()} "
              "UTC on the file date")
    counts = table["pass_source"].value_counts()
    sources = [f"{PASS_SOURCE_TEXT.get(source, source)} on {n} night{'' if n == 1 else 's'}"
               for source, n in counts.items()]
    return xlabel, "Pass time = " + "; ".join(sources) + "."


def plot_nights(table: pd.DataFrame, path: Path, eaglei_tz: str, *, layer: str, baseline: tuple[dt.date, dt.date],
                landfall_utc: pd.Timestamp, local_tz: str) -> None:
    """Two lines by night (% darker, EAGLE-I % out at each night's pass) on one percent axis, landfall marked, and
    the nights the satellite cannot see left as gaps with markers."""
    x = mdates.date2num(pd.to_datetime(table["night"]).to_numpy())
    status = table["status"].to_numpy()
    darker = np.where(status == "ok", 100 * table["pct_darker"].to_numpy(dtype=float), np.nan)
    out = 100 * table["eaglei_pct_out"].to_numpy(dtype=float)
    eaglei_label = ("EAGLE-I: % of customers out at the satellite pass (median of runs within ±60 min; stamps read "
                    f"as {eaglei_tz})")
    series = ((darker, DARKER_COLOR, "% darker", "Night lights: % darker than the pre-storm baseline (clear pixels)"),
              (out, EAGLEI_COLOR, "EAGLE-I % out", eaglei_label))
    xlabel, pass_note = pass_text(table)
    fig = Figure(figsize=(10, 5.8), layout="constrained", facecolor=SURFACE)
    ax = fig.subplots()
    style_axes(ax, xlabel)
    for values, color, _, label in series:
        ax.plot(x, values, color=color, linewidth=1.6, marker="o", markersize=4.5, markeredgecolor=SURFACE,
                markeredgewidth=1.0, solid_capstyle="round", solid_joinstyle="round", label=label, zorder=3)
    mark_hidden_nights(ax, x, status)
    mark_landfall(ax, landfall_utc, local_tz, pass_numbers(table), x)
    label_line_ends(ax, x, [(values, short) for values, _, short, _ in series])
    finite = np.concatenate([darker[np.isfinite(darker)], out[np.isfinite(out)], [0.0]])
    ax.set_ylim(min(-10.0, math.floor(finite.min() / 10) * 10), 105)
    ax.set_xlim(x.min() - 1, x.max() + 5)
    fig.suptitle("Hurricane Ian, Lee County FL (12071): satellite night lights vs. official outage counts",
                 x=0.01, ha="left", fontsize=12, color=INK, fontweight="bold")
    first, last = baseline
    ax.set_title(f"VNP46A2 {layer}. Clear = quality 0, cloud clear or probably clear, no snow.\nBaseline = per-pixel "
                 f"median of clear nights in files dated {first:%b %d} to {last:%b %d}, 2022.\n{pass_note}",
                 loc="left", fontsize=8.5, color=INK_SECONDARY)
    fig.legend(loc="outside lower left", frameon=False, fontsize=8.5, labelcolor=INK_SECONDARY)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
