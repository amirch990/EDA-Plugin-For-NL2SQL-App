# -*- coding: utf-8 -*-
"""The actions as a frontend calls them: run(ctx, **inputs) -> Result.

Every failure a person can cause must come back as a Result, never a raise —
that is what keeps a mistake a message on a page instead of a traceback in a
terminal nobody is reading.
"""
from __future__ import annotations

from nl2sql_engine.modules import Registry

from nl2sql_eda import MODULE


def run(ctx, action, **inputs):
    """Through the real Registry, so default-filling and validation are the
    core's, exactly as they will be in the app."""
    reg = Registry()
    reg.modules.append(MODULE)
    return reg.run("eda", action, ctx, inputs)


def test_tables_lists_with_row_counts(ctx):
    r = run(ctx, "tables")
    assert r.kind == "table"
    rows = {name: n for name, n in r.data["rows"]}
    assert rows["t"] == 10 and rows["empty_table"] == 0 and rows["wide"] == 100


def test_profile_returns_a_spec_the_page_can_draw(ctx):
    r = run(ctx, "profile", table="t")
    assert r.kind == "chart"
    assert r.data["type"] == "eda/profile"
    assert r.data["row_count"] == 10 and len(r.data["columns"]) == 10


def test_profile_table_is_readable_anywhere(ctx):
    r = run(ctx, "profile-table", table="t")
    assert r.kind == "table"
    assert r.data["columns"][:4] == ["column", "type", "non-null", "nulls"]
    assert len(r.data["rows"]) == 10
    assert "exact" in r.note


def test_nulls_tells_the_story_in_its_note(ctx):
    r = run(ctx, "nulls", table="t")
    assert r.kind == "table"
    assert "null together in 100%" in r.note


def test_nulls_says_so_plainly_when_there_are_none(ctx):
    r = run(ctx, "nulls", sql="SELECT grade FROM t")
    assert r.kind == "markdown" and "No nulls anywhere" in r.data


def test_top_values_reports_its_cap(ctx):
    r = run(ctx, "top-values", table="t", column="grade")
    assert r.kind == "table"
    assert r.data["rows"][0][1] > 0
    assert "all 3 distinct values shown" in r.note


# ── the survivable failures ────────────────────────────────────────────────

def test_no_target_is_a_message(ctx):
    r = run(ctx, "profile")
    assert r.kind == "error" and "Choose a table" in r.data


def test_a_refused_query_is_a_message(ctx):
    r = run(ctx, "profile", sql="DROP TABLE t")
    assert r.kind == "error"
    assert "DROP" in r.data and "only reads" in r.data


def test_an_unknown_column_names_the_alternatives(ctx):
    r = run(ctx, "top-values", table="t", column="nope")
    assert r.kind == "error" and "columns are" in r.data


def test_a_missing_column_asks_for_one(ctx):
    r = run(ctx, "top-values", table="t")
    assert r.kind == "error" and "Choose a column" in r.data


def test_a_query_target_works_through_the_registry(ctx):
    r = run(ctx, "profile-table", sql="SELECT n, grade FROM t WHERE n <= 5")
    assert r.kind == "table" and len(r.data["rows"]) == 2
    assert "5 rows" in r.note


def test_rich_results_explain_themselves_on_a_plain_frontend(ctx):
    """A frontend that cannot draw this dialect shows the note and the
    fallback rows — never an empty box with no explanation."""
    r = run(ctx, "profile", table="t")
    assert r.note and "EDA page" in r.note
    assert r.data["rows"] and all(len(x) == 2 for x in r.data["rows"])

    c = run(ctx, "chart", table="t", kind="bar", x="grade")
    assert c.note and "aggregated over all 10 rows" in c.note
    assert dict(c.data["rows"])

    p = run(ctx, "chart", table="t", kind="null_matrix")
    assert "as an image" in p.note
