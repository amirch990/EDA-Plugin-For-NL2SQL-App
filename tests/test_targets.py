# -*- coding: utf-8 -*-
"""Targets: a table or a pasted query, resolved into one relation."""
from __future__ import annotations

import pytest

from nl2sql_eda.targets import TargetError, resolve


def test_a_table_resolves_with_its_types(ctx):
    t = resolve(ctx, table="t")
    assert t["kind"] == "table" and t["label"] == "t"
    types = dict(t["columns"])
    assert types["n"] == "INTEGER" and types["grade"] == "VARCHAR"
    assert types["when_"] == "DATE" and types["flag"] == "BOOLEAN"
    # An all-null column has no VALUE to read a type from — say so honestly.
    assert types["empty"] == "unknown"


def test_a_query_resolves_and_is_wrapped(ctx):
    t = resolve(ctx, sql="SELECT n, grade FROM t WHERE n > 5")
    assert t["kind"] == "sql"
    assert t["relation"].startswith("(") and t["relation"].endswith(") AS q")
    assert [c for c, _ in t["columns"]] == ["n", "grade"]


def test_a_query_wins_over_a_table(ctx):
    t = resolve(ctx, table="t", sql="SELECT 1 AS only_this")
    assert t["kind"] == "sql" and [c for c, _ in t["columns"]] == ["only_this"]


def test_neither_is_a_question_not_a_crash(ctx):
    with pytest.raises(TargetError, match="Choose a table"):
        resolve(ctx)


def test_an_unknown_table_says_so(ctx):
    with pytest.raises(TargetError, match="No table named"):
        resolve(ctx, table="nope")


def test_a_write_is_refused_in_the_app_s_own_words(ctx):
    """Composed into a subquery, `DELETE FROM t` would pass the core's
    guardrail (the composed statement starts with SELECT) and die as a
    syntax error. The shape check says the real thing first."""
    with pytest.raises(TargetError) as e:
        resolve(ctx, sql="DELETE FROM t")
    assert "DELETE" in str(e.value) and "only reads" in str(e.value)


def test_the_shape_check_sees_past_comments_and_parens(ctx):
    with pytest.raises(TargetError, match="DROP"):
        resolve(ctx, sql="-- harmless\n  DROP TABLE t")
    assert resolve(ctx, sql="(SELECT n FROM t)")["kind"] == "sql"


def test_a_second_statement_is_still_the_core_s_job(ctx):
    """The security boundary is the core's guardrail, not the shape check:
    this one LOOKS like a SELECT and must still be refused."""
    with pytest.raises(TargetError) as e:
        resolve(ctx, sql="SELECT 1) AS q; DROP TABLE t; --")
    assert "statement" in str(e.value).lower() or "cannot run" in str(e.value)


def test_a_broken_query_reports_the_database_s_own_words(ctx):
    with pytest.raises(TargetError) as e:
        resolve(ctx, sql="SELECT amout FROM t")     # deliberate typo
    assert "cannot run" in str(e.value) and "amout" in str(e.value)


def test_duplicate_column_names_arrive_usable(ctx):
    """DuckDB renames the second one itself (n, n_1), so the guard in
    _from_sql is a safety net for engines that do not — what matters is that
    the columns come back distinct and the target resolves."""
    names = [c for c, _ in resolve(ctx, sql="SELECT n, n FROM t")["columns"]]
    assert len(set(names)) == len(names) == 2


def test_a_trailing_semicolon_is_fine(ctx):
    assert resolve(ctx, sql="SELECT n FROM t;")["kind"] == "sql"


def test_the_label_is_truncated_but_readable(ctx):
    long_sql = "SELECT n, grade, name, price FROM t WHERE " + \
               " AND ".join(["n > 0"] * 40)
    t = resolve(ctx, sql=long_sql)
    assert len(t["label"]) <= 121 and t["label"].endswith("…")
