# -*- coding: utf-8 -*-
"""The four plots a browser charting library does not draw.

Hexbin, KDE, ridgeline and the missing-cells matrix are rendered here with
matplotlib and returned as base64 PNGs — the same picture everywhere it later
appears, in the page, in a download, in a report.

Two defensive choices, both about running on cores this package has never
met:

  * **matplotlib and numpy are imported inside the functions.** They are a
    dependency of the cores we know, but a package must not become
    unimportable — taking its ACTIONS down with it — because a plotting
    library is missing. Absent, these four kinds return an error Result and
    the other seven carry on.
  * **The palette is borrowed, not required.** `nl2sql_engine.charts` holds
    the house colours on our core, so the PNGs match the interactive charts
    exactly. Another core's internals are not contract, so a failed import
    falls back to the same hex values copied here.
"""
from __future__ import annotations

import base64
import io
import math

from .charts import Chart, _points
from .common import is_float, q
from .targets import TargetError

HEXBIN_POINTS = 50_000
KDE_POINTS = 10_000
RIDGE_CATS = 12
KDE_HUES = 6
NULL_MATRIX_ROWS = 500

# The house palette, copied. Used only if the engine's own cannot be read.
_TEAL, _BLUE, _ORANGE = "#0d9488", "#00b4d8", "#f7931e"
_COLORS = [_TEAL, _BLUE, _ORANGE, "#9b59b6", "#2ecc71", "#e74c3c"]
_GRID = "#e8e4e0"

PNG_KINDS = ("hexbin", "kde", "ridgeline", "null_matrix")


def _kit():
    """(plt, np, palette, label) — or a message a person can act on."""
    try:
        import matplotlib
        matplotlib.use("Agg")                  # no display on a server
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception as exc:                   # noqa: BLE001
        raise TargetError(
            "This chart is drawn on the server and needs matplotlib, which "
            f"is not installed here ({exc}). The interactive kinds (bar, "
            "line, histogram, pie, scatter, box, correlation) need nothing "
            "extra.") from None
    try:                                       # the house style, if reachable
        from nl2sql_engine.charts import (COLORS, GRID, ORANGE, TEAL,
                                          _label as label)
        palette = {"COLORS": COLORS, "GRID": GRID, "ORANGE": ORANGE,
                   "TEAL": TEAL}
    except Exception:                          # noqa: BLE001 — not contract
        palette = {"COLORS": _COLORS, "GRID": _GRID, "ORANGE": _ORANGE,
                   "TEAL": _TEAL}

        def label(text):
            return str(text)
    return plt, np, palette, label


def _png(plt, fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _style(ax, grid: str) -> None:
    ax.grid(axis="y", color=grid, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=8)


def _numeric_values(c: Chart, xcol: str, hcol: str | None, cap: int):
    """The values themselves — these plots need points, not aggregates.
    Everything when it fits, an honest sample when it does not."""
    qx, finite = q(xcol), c.finite(xcol)
    cols = qx + (f", {q(hcol)}" if hcol else "")
    where = f"{qx} IS NOT NULL{finite}"
    total = int(c.one(f"SELECT count(*) FROM {c.rel} WHERE {where}") or 0)
    if not total:
        raise TargetError(f"{xcol!r} has no non-null values.")
    if total <= cap:
        return (c.rows(f"SELECT {cols} FROM {c.rel} WHERE {where}"),
                f"all {total:,} values")
    rows = c.rows(f"SELECT {cols} FROM (SELECT {cols} FROM {c.rel} "
                  f"WHERE {where}) USING SAMPLE {int(cap)} ROWS")
    return rows, f"{len(rows):,} sampled values of {total:,}"


def _kde_curve(np, vals, lo: float, hi: float, grid_n: int = 256):
    """Gaussian KDE with Scott's bandwidth, in plain numpy — scipy is not
    installed here and fifteen lines do not justify a 40 MB dependency."""
    a = vals[np.isfinite(vals)]
    if a.size < 3:
        return None, None
    sd = a.std(ddof=1)
    if not (sd > 0):
        return None, None
    bw = sd * a.size ** (-1 / 5)
    grid = np.linspace(lo, hi, grid_n)
    dens = np.zeros(grid_n)
    # Chunked: the full (grid × points) matrix at 10k points is fine, but
    # chunking keeps memory flat however the caps move later.
    for start in range(0, a.size, 4000):
        chunk = a[start:start + 4000]
        dens += np.exp(-0.5 * ((grid[:, None] - chunk[None, :]) / bw) ** 2
                       ).sum(axis=1)
    dens /= a.size * bw * math.sqrt(2 * math.pi)
    return grid, dens


# ── hexbin ─────────────────────────────────────────────────────────────────

def _hexbin(c: Chart, x, y, bins, **_):
    plt, np, pal, label = _kit()
    xcol = c.col(x, "x", numeric=True)
    ycol = c.col(y, "y", numeric=True)
    rows, basis = _points(c, xcol, ycol, None, HEXBIN_POINTS)
    xs = np.array([float(r[0]) for r in rows])
    ys = np.array([float(r[1]) for r in rows])
    fig, ax = plt.subplots(figsize=(7.5, 4.6), dpi=150)
    hb = ax.hexbin(xs, ys, gridsize=max(12, min(int(bins), 60)),
                   cmap="viridis", mincnt=1)
    fig.colorbar(hb, ax=ax, label="points per hex")
    ax.set_xlabel(label(xcol), fontsize=9)
    ax.set_ylabel(label(ycol), fontsize=9)
    ax.set_title(label(f"{ycol} vs {xcol}"), fontsize=10, color="#1a2b3d")
    _style(ax, pal["GRID"])
    fig.tight_layout()
    return {"renderer": "png", "png_base64": _png(plt, fig), "basis": basis,
            "meta": {}}


# ── kde ────────────────────────────────────────────────────────────────────

def _kde(c: Chart, x, hue, **_):
    plt, np, pal, label = _kit()
    xcol = c.col(x, "the value (x)", numeric=True)
    hcol = c.col(hue, "the colour (hue)") if hue else None
    rows, basis = _numeric_values(c, xcol, hcol, KDE_POINTS)
    all_vals = np.array([float(r[0]) for r in rows])
    lo, hi = all_vals.min(), all_vals.max()
    if hi <= lo:
        raise TargetError(f"{xcol!r} holds a single value — no density to "
                          f"draw.")
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad

    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150)
    meta = {}
    if not hcol:
        grid, dens = _kde_curve(np, all_vals, lo, hi)
        if grid is None:
            raise TargetError("Not enough spread to estimate a density.")
        ax.fill_between(grid, dens, color=pal["TEAL"], alpha=0.25)
        ax.plot(grid, dens, color=pal["TEAL"], linewidth=2)
    else:
        hue_vals, hue_total = c.top_categories(hcol, KDE_HUES)
        hues = [str(h) for h in hue_vals]
        groups: dict[str, list] = {h: [] for h in hues}
        for r in rows:
            k = str(r[1])
            if r[1] is not None and k in groups:
                groups[k].append(float(r[0]))
        drew = 0
        for i, h in enumerate(hues):
            grid, dens = _kde_curve(np, np.array(groups[h]), lo, hi)
            if grid is None:
                continue
            colour = pal["COLORS"][i % len(pal["COLORS"])]
            ax.fill_between(grid, dens, color=colour, alpha=0.18)
            ax.plot(grid, dens, color=colour, linewidth=2, label=label(h))
            drew += 1
        if not drew:
            raise TargetError("No hue group had enough values for a density.")
        ax.legend(fontsize=8, frameon=False, title=label(hcol),
                  title_fontsize=8)
        meta = {"hue_shown": drew, "hue_total": hue_total}
    ax.set_xlabel(label(xcol), fontsize=9)
    ax.set_ylabel("density", fontsize=9)
    ax.set_yticks([])
    ax.set_title(label(f"Distribution of {xcol}"), fontsize=10,
                 color="#1a2b3d")
    _style(ax, pal["GRID"])
    fig.tight_layout()
    return {"renderer": "png", "png_base64": _png(plt, fig), "basis": basis,
            "meta": meta}


# ── ridgeline ──────────────────────────────────────────────────────────────

def _ridgeline(c: Chart, x, hue, **_):
    """One density per category, stacked — the joyplot. The categories are
    the point, so hue is REQUIRED here and capped harder than elsewhere:
    forty ridges is wallpaper."""
    plt, np, pal, label = _kit()
    xcol = c.col(x, "the value (x)", numeric=True)
    hcol = c.col(hue, "the categories (hue)")
    rows, basis = _numeric_values(c, xcol, hcol, KDE_POINTS * 5)
    cat_vals, cats_total = c.top_categories(hcol, RIDGE_CATS)
    cats = [str(v) for v in cat_vals]
    groups: dict[str, list] = {v: [] for v in cats}
    for r in rows:
        k = str(r[1])
        if r[1] is not None and k in groups:
            groups[k].append(float(r[0]))

    all_vals = np.array([float(r[0]) for r in rows])
    lo, hi = all_vals.min(), all_vals.max()
    if hi <= lo:
        raise TargetError(f"{xcol!r} holds a single value — no densities to "
                          f"draw.")
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad

    curves = []
    for v in cats:
        grid, dens = _kde_curve(np, np.array(groups[v]), lo, hi)
        if grid is not None:
            curves.append((v, grid, dens, float(np.median(np.array(groups[v])))))
    if not curves:
        raise TargetError("No category had enough values for a density.")
    curves.sort(key=lambda t: t[3])            # low medians at the bottom
    peak = max(d.max() for _v, _g, d, _m in curves)

    fig, ax = plt.subplots(figsize=(7.5, 0.55 * len(curves) + 1.8), dpi=150)
    for i, (v, grid, dens, _m) in enumerate(curves):
        off = i * 0.8
        colour = pal["COLORS"][i % len(pal["COLORS"])]
        ax.fill_between(grid, off, off + dens / peak, color=colour,
                        alpha=0.55, zorder=len(curves) - i)
        ax.plot(grid, off + dens / peak, color=colour, linewidth=1.4,
                zorder=len(curves) - i)
        ax.text(lo, off + 0.06, label(v), fontsize=8, ha="left", va="bottom",
                color="#1a2b3d", zorder=99)
    ax.set_yticks([])
    ax.set_xlim(lo, hi)
    ax.set_xlabel(label(xcol), fontsize=9)
    title = f"{xcol} by {hcol}"
    if cats_total > len(curves):
        title += f" (top {len(curves)} of {cats_total})"
    ax.set_title(label(title), fontsize=10, color="#1a2b3d")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    return {"renderer": "png", "png_base64": _png(plt, fig), "basis": basis,
            "meta": {"hue_shown": len(curves), "hue_total": cats_total}}


# ── the missing-cells matrix ───────────────────────────────────────────────

def _null_matrix(c: Chart, **_):
    """The missingno picture: rows down, columns across, nulls in orange.

    Drawn from the FIRST rows in stored order, and labelled so — order often
    carries the pattern (a field added in 1997 is null before 1997), and a
    random sample would scramble exactly that.
    """
    plt, np, pal, label = _kit()
    cols = list(c.types)
    sel = ", ".join(f"({q(col)} IS NULL)" for col in cols)
    rows = c.rows(f"SELECT {sel} FROM {c.rel} LIMIT {NULL_MATRIX_ROWS}")
    if not rows:
        raise TargetError("No rows to draw.")
    m = np.array([[bool(v) for v in r] for r in rows], dtype=float)

    fig, ax = plt.subplots(
        figsize=(max(6.0, 0.42 * len(cols) + 1.5), 4.6), dpi=150)
    from matplotlib.colors import ListedColormap
    ax.imshow(m, aspect="auto", interpolation="nearest",
              cmap=ListedColormap(["#e8e4e0", pal["ORANGE"]]), vmin=0, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels([label(col) for col in cols], rotation=45, ha="right",
                       fontsize=7)
    ax.set_ylabel(f"first {len(rows)} rows, stored order", fontsize=8)
    ax.set_yticks([])
    pct = 100.0 * m.sum() / m.size
    ax.set_title(label(f"Missing cells (orange) — {pct:.1f}% of this view"),
                 fontsize=10, color="#1a2b3d")
    fig.tight_layout()
    return {"renderer": "png", "png_base64": _png(plt, fig),
            "basis": f"first {len(rows):,} rows in stored order", "meta": {}}


KINDS = {"hexbin": _hexbin, "kde": _kde, "ridgeline": _ridgeline,
         "null_matrix": _null_matrix}
