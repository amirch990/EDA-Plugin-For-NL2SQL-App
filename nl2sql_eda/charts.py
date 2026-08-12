# -*- coding: utf-8 -*-
"""One chart for one relation — the numbers here, the drawing on the page.

The database does every aggregation: a bar chart over a million rows is a
GROUP BY, never a million rows shipped to a browser to be counted there. What
comes back is a small spec — categories, series, bin edges — and the page
draws it interactively.

The seaborn idea of `hue` runs through most kinds: a third column whose
values split the chart into coloured groups. Categories are capped, and the
caps are **reported** (`meta.categories_shown` vs `categories_total`) rather
than silently applied — a bar chart quietly showing 25 of 77 categories is
exactly the kind of wrongness this app teaches people to catch.

WHAT CHANGED FROM THE IN-APP ORIGINAL, AND WHY

The original held the capped category values in Python and fed them back as
BOUND PARAMETERS (`"col" IN (?,?,…)`), so that data never became SQL text.
A module has no parameters — `ctx.query` takes one string — so writing those
values into SQL would mean inventing a literal-quoting helper for arbitrary
values (dates, embedded quotes, blobs), which is precisely the thing the
original avoided.

So the caps are expressed as a JOIN against a CTE that recomputes the top
categories inside the same statement:

    WITH src AS (SELECT * FROM <relation>),
         top_x AS (SELECT x FROM src GROUP BY 1 ORDER BY <measure> DESC LIMIT 25)
    SELECT s.x, <measure> FROM src s JOIN top_x t ON s.x = t.x GROUP BY 1

No value ever leaves the database and comes back, so nothing has to be
quoted, and the join keeps the column's own type. One statement, one pass,
and the invariant is stronger than before rather than weaker.
"""
from __future__ import annotations

from .common import is_float, is_numeric, num, q, simple_type
from .targets import TargetError

# The caps, and why they are these numbers: a legend past eight entries is a
# lookup table, not a legend; 25 bars fill a laptop screen exactly; five
# thousand points is where a browser canvas stays fluid.
HUE_CATS = 8
BAR_CATS = 25
PIE_CATS = 8
BOX_CATS = 15
# Boxes are wide objects: with a hue each category holds several, so both
# axes are capped harder — 8 × 4 = 32 boxes is the readable ceiling.
BOX_CATS_HUED = 8
BOX_HUES = 4
# Outlier points drawn per box. The MOST extreme are kept when there are
# more — for outlier inspection the far ones are the ones being looked for.
BOX_OUTLIER_CAP = 200
SCATTER_POINTS = 5_000
CORR_COLS = 12
LINE_POINTS = 2_000

AGGS = {"count": "count(*)", "sum": "sum", "avg": "avg",
        "min": "min", "max": "max"}
GRANULARITIES = ("as-is", "year", "month", "week", "day")

CLIENT_KINDS = ("bar", "line", "histogram", "pie", "scatter", "box", "corr")


class Chart:
    """Everything a kind needs: the relation, its column types, and a way to
    ask questions about it. One object instead of five arguments."""

    def __init__(self, ctx, target: dict):
        self.ctx = ctx
        self.rel = target["relation"]
        self.label = target["label"]
        self.types = {c: (duck, simple_type(duck)) for c, duck in target["columns"]}

    # ── asking ─────────────────────────────────────────────────────────────

    def rows(self, sql: str) -> list:
        _, rows = self.ctx.query(sql)
        return rows

    def one(self, sql: str):
        rows = self.rows(sql)
        return rows[0][0] if rows else None

    def src(self, *ctes: str) -> str:
        """The WITH prefix every composed statement starts from: `src` is the
        relation, whether it began life as a table or a pasted query."""
        parts = [f"src AS (SELECT * FROM {self.rel})"] + [c for c in ctes if c]
        return "WITH " + ",\n     ".join(parts) + "\n"

    def basis(self) -> str:
        total = self.one(f"SELECT count(*) FROM {self.rel}") or 0
        return f"aggregated over all {total:,} rows"

    # ── validating ─────────────────────────────────────────────────────────

    def col(self, name, role: str, numeric: bool = False) -> str:
        """A column that exists in THIS relation — the only names that ever
        reach the SQL. Everything else is a message naming the role that was
        wrong."""
        name = (name or "").strip()
        if not name:
            raise TargetError(f"This chart needs a column for {role}.")
        if name not in self.types:
            have = ", ".join(list(self.types)[:12])
            raise TargetError(f"No column {name!r} in this data. "
                              f"Columns: {have}…")
        duck = self.types[name][0]
        if numeric and not is_numeric(duck):
            # "unknown" is what an entirely-NULL column reports (typeof reads
            # a VALUE's type, and there are none). Saying "is unknown" would
            # puzzle anyone; the real fact is that the column is empty.
            if duck == "unknown":
                raise TargetError(f"{name!r} has no values at all — nothing "
                                  f"to draw.")
            raise TargetError(f"{role} needs a numeric column; {name!r} is "
                              f"{duck}.")
        return name

    def measure(self, y, agg: str) -> tuple[str, str]:
        """(SQL expression, label) for the thing being measured."""
        if agg == "count":
            return "count(*)", "count"
        ycol = self.col(y, "the value (y)", numeric=True)
        return f"{AGGS[agg]}({q(ycol)})", f"{agg}({ycol})"

    def finite(self, col: str) -> str:
        """A float column can hold NaN and infinity, and both poison a bin
        boundary or an axis. Excluded where they would."""
        return f" AND isfinite({q(col)})" if is_float(self.types[col][0]) else ""

    def top_categories(self, col: str, cap: int,
                       measure: str = "count(*)") -> tuple[list, int]:
        """The cap'd category values, biggest first, and how many exist —
        the second number is what makes the cap honest instead of silent."""
        qc = q(col)
        total = int(self.one(
            f"SELECT count(DISTINCT {qc}) FROM {self.rel}") or 0)
        rows = self.rows(
            f"{self.src()}SELECT {qc} FROM src WHERE {qc} IS NOT NULL "
            f"GROUP BY 1 ORDER BY {measure} DESC, {qc} LIMIT {int(cap)}")
        return [r[0] for r in rows], total

    def top_cte(self, name: str, col: str, cap: int,
                measure: str = "count(*)") -> str:
        """A CTE holding the same top categories — used to JOIN the cap into
        the main statement instead of listing values back to the database."""
        qc = q(col)
        return (f"{name} AS (SELECT {qc} AS v FROM src WHERE {qc} IS NOT NULL "
                f"GROUP BY 1 ORDER BY {measure} DESC, {qc} LIMIT {int(cap)})")


def draw(ctx, target: dict, kind: str, x=None, y=None, hue=None,
         agg: str = "count", bins: int = 30, granularity: str = "as-is",
         stacked: bool = False) -> dict:
    """The one entry point: validate, dispatch, return a spec."""
    fn = _KINDS.get(kind)
    if fn is None:
        # The server-drawn kinds live in their own module so that matplotlib
        # is imported only when one is actually asked for.
        from .charts_png import KINDS as PNG_KINDS_MAP
        fn = PNG_KINDS_MAP.get(kind)
    if fn is None:
        from .charts_png import PNG_KINDS
        raise TargetError(f"Unknown chart kind {kind!r}. Kinds: "
                          f"{', '.join(tuple(_KINDS) + PNG_KINDS)}.")
    if agg not in AGGS:
        raise TargetError(f"Unknown aggregation {agg!r}. "
                          f"One of: {', '.join(AGGS)}.")
    bins = max(5, min(int(bins or 30), 100))
    c = Chart(ctx, target)
    spec = fn(c, x=x, y=y, hue=hue, agg=agg, bins=bins,
              granularity=granularity, stacked=stacked)
    # A PNG kind names itself "png" so a frontend that knows nothing about
    # this dialect can still show the image; the interactive kinds carry
    # their own dialect name for the page's option builder.
    spec["type"] = "png" if spec.get("renderer") == "png" else f"eda/{kind}"
    spec["kind"] = kind
    spec.setdefault("renderer", "echarts")
    spec["rows"] = _fallback_rows(spec, kind)
    return spec


# How many fallback rows are worth carrying. Enough to read, few enough that
# a scatter of five thousand points does not double the response to serve a
# renderer that was only ever going to show a table.
FALLBACK_ROWS = 200


def _fallback_rows(spec: dict, kind: str) -> list:
    """The same chart as [label, value] pairs, for a frontend that does not
    know this dialect.

    The contract's simplest chart shape is `rows` of pairs, and a renderer
    that knows only that draws an EMPTY table from any richer spec — which
    reads as "the module is broken" rather than "this frontend cannot draw
    it". A few hundred pairs cost little and turn a blank box into the
    numbers. The page ignores this key entirely.
    """
    try:
        if spec.get("renderer") == "png":
            return [["(image)", "This chart is drawn as an image — open the "
                                "EDA page to see it."]]
        if kind in ("bar", "line"):
            cats, out = spec["categories"], []
            for ser in spec["series"]:
                multi = len(spec["series"]) > 1
                for c, v in zip(cats, ser["values"]):
                    out.append([f"{c} · {ser['name']}" if multi else c, v])
            return out[:FALLBACK_ROWS]
        if kind == "histogram":
            edges, out = spec["edges"], []
            for ser in spec["series"]:
                multi = len(spec["series"]) > 1
                for i, n in enumerate(ser["counts"]):
                    label = f"{edges[i]:.4g} – {edges[i + 1]:.4g}"
                    out.append([f"{label} · {ser['name']}" if multi else label, n])
            return out[:FALLBACK_ROWS]
        if kind == "pie":
            return [[s["name"], s["value"]] for s in spec["slices"]]
        if kind == "scatter":
            out = []
            for ser in spec["series"]:
                out += [[p[0], p[1]] for p in ser["points"]]
            return out[:FALLBACK_ROWS]
        if kind == "box":
            out = []
            for ser in spec["series"]:
                multi = len(spec["series"]) > 1
                for c, box in zip(spec["categories"], ser["boxes"]):
                    if box:
                        out.append([f"{c} · {ser['name']}" if multi else c,
                                    box[2]])          # the median
            return out[:FALLBACK_ROWS]
        if kind == "corr":
            cols, m, out = spec["columns"], spec["matrix"], []
            for i, a in enumerate(cols):
                for b_i in range(i + 1, len(cols)):
                    out.append([f"{a} × {cols[b_i]}", m[i][b_i]])
            return sorted(out, key=lambda r: -abs(r[1] or 0))[:FALLBACK_ROWS]
    except Exception:                                 # noqa: BLE001
        pass                                          # a fallback that fails
    return []                                         # is not worth a failure


# ── bar ────────────────────────────────────────────────────────────────────

def _bar(c: Chart, x, y, hue, agg, stacked, **_):
    xcol = c.col(x, "the category (x)")
    expr, mlabel = c.measure(y, agg)
    qx = q(xcol)

    if not hue:
        # The top-N query IS the chart: one statement gives the categories,
        # in order, with their values. (The original asked twice.)
        rows = c.rows(
            f"{c.src()}SELECT {qx}, {expr} AS m FROM src "
            f"WHERE {qx} IS NOT NULL GROUP BY 1 "
            f"ORDER BY m DESC, {qx} LIMIT {BAR_CATS}")
        if not rows:
            raise TargetError(f"{xcol!r} has no non-null values to group by.")
        total = int(c.one(f"SELECT count(DISTINCT {qx}) FROM {c.rel}") or 0)
        return {"x_label": xcol, "y_label": mlabel,
                "categories": [str(r[0]) for r in rows],
                "series": [{"name": mlabel,
                            "values": [num(r[1]) for r in rows]}],
                # ECHOED — the original accepted `stacked`, never returned it,
                # and the page's renderer reads it off the spec: the toggle
                # was dead on arrival. One key fixes it.
                "stacked": bool(stacked),
                "basis": c.basis(),
                "meta": {"categories_shown": len(rows),
                         "categories_total": total}}

    hcol = c.col(hue, "the colour (hue)")
    cats, cats_total = c.top_categories(xcol, BAR_CATS, expr)
    if not cats:
        raise TargetError(f"{xcol!r} has no non-null values to group by.")
    hues, hues_total = c.top_categories(hcol, HUE_CATS)
    qh = q(hcol)
    rows = c.rows(
        f"{c.src(c.top_cte('tx', xcol, BAR_CATS, expr), c.top_cte('th', hcol, HUE_CATS))}"
        f"SELECT s.{qx} AS xv, s.{qh} AS hv, {expr} AS m FROM src s "
        f"JOIN tx ON s.{qx} = tx.v JOIN th ON s.{qh} = th.v "
        f"GROUP BY 1, 2")
    grid = {(str(a), str(b)): num(m) for a, b, m in rows}
    return {"x_label": xcol, "y_label": mlabel, "hue_label": hcol,
            "categories": [str(v) for v in cats],
            "series": [{"name": str(h),
                        "values": [grid.get((str(v), str(h))) for v in cats]}
                       for h in hues],
            "stacked": bool(stacked),
            "basis": c.basis(),
            "meta": {"categories_shown": len(cats),
                     "categories_total": cats_total,
                     "hue_shown": len(hues), "hue_total": hues_total}}


# ── line ───────────────────────────────────────────────────────────────────

def _time_expr(c: Chart, xcol: str, granularity: str) -> str:
    qx = q(xcol)
    if not granularity or granularity == "as-is":
        return qx
    if granularity not in GRANULARITIES:
        raise TargetError("granularity must be one of "
                          f"{', '.join(GRANULARITIES)}")
    if c.types[xcol][1] != "date":
        raise TargetError(f"Grouping by {granularity} applies to a date "
                          f"column; {xcol!r} is {c.types[xcol][0]}.")
    return f"date_trunc('{granularity}', {qx})"


def _line(c: Chart, x, y, hue, agg, granularity, **_):
    xcol = c.col(x, "the x axis")
    expr, mlabel = c.measure(y, agg)
    xe = _time_expr(c, xcol, granularity)

    n = int(c.one(f"SELECT count(DISTINCT {xe}) FROM {c.rel}") or 0)
    if n > LINE_POINTS:
        raise TargetError(
            f"{xcol!r} has {n:,} distinct values — too many points for a "
            f"line. Group a date column by month or year, or use a histogram.")

    if not hue:
        rows = c.rows(
            f"{c.src()}SELECT {xe} AS xv, {expr} AS m FROM src "
            f"WHERE {xe} IS NOT NULL GROUP BY 1 ORDER BY 1")
        return {"x_label": xcol, "y_label": mlabel,
                "categories": [str(r[0]) for r in rows],
                "series": [{"name": mlabel,
                            "values": [num(r[1]) for r in rows]}],
                "basis": c.basis(), "meta": {"points": len(rows)}}

    hcol = c.col(hue, "the colour (hue)")
    hues, hues_total = c.top_categories(hcol, HUE_CATS)
    qh = q(hcol)
    rows = c.rows(
        f"{c.src(c.top_cte('th', hcol, HUE_CATS))}"
        f"SELECT {xe.replace(q(xcol), 's.' + q(xcol))} AS xv, s.{qh} AS hv, "
        f"{expr} AS m FROM src s JOIN th ON s.{qh} = th.v "
        f"WHERE {xe.replace(q(xcol), 's.' + q(xcol))} IS NOT NULL "
        f"GROUP BY 1, 2 ORDER BY 1")
    xs, seen = [], set()
    for a, _b, _m in rows:
        if str(a) not in seen:
            seen.add(str(a))
            xs.append(str(a))
    grid = {(str(a), str(b)): num(m) for a, b, m in rows}
    return {"x_label": xcol, "y_label": mlabel, "hue_label": hcol,
            "categories": xs,
            "series": [{"name": str(h),
                        "values": [grid.get((v, str(h))) for v in xs]}
                       for h in hues],
            "basis": c.basis(),
            "meta": {"points": len(xs), "hue_shown": len(hues),
                     "hue_total": hues_total}}


# ── histogram ──────────────────────────────────────────────────────────────

def _bounds(c: Chart, xcol: str) -> tuple[float, float, str]:
    qx, finite = q(xcol), c.finite(xcol)
    rows = c.rows(f"SELECT min({qx}), max({qx}) FROM {c.rel} "
                  f"WHERE {qx} IS NOT NULL{finite}")
    lo, hi = (rows[0] if rows else (None, None))
    if lo is None:
        raise TargetError(f"{xcol!r} has no non-null values.")
    return float(lo), float(hi), finite


def _histogram(c: Chart, x, hue, bins, **_):
    xcol = c.col(x, "the value (x)", numeric=True)
    qx = q(xcol)
    lo, hi, finite = _bounds(c, xcol)
    if hi <= lo:
        raise TargetError(f"{xcol!r} holds a single value ({lo}) — "
                          f"nothing to bin.")
    width = (hi - lo) / bins
    # lo/width are floats this code computed — nothing user-written is
    # interpolated. LEAST folds the exact-maximum row into the last bin
    # instead of giving it a bin of its own.
    bexpr = (f"LEAST(CAST(floor(({qx} - {lo!r}) / {width!r}) AS INT), "
             f"{bins - 1})")
    edges = [lo + i * width for i in range(bins + 1)]

    if not hue:
        rows = c.rows(f"{c.src()}SELECT {bexpr} AS b, count(*) FROM src "
                      f"WHERE {qx} IS NOT NULL{finite} GROUP BY 1")
        counts = [0] * bins
        for b, n in rows:
            if b is not None and 0 <= int(b) < bins:
                counts[int(b)] = int(n)
        return {"x_label": xcol, "y_label": "count", "edges": edges,
                "series": [{"name": xcol, "counts": counts}],
                "basis": c.basis(), "meta": {"bins": bins}}

    hcol = c.col(hue, "the colour (hue)")
    hues, hues_total = c.top_categories(hcol, HUE_CATS)
    qh = q(hcol)
    bexpr_s = bexpr.replace(qx, f"s.{qx}")
    rows = c.rows(
        f"{c.src(c.top_cte('th', hcol, HUE_CATS))}"
        f"SELECT s.{qh} AS hv, {bexpr_s} AS b, count(*) FROM src s "
        f"JOIN th ON s.{qh} = th.v "
        f"WHERE s.{qx} IS NOT NULL{finite.replace(qx, 's.' + qx)} "
        f"GROUP BY 1, 2")
    series = {str(h): [0] * bins for h in hues}
    for h, b, n in rows:
        if b is not None and 0 <= int(b) < bins and str(h) in series:
            series[str(h)][int(b)] = int(n)
    return {"x_label": xcol, "y_label": "count", "hue_label": hcol,
            "edges": edges,
            "series": [{"name": str(h), "counts": series[str(h)]}
                       for h in hues],
            "basis": c.basis(),
            "meta": {"bins": bins, "hue_shown": len(hues),
                     "hue_total": hues_total}}


# ── pie ────────────────────────────────────────────────────────────────────

def _pie(c: Chart, x, y, agg, **_):
    xcol = c.col(x, "the category")
    expr, mlabel = c.measure(y, agg)
    if agg not in ("count", "sum"):
        # A pie states shares of a whole. Averages do not add up to a whole,
        # so a pie of averages is a picture of nothing.
        raise TargetError("A pie shows parts of a whole — use count or sum.")
    qx = q(xcol)
    # Head and tail in ONE statement: the original pulled every group and
    # sliced in Python, which on a high-cardinality column meant shipping
    # thousands of rows to draw eight wedges.
    rows = c.rows(
        f"{c.src()}"
        f", g AS (SELECT CAST({qx} AS VARCHAR) AS v, {expr} AS m FROM src "
        f"        WHERE {qx} IS NOT NULL GROUP BY 1)\n"
        f"SELECT v, m, 0 AS is_other FROM g ORDER BY m DESC, v "
        f"LIMIT {PIE_CATS}")
    if not rows:
        raise TargetError(f"{xcol!r} has no non-null values.")
    total_rows = c.rows(
        f"{c.src()}"
        f", g AS (SELECT CAST({qx} AS VARCHAR) AS v, {expr} AS m FROM src "
        f"        WHERE {qx} IS NOT NULL GROUP BY 1)\n"
        f"SELECT count(*), sum(m) FROM g")
    n_groups, grand = int(total_rows[0][0] or 0), float(total_rows[0][1] or 0)
    head = [{"name": str(v), "value": num(m)} for v, m, _o in rows]
    rest = grand - sum(float(m or 0) for _v, m, _o in rows)
    if n_groups > len(head) and rest > 0:
        head.append({"name": "(other)", "value": num(rest), "other": True})
    return {"x_label": xcol, "y_label": mlabel, "slices": head,
            "basis": c.basis(),
            "meta": {"categories_shown": min(n_groups, PIE_CATS),
                     "categories_total": n_groups}}


# ── scatter ────────────────────────────────────────────────────────────────

def _points(c: Chart, xcol: str, ycol: str, hcol: str | None, cap: int):
    """Row-level points: everything when it fits, an honest sample when it
    does not. Returns (rows, basis)."""
    qx, qy = q(xcol), q(ycol)
    conds = [f"{qx} IS NOT NULL", f"{qy} IS NOT NULL"]
    for col in (xcol, ycol):
        if is_float(c.types[col][0]):
            conds.append(f"isfinite({q(col)})")
    cols = f"{qx}, {qy}" + (f", {q(hcol)}" if hcol else "")
    where = " AND ".join(conds)
    total = int(c.one(f"SELECT count(*) FROM {c.rel} WHERE {where}") or 0)
    if not total:
        raise TargetError("No rows where both columns have values.")
    if total <= cap:
        return (c.rows(f"SELECT {cols} FROM {c.rel} WHERE {where}"),
                f"all {total:,} points")
    rows = c.rows(f"SELECT {cols} FROM (SELECT {cols} FROM {c.rel} "
                  f"WHERE {where}) USING SAMPLE {int(cap)} ROWS")
    return rows, f"{len(rows):,} sampled points of {total:,}"


def _scatter(c: Chart, x, y, hue, **_):
    xcol = c.col(x, "x", numeric=True)
    ycol = c.col(y, "y", numeric=True)
    hcol = c.col(hue, "the colour (hue)") if hue else None
    rows, basis = _points(c, xcol, ycol, hcol, SCATTER_POINTS)

    if not hcol:
        return {"x_label": xcol, "y_label": ycol,
                "series": [{"name": f"{ycol} vs {xcol}",
                            "points": [[num(r[0]), num(r[1])] for r in rows]}],
                "basis": basis, "meta": {}}

    hues, hues_total = c.top_categories(hcol, HUE_CATS)
    shown = {str(h) for h in hues}
    series: dict[str, list] = {str(h): [] for h in hues}
    other: list = []
    for r in rows:
        p = [num(r[0]), num(r[1])]
        key = str(r[2])
        (series[key] if (r[2] is not None and key in shown) else other).append(p)
    out = [{"name": str(h), "points": series[str(h)]}
           for h in hues if series[str(h)]]
    if other:
        out.append({"name": "(other)", "points": other, "other": True})
    return {"x_label": xcol, "y_label": ycol, "hue_label": hcol,
            "series": out, "basis": basis,
            "meta": {"hue_shown": len(hues), "hue_total": hues_total}}


# ── box ────────────────────────────────────────────────────────────────────

def _box(c: Chart, x, y, hue, **_):
    """The Tukey box: whiskers at the last value inside 1.5×IQR of the
    quartiles, everything beyond drawn as points. This is the box plot AS an
    outlier instrument — min/max whiskers quietly swallow the outliers into
    the whisker, which is the opposite of showing them. Fences are computed
    PER BOX, so a category's outliers are judged against that category's own
    spread, not the whole column's."""
    ycol = c.col(y, "the value (y)", numeric=True)
    qy = q(ycol)
    if hue and not x:
        raise TargetError("Pick a category (x) first — hue splits each "
                          "category's box into coloured sub-boxes.")

    conds = [f"{qy} IS NOT NULL{c.finite(ycol)}"]
    ctes, keys, joins = [], [], []
    cats = hues = None
    cats_total = hues_total = None
    xcol = hcol = None
    if x:
        xcol = c.col(x, "the category (x)")
        cap = BOX_CATS_HUED if hue else BOX_CATS
        cats_vals, cats_total = c.top_categories(xcol, cap)
        if not cats_vals:
            raise TargetError(f"{xcol!r} has no non-null values to group by.")
        cats = [str(v) for v in cats_vals]
        ctes.append(c.top_cte("tx", xcol, cap))
        joins.append(f"JOIN tx ON r.{q(xcol)} = tx.v")
        keys.append(f"CAST(r.{q(xcol)} AS VARCHAR)")
    if hue:
        hcol = c.col(hue, "the colour (hue)")
        hues_vals, hues_total = c.top_categories(hcol, BOX_HUES)
        hues = [str(v) for v in hues_vals]
        ctes.append(c.top_cte("th", hcol, BOX_HUES))
        joins.append(f"JOIN th ON r.{q(hcol)} = th.v")
        keys.append(f"CAST(r.{q(hcol)} AS VARCHAR)")

    gsel = "".join(f"{k} AS g{i}, " for i, k in enumerate(keys))
    gcols = ", ".join(f"g{i}" for i in range(len(keys)))
    skey = ", ".join(f"s.g{i}" for i in range(len(keys)))
    join_f = (" JOIN f ON " + " AND ".join(f"s.g{i} = f.g{i}"
                                           for i in range(len(keys)))
              if keys else " CROSS JOIN f")
    # One pipeline of CTEs, used by BOTH statements below: `rel` is the
    # filtered relation, `qt` the per-box quartiles, `f` adds the fences.
    pipeline = c.src(
        *ctes,
        f"""rel AS (
       SELECT {gsel}r.{qy} AS yv FROM src r {' '.join(joins)}
       WHERE {' AND '.join(conds).replace(qy, 'r.' + qy)}
     )""",
        f"""qt AS (
       SELECT {gcols + ', ' if keys else ''}
              percentile_cont(0.25) WITHIN GROUP (ORDER BY yv) AS q1,
              percentile_cont(0.5)  WITHIN GROUP (ORDER BY yv) AS med,
              percentile_cont(0.75) WITHIN GROUP (ORDER BY yv) AS q3,
              count(*) AS n
       FROM rel{(' GROUP BY ' + gcols) if keys else ''}
     )""",
        "f AS (SELECT *, q1 - 1.5 * (q3 - q1) AS lo, "
        "q3 + 1.5 * (q3 - q1) AS hi FROM qt)")

    stats = c.rows(
        f"{pipeline}"
        f"SELECT {skey + ', ' if keys else ''}f.q1, f.med, f.q3, f.n,\n"
        f"       min(CASE WHEN s.yv >= f.lo THEN s.yv END) AS wlo,\n"
        f"       max(CASE WHEN s.yv <= f.hi THEN s.yv END) AS whi,\n"
        f"       count(CASE WHEN s.yv < f.lo OR s.yv > f.hi THEN 1 END) AS n_out\n"
        f"FROM rel s{join_f}\n"
        f"GROUP BY {skey + ', ' if keys else ''}f.q1, f.med, f.q3, f.n")

    # The outlier POINTS, most extreme first, capped per box — the far ones
    # are the ones being looked for, so those are the ones that survive.
    outs = c.rows(
        f"{pipeline}"
        f"SELECT {skey + ', ' if keys else ''}s.yv\n"
        f"FROM rel s{join_f}\n"
        f"WHERE s.yv < f.lo OR s.yv > f.hi\n"
        f"QUALIFY row_number() OVER ("
        f"{('PARTITION BY ' + skey + ' ') if keys else ''}"
        f"ORDER BY GREATEST(f.lo - s.yv, s.yv - f.hi) DESC) "
        f"<= {BOX_OUTLIER_CAP}")

    ng = len(keys)
    smap = {tuple(str(v) for v in r[:ng]): r[ng:] for r in stats}
    idx = {v: i for i, v in enumerate(cats)} if cats else {}
    series = []
    for h in (hues if hues else [None]):
        boxes, counts, ncounts = [], [], []
        for v in (cats or [None]):
            rec = smap.get(tuple(str(k) for k in (v, h) if k is not None))
            if rec is None:
                boxes.append(None)
                counts.append(0)
                ncounts.append(0)
                continue
            q1, med, q3, n, wlo, whi, n_out = rec
            # A degenerate box (everything inside one quartile) can leave a
            # whisker NULL; the quartile itself is then the honest end.
            wlo = q1 if wlo is None else wlo
            whi = q3 if whi is None else whi
            boxes.append([num(float(v_)) for v_ in (wlo, q1, med, q3, whi)])
            counts.append(int(n))
            ncounts.append(int(n_out))
        series.append({"name": h if h is not None else ycol, "boxes": boxes,
                       "counts": counts, "outlier_counts": ncounts,
                       "outliers": []})

    by_name = {s["name"]: s for s in series}
    for r in outs:
        cat = str(r[0]) if xcol else None
        h = str(r[1]) if (xcol and hcol) else None
        s = by_name.get(h if h is not None else ycol)
        if s is not None:
            s["outliers"].append([idx.get(cat, 0), num(float(r[ng]))])

    return {"x_label": xcol or "", "y_label": ycol, "hue_label": hcol,
            "categories": cats or [ycol], "series": series,
            "whiskers": "tukey_1_5_iqr", "basis": c.basis(),
            "meta": {"categories_shown": len(cats) if cats else 1,
                     "categories_total": cats_total if cats else 1,
                     "hue_shown": len(hues) if hues else None,
                     "hue_total": hues_total,
                     "outliers_total": sum(sum(s["outlier_counts"])
                                           for s in series),
                     "outliers_shown": sum(len(s["outliers"]) for s in series),
                     "outlier_cap": BOX_OUTLIER_CAP}}


# ── correlation ────────────────────────────────────────────────────────────

def _corr(c: Chart, **_):
    numeric_all = [col for col, (duck, _s) in c.types.items()
                   if is_numeric(duck)]
    numeric = numeric_all[:CORR_COLS]
    if len(numeric) < 2:
        raise TargetError("Correlation needs at least two numeric columns.")
    # A float column may hold infinity, and DuckDB's corr() raises outright
    # on it ("STDDEV_POP for X is out of range") — one poisoned value would
    # take down the whole matrix rather than one cell. Non-finite values
    # become NULL, which corr() already ignores pairwise. (The in-app
    # original had this hole; a real table with an inf broke the chart.)
    def safe(col: str) -> str:
        return (f"CASE WHEN isfinite({q(col)}) THEN {q(col)} END"
                if is_float(c.types[col][0]) else q(col))

    exprs, pairs = [], []
    for i, a in enumerate(numeric):
        for b in numeric[i + 1:]:
            exprs.append(f"corr({safe(a)}, {safe(b)})")
            pairs.append((a, b))
    row = c.rows(f"SELECT {', '.join(exprs)} FROM {c.rel}")[0]
    n = len(numeric)
    m = [[1.0 if i == j else None for j in range(n)] for i in range(n)]
    idx = {col: i for i, col in enumerate(numeric)}
    for (a, b), v in zip(pairs, row):
        v = num(float(v)) if v is not None else None
        m[idx[a]][idx[b]] = m[idx[b]][idx[a]] = v
    return {"columns": numeric, "matrix": m, "basis": c.basis(),
            "meta": {"numeric_total": len(numeric_all)}}


_KINDS = {"bar": _bar, "line": _line, "histogram": _histogram, "pie": _pie,
          "scatter": _scatter, "box": _box, "corr": _corr}
