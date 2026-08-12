# -*- coding: utf-8 -*-
"""Everything worth knowing about a relation before the first chart.

Per-column descriptive statistics, EXACT null counts, a mini-histogram per
numeric column, top values per categorical one, and the null-pattern analysis
that says whether blanks travel together — every number computed in the
database, over every row.

How this differs from the in-app original, and why each change is a gain:

  * DuckDB's ``SUMMARIZE`` is not a SELECT, so a module cannot run it. The
    statistics are hand-written aggregates instead — which incidentally FIXES
    a wart: SUMMARIZE returns min/max/avg as VARCHAR whatever the column was,
    and the original carried a `_maybe_number` helper to guess them back into
    numbers. Asking for `min(c)` returns the column's own type. No guessing.
  * Everything goes through ``ctx.query`` — one guardrail-checked read-only
    statement at a time. No cursor, no parameters, no second statement.

Cost: three scans plus roughly one statement per interesting column (~40-50
on a 40-column table). They are in-process calls against an embedded engine,
and profiling a million-row table still answers in about a second.
"""
from __future__ import annotations

import math

from .common import (MAX_MASKS, MAX_NULL_COLS, PROFILE_BINS, TOP_K, is_float,
                     is_numeric, is_orderable, num, q, scalar, simple_type)

# Below this many rows, distinct counts are computed EXACTLY; above it they
# are estimated. Chosen so that every interactive profile in the course's own
# databases is exact, and a million-row table still answers in about a second.
EXACT_DISTINCT_ROWS = 200_000


def compute(ctx, target: dict, detail: bool = True) -> dict:
    """The profile of one resolved target. `detail=False` skips the
    per-column histograms and top values — the plain-table actions do not
    show them, and they are most of the statements."""
    rel, cols = target["relation"], target["columns"]
    names = [c for c, _ in cols]

    total = int(_one(ctx, f"SELECT count(*) FROM {rel}") or 0)
    if not total:
        return {"target": {"kind": target["kind"], "label": target["label"]},
                "database": "", "row_count": 0, "column_count": len(cols),
                "basis": "the relation has no rows", "columns": [],
                "nulls": {"total_null_cells": 0, "by_column": [],
                          "patterns": [], "pairs": [],
                          "patterns_truncated": False}}

    # Pass 1 — non-null counts, exactly. SUMMARIZE's null_percentage is
    # rounded to two decimals, and "0.00%" hides the three null rows somebody
    # is hunting for in a million. The difference between "no nulls" and
    # "almost none" is precisely what a null analysis exists to state.
    counts = _scan(ctx, rel, names, lambda c, t: f"count({q(c)})", 0)

    # Pass 2 — distinct/min/max, for the columns that can answer.
    #
    # EXACT below the threshold, estimated above it. The original always
    # estimated (HyperLogLog, via SUMMARIZE) because exact distinct counts on
    # every column of a wide table are the one genuinely slow thing here. But
    # an estimate cannot answer the question people actually bring to this
    # column — "is this a key?" — and on the 682-row table it read 701, which
    # is impossible on its face. So: exact where exact is cheap, which is
    # most tables anyone profiles interactively, and honest labelling either
    # way.
    exact = total <= EXACT_DISTINCT_ROWS
    counter = "count(DISTINCT {})" if exact else "approx_count_distinct({})"
    uniques = _scan(ctx, rel, names,
                    lambda c, t: (counter.format(q(c))
                                  if is_orderable(t) else "NULL"), None,
                    types=cols)
    lohi = _scan(ctx, rel, names,
                 lambda c, t: (f"min({q(c)}), max({q(c)})"
                               if is_orderable(t) else "NULL, NULL"), None,
                 types=cols, width=2)

    # Pass 3 — the numeric moments, for numeric columns only. A text column
    # never meets avg() this way, so one CHAR column cannot fail the scan.
    nums = [c for c, t in cols if is_numeric(t)]
    moments = _scan(ctx, rel, nums,
                    lambda c, t: (f"avg({q(c)}), stddev_samp({q(c)}), "
                                  f"quantile_cont({q(c)}, [0.25, 0.5, 0.75])"),
                    None, width=3) if nums else {}

    columns = []
    for cname, duck in cols:
        non_null = int(counts.get(cname) or 0)
        nulls = total - non_null
        simple = simple_type(duck)
        lo, hi = (lohi.get(cname) or (None, None))
        avg, std, quants = (moments.get(cname) or (None, None, None))
        quants = list(quants) if isinstance(quants, (list, tuple)) else [None] * 3
        entry = {
            "name": cname, "type": duck, "simple_type": simple,
            "count": non_null, "nulls": nulls,
            "null_pct": round(100.0 * nulls / total, 2),
            # Approximate by construction (HyperLogLog) and labelled so in
            # the UI — exact distinct counts on every column of a wide table
            # are the one thing here that would actually be slow. CAPPED at
            # the non-null count: the estimate can overshoot, and "701
            # distinct values in 682 rows" is impossible on its face, which
            # costs the reader more trust than the approximation saves time.
            "unique": _capped(uniques.get(cname), non_null),
            "min": scalar(lo), "max": scalar(hi),
            "mean": num(avg), "std": num(std),
            "q25": num(quants[0]), "median": num(quants[1]),
            "q75": num(quants[2]),
            "top_values": None, "histogram": None,
        }
        if detail and non_null:
            low_card = isinstance(entry["unique"], int) and entry["unique"] <= 12
            if is_numeric(duck) and not low_card:
                entry["histogram"] = _histogram(ctx, rel, cname, duck, lo, hi)
            elif simple in ("text", "bool") or (is_numeric(duck) and low_card):
                entry["top_values"] = _top_values(ctx, rel, cname, non_null)
        columns.append(entry)

    nulls_by_col = {c["name"]: c["nulls"] for c in columns}
    return {
        "target": {"kind": target["kind"], "label": target["label"]},
        "database": "",                       # the frontend knows its own name
        "row_count": total, "column_count": len(cols),
        # Additive key: a frontend that predates it ignores it, one that
        # knows it can stop calling exact numbers "approximate".
        "distinct_exact": exact,
        "basis": f"aggregated over all {total:,} rows",
        "columns": columns,
        "nulls": null_analysis(ctx, rel, nulls_by_col, total),
    }


# ── the scans ──────────────────────────────────────────────────────────────

def _one(ctx, sql):
    _, rows = ctx.query(sql)
    return rows[0][0] if rows else None


def _capped(unique, non_null: int):
    """An estimate that cannot exceed what it counts."""
    unique = num(unique)
    if isinstance(unique, (int, float)) and not isinstance(unique, bool):
        return min(int(unique), non_null)
    return unique


def _scan(ctx, rel: str, names: list[str], expr, missing, types=None,
          width: int = 1) -> dict:
    """One statement holding `width` expressions per column — and, if that
    statement fails, the same expressions asked one column at a time.

    The fallback is what keeps a profile robust: an exotic column type that
    refuses an aggregate costs its own statistics and nothing else, instead
    of failing the table for every other column.
    """
    if not names:
        return {}
    tmap = dict(types or [])
    parts = [expr(c, tmap.get(c, "")) for c in names]
    try:
        _, rows = ctx.query(f"SELECT {', '.join(parts)} FROM {rel}")
        row = list(rows[0]) if rows else []
        if len(row) == len(names) * width:
            return _unpack(names, row, width)
    except Exception:                             # noqa: BLE001 — fall back below
        pass
    out = {}
    for i, c in enumerate(names):
        try:
            _, rows = ctx.query(f"SELECT {parts[i]} FROM {rel}")
            row = list(rows[0]) if rows else []
            out[c] = (tuple(row) if width > 1 else row[0]) if row else missing
        except Exception:                         # noqa: BLE001 — this column only
            out[c] = missing
    return out


def _unpack(names: list[str], row: list, width: int) -> dict:
    if width == 1:
        return {c: row[i] for i, c in enumerate(names)}
    return {c: tuple(row[i * width:(i + 1) * width])
            for i, c in enumerate(names)}


# ── per-column detail ──────────────────────────────────────────────────────

def _histogram(ctx, rel: str, cname: str, duck: str, lo, hi,
               bins: int = PROFILE_BINS) -> dict | None:
    """Equal-width bins, counted by the database over every non-null row."""
    try:
        lo, hi = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    qc = q(cname)
    # A float column can hold NaN, and floor(NaN) lands in no bin — the row
    # count and the bar total would then disagree for no visible reason.
    finite = f" AND isfinite({qc})" if is_float(duck) else ""
    try:
        if hi <= lo:
            # One value (or one value and nulls): a single bar says it plainly.
            n = _one(ctx, f"SELECT count(*) FROM {rel} "
                          f"WHERE {qc} IS NOT NULL{finite}")
            return {"edges": [lo, hi], "counts": [int(n or 0)]}
        width = (hi - lo) / bins
        # lo/width are floats this function computed — nothing user-written is
        # interpolated. LEAST folds the exact-maximum row into the last bin
        # instead of giving it a bin of its own.
        _, rows = ctx.query(
            f"SELECT LEAST(CAST(floor(({qc} - {lo!r}) / {width!r}) AS INT), "
            f"{bins - 1}) AS b, count(*) FROM {rel} "
            f"WHERE {qc} IS NOT NULL{finite} GROUP BY 1 ORDER BY 1")
    except Exception:                             # noqa: BLE001 — no bars, no crash
        return None
    counts = [0] * bins
    for b, n in rows:
        if b is not None and 0 <= int(b) < bins:
            counts[int(b)] = int(n)
    return {"edges": [lo + i * width for i in range(bins + 1)],
            "counts": counts}


def _top_values(ctx, rel: str, cname: str, non_null: int,
                k: int = TOP_K) -> list[dict] | None:
    """The K most frequent values, and how much of the column they cover —
    'A/B/C/D and that is everything' and 'eight names out of forty thousand'
    are different facts, and the share is what separates them."""
    qc = q(cname)
    try:
        _, rows = ctx.query(
            f"SELECT CAST({qc} AS VARCHAR) AS v, count(*) AS n FROM {rel} "
            f"WHERE {qc} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 "
            f"LIMIT {int(k)}")
    except Exception:                             # noqa: BLE001
        return None
    out = [{"value": v, "count": int(n),
            "pct": round(100.0 * n / non_null, 1) if non_null else 0.0}
           for v, n in rows]
    covered = sum(o["count"] for o in out)
    if covered < non_null:
        rest = non_null - covered
        out.append({"value": None, "count": rest,
                    "pct": round(100.0 * rest / non_null, 1), "other": True})
    return out


# ── where the nulls are, and whether they travel together ──────────────────

def null_analysis(ctx, rel: str, nulls_by_col: dict, total: int) -> dict:
    """Columns rarely go missing independently: one unfilled form section is
    five columns null in the SAME rows, and knowing that changes what a fix
    is. The joint distribution over null-masks answers it in one query, and
    the pairwise numbers are derived from those masks in Python rather than
    asked as sixty-six separate aggregates."""
    by_column = sorted(
        ({"column": c, "nulls": n,
          "pct": round(100.0 * n / total, 2) if total else 0.0}
         for c, n in nulls_by_col.items() if n > 0),
        key=lambda e: e["nulls"], reverse=True)
    out = {"total_null_cells": sum(nulls_by_col.values()),
           "by_column": by_column, "patterns": [], "pairs": [],
           "patterns_truncated": False}
    if not by_column or not total:
        return out

    null_cols = [e["column"] for e in by_column[:MAX_NULL_COLS]]
    masks_sql = ", ".join(f"({q(c)} IS NULL)" for c in null_cols)
    try:
        _, rows = ctx.query(
            f"SELECT {masks_sql}, count(*) FROM {rel} "
            f"GROUP BY ALL ORDER BY count(*) DESC LIMIT {MAX_MASKS}")
    except Exception:                             # noqa: BLE001 — counts still stand
        return out
    out["patterns_truncated"] = len(rows) >= MAX_MASKS

    masks = [(tuple(bool(v) for v in r[:-1]), int(r[-1])) for r in rows]
    out["patterns"] = [
        {"columns": [c for c, isnull in zip(null_cols, mask) if isnull],
         "rows": n, "pct": round(100.0 * n / total, 2)}
        for mask, n in masks if any(mask)][:10]

    # P(B is null | A is null), read straight off the mask distribution.
    for i, a in enumerate(null_cols):
        a_total = sum(n for mask, n in masks if mask[i])
        if not a_total:
            continue
        for j, b in enumerate(null_cols):
            if i == j:
                continue
            both = sum(n for mask, n in masks if mask[i] and mask[j])
            p = both / a_total
            if p >= 0.5:
                out["pairs"].append({"a": a, "b": b, "p": round(p, 3),
                                     "rows_both": both})
    out["pairs"] = sorted(out["pairs"], key=lambda e: e["p"],
                          reverse=True)[:12]
    return out
