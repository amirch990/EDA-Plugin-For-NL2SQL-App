# -*- coding: utf-8 -*-
"""The same numbers, as plain tables.

The rich actions return specs for this plugin's own page to draw. These four
return `Result.table` / `Result.markdown`, so they are useful on ANY
frontend — the app's generic Modules page, a core that has no pages at all,
or a future official frontend. They are the descendants of the `eda-profile`
module, which this package replaces; the capability moved in and gained
pasted-SQL targets on the way.
"""
from __future__ import annotations

from nl2sql_engine.modules import Result

from .common import TOP_K, q, scalar
from .profile import compute


def tables(ctx) -> Result:
    """Every table in the connection, with its row count."""
    names = ctx.tables()
    if not names:
        return Result.table([], ["table", "rows"], title="Tables",
                            note="This connection has no tables.")
    counts: dict[str, int | None] = {}
    # One statement per chunk rather than per table: a connection with a
    # hundred tables is one or two round trips instead of a hundred.
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        union = " UNION ALL ".join(
            f"SELECT {_lit(t)} AS t, count(*) AS n FROM {q(t)}" for t in chunk)
        try:
            _, rows = ctx.query(union)
            counts.update({str(t): int(n) for t, n in rows})
        except Exception:                         # noqa: BLE001 — one at a time
            for t in chunk:
                try:
                    _, rows = ctx.query(f"SELECT count(*) FROM {q(t)}")
                    counts[t] = int(rows[0][0])
                except Exception:                 # noqa: BLE001 — a view may refuse
                    counts[t] = None
    return Result.table([[t, counts.get(t)] for t in names],
                        ["table", "rows"], title="Tables",
                        note=f"{len(names)} table(s) in this connection.")


def profile_table(ctx, target: dict) -> Result:
    """The per-column statistics, one row per column."""
    data = compute(ctx, target, detail=False)
    if not data["row_count"]:
        return Result.markdown(f"**{target['label']}** has no rows.",
                               title="Profile")
    rows = [[c["name"], c["type"], c["count"], c["nulls"], c["null_pct"],
             c["unique"], c["min"], c["max"], c["mean"], c["std"],
             c["median"]]
            for c in data["columns"]]
    return Result.table(
        rows, ["column", "type", "non-null", "nulls", "null %", "distinct",
               "min", "max", "mean", "std", "median"],
        title=f"Profile — {target['label']}",
        note=f"{data['row_count']:,} rows; every statistic computed over all "
             f"of them. Null counts are exact; distinct counts are "
             + ("exact too."
                if data.get("distinct_exact")
                else "estimated (HyperLogLog) above "
                     "200,000 rows."))


def nulls(ctx, target: dict) -> Result:
    """Exact null counts, and the columns whose blanks travel together."""
    data = compute(ctx, target, detail=False)
    if not data["row_count"]:
        return Result.markdown(f"**{target['label']}** has no rows.",
                               title="Nulls")
    n = data["nulls"]
    if not n["by_column"]:
        return Result.markdown(
            f"**No nulls anywhere** — {data['column_count']} columns, "
            f"{data['row_count']:,} rows, every cell filled.", title="Nulls")
    note = (f"{data['row_count']:,} rows; "
            f"{data['column_count'] - len(n['by_column'])} column(s) fully "
            f"filled.")
    if n["pairs"]:
        # The pairs list is directional — P(b null | a null) and P(a null |
        # b null) are different facts and the page shows both. A three-line
        # summary is not the place for both halves of one story, so the note
        # keeps the stronger direction per pair and moves on to the next
        # finding.
        seen, stories = set(), []
        for p in n["pairs"]:
            key = frozenset((p["a"], p["b"]))
            if key in seen:
                continue
            seen.add(key)
            stories.append(f"{p['a']} & {p['b']} null together in "
                           f"{p['p']:.0%} of {p['a']}'s null rows")
            if len(stories) == 3:
                break
        note += " Patterns: " + "; ".join(stories) + "."
    if n["patterns_truncated"]:
        note += " (many distinct null patterns — the top ones only)"
    return Result.table([[e["column"], e["nulls"], e["pct"]]
                         for e in n["by_column"]],
                        ["column", "nulls", "null %"],
                        title=f"Nulls — {target['label']}", note=note)


def top_values(ctx, target: dict, column: str) -> Result:
    """The most frequent values of one column, with shares."""
    names = [c for c, _ in target["columns"]]
    if column not in names:
        return Result.error(
            f"No column named {column!r} in {target['label']} — "
            f"columns are: {', '.join(names[:20])}")
    rel, qc = target["relation"], q(column)
    _, head = ctx.query(f"SELECT count({qc}), count(DISTINCT {qc}) FROM {rel}")
    non_null, distinct = int(head[0][0] or 0), int(head[0][1] or 0)
    if not non_null:
        return Result.markdown(f"`{column}` has no non-null values.",
                               title=f"Top values — {column}")
    _, rows = ctx.query(
        f"SELECT CAST({qc} AS VARCHAR) AS v, count(*) AS n FROM {rel} "
        f"WHERE {qc} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 "
        f"LIMIT {TOP_K * 2}")
    out = [[scalar(v), int(n), round(100.0 * n / non_null, 2)] for v, n in rows]
    shown = len(out)
    note = (f"{shown} of {distinct:,} distinct values shown"
            if distinct > shown else
            f"all {distinct:,} distinct values shown")
    return Result.table(out, ["value", "rows", "share %"],
                        title=f"Top values — {column}",
                        note=f"{note}, shares of {non_null:,} non-null rows.")


def _lit(text: str) -> str:
    """A string literal. Only ever used on names the DATABASE gave us
    (ctx.tables()), never on anything a person typed — but quoted properly
    regardless, because that is the habit that stays correct."""
    return "'" + str(text).replace("'", "''") + "'"
