# -*- coding: utf-8 -*-
"""A TARGET: a table, or SQL somebody pasted, resolved into one relation.

The whole feature stands on this one abstraction. Once resolved, tables and
queries are the same thing, and nothing downstream has to care which it got —
every computation just puts `relation` after FROM.

What changed from the original, and why it is an improvement rather than a
compromise: the in-app version asked DuckDB `DESCRIBE SELECT * FROM (…)` to
validate a pasted query and learn its column types. A module has
`ctx.query`, which runs ONE guardrail-checked SELECT — DESCRIBE is not one.
So validation became `SELECT * FROM (…) LIMIT 0` (which also yields the
column names) and types come from a `typeof()` pass. The result is the same
information through a door that any core will open — which is what makes
this package installable on cores we do not control.
"""
from __future__ import annotations

import re

from .common import q


class TargetError(Exception):
    """Something the person asking can fix, phrased for them. Actions turn
    this into a Result.error — never a traceback."""


def resolve(ctx, table: str = "", sql: str = "") -> dict:
    """-> {"relation", "columns": [(name, duck_type)], "kind", "label"}.

    A non-empty `sql` wins over `table`: every form that offers both has a
    table already selected in its dropdown, so a person who typed a query
    means the query.
    """
    sql = (sql or "").strip().rstrip(";").strip()
    table = (table or "").strip()

    if sql:
        relation, names = _from_sql(ctx, sql)
        label = " ".join(sql.split())
        label = label[:120] + "…" if len(label) > 120 else label
        kind = "sql"
    elif table:
        relation, names = _from_table(ctx, table)
        label, kind = table, "table"
    else:
        raise TargetError("Choose a table, or paste a SELECT query.")

    return {"relation": relation, "columns": _types(ctx, relation, names),
            "kind": kind, "label": label}


def _from_table(ctx, table: str) -> tuple[str, list[str]]:
    if table not in ctx.tables():
        raise TargetError(f"No table named {table!r} in this connection.")
    cols = ctx.columns(table)
    if not cols:
        raise TargetError(f"{table!r} has no columns.")
    return q(table), cols


_LEADING_NOISE = re.compile(r"^(\s+|--[^\n]*\n?|/\*.*?\*/|\()+", re.S)


def _first_word(sql: str) -> str:
    """The statement keyword, past any leading comments and parentheses."""
    head = _LEADING_NOISE.sub("", sql)
    m = re.match(r"[a-zA-Z_]+", head)
    return (m.group(0) if m else "").upper()


def _shape_check(sql: str) -> None:
    """A READABLE refusal for the obvious case — not the security boundary.

    The boundary is the core's own guardrail, which runs inside ctx.query on
    the composed statement and catches what matters (a second statement, a
    file-reading function). But composed, a pasted `DELETE FROM t` becomes
    `SELECT * FROM (DELETE FROM t) AS q` — which starts with SELECT, passes
    the guardrail, and dies as "Parser Error: syntax error at or near FROM".
    That is a true statement and a useless one. This says the real thing
    instead, in the app's own words.
    """
    word = _first_word(sql)
    if word in ("SELECT", "WITH", ""):
        return
    raise TargetError(
        f"`{word}` is not allowed — EDA only reads. Paste a SELECT "
        f"(or a WITH … SELECT) query.")


def _from_sql(ctx, sql: str) -> tuple[str, list[str]]:
    """Validate a pasted query by running it for NO rows.

    LIMIT 0 costs nothing, proves the query parses and runs, and hands back
    its column names — and the core's guardrail (single read-only statement)
    runs inside ctx.query before any of that. A query that cannot run reports
    the database's own first line: "no such column: amout" is the answer, and
    rewording it would only make it vaguer.
    """
    _shape_check(sql)
    relation = f"({sql}) AS q"
    try:
        names, _ = ctx.query(f"SELECT * FROM {relation} LIMIT 0")
    except ValueError as exc:                     # the guardrail refused it
        raise TargetError(str(exc)) from None
    except Exception as exc:                      # noqa: BLE001 — the DB refused it
        first = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
        raise TargetError(f"The query cannot run: {first}") from None
    if not names:
        raise TargetError("That query returns no columns.")
    if len(set(names)) != len(names):
        # DuckDB renames duplicates itself (n, n_1), so this is a safety net
        # for an engine that does not — reached, it would otherwise show two
        # identical columns with different numbers.
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise TargetError(
            "That query has two columns with the same name "
            f"({', '.join(dupes)}) — give one an alias with AS.")
    return relation, list(names)


def _types(ctx, relation: str, names: list[str]) -> list[tuple[str, str]]:
    """The DuckDB type of every column, in one scan.

    `typeof()` reads a VALUE's type, so a column that is entirely NULL has no
    type to report — "unknown" is the honest answer there, and it lands in
    the text family, which is where an all-null column belongs anyway.
    """
    exprs = ", ".join(f"max(typeof({q(n)})) FILTER (WHERE {q(n)} IS NOT NULL)"
                      for n in names)
    try:
        _, rows = ctx.query(f"SELECT {exprs} FROM {relation}")
        got = list(rows[0]) if rows else [None] * len(names)
    except Exception:                             # noqa: BLE001 — types are a bonus
        got = [None] * len(names)
    return [(n, got[i] or "unknown") for i, n in enumerate(names)]
