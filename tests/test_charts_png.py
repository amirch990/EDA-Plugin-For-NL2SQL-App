# -*- coding: utf-8 -*-
"""The four server-drawn kinds. A PNG cannot be asserted pixel by pixel, so
what is checked is: it is a real PNG, of a plausible size, from the right
data, and every refusal is a sentence."""
from __future__ import annotations

import base64

import pytest

from nl2sql_eda.charts import draw
from nl2sql_eda.targets import TargetError, resolve

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_of(spec) -> bytes:
    assert spec["renderer"] == "png" and spec["type"] == "png"
    raw = base64.b64decode(spec["png_base64"])
    assert raw.startswith(PNG_MAGIC), "not a PNG"
    assert len(raw) > 2000, "suspiciously small image"
    return raw


def chart(ctx, kind, table="t", **kw):
    return draw(ctx, resolve(ctx, table=table), kind, **kw)


# ── each kind draws ────────────────────────────────────────────────────────

def test_hexbin_draws(ctx):
    s = draw(ctx, resolve(ctx, sql="SELECT i AS a, i % 17 AS b "
                                   "FROM range(1, 3000) t(i)"),
             "hexbin", x="a", y="b")
    png_of(s)
    assert s["kind"] == "hexbin" and "points" in s["basis"]


def test_kde_draws(ctx):
    s = draw(ctx, resolve(ctx, table="wide"), "kde", x="v")
    png_of(s)
    assert "all 100 values" in s["basis"]


def test_kde_with_hue_reports_its_groups(ctx):
    s = draw(ctx, resolve(ctx, sql="""
        SELECT 'a' AS g, i AS v FROM range(1, 60) t(i)
        UNION ALL SELECT 'b', i * 2 FROM range(1, 60) t(i)"""),
             "kde", x="v", hue="g")
    png_of(s)
    assert s["meta"]["hue_shown"] == 2 and s["meta"]["hue_total"] == 2


def test_ridgeline_draws_one_ridge_per_category(ctx):
    s = draw(ctx, resolve(ctx, sql="""
        SELECT 'a' AS g, i AS v FROM range(1, 60) t(i)
        UNION ALL SELECT 'b', i * 2 FROM range(1, 60) t(i)
        UNION ALL SELECT 'c', i + 30 FROM range(1, 60) t(i)"""),
             "ridgeline", x="v", hue="g")
    png_of(s)
    assert s["meta"]["hue_shown"] == 3 and s["meta"]["hue_total"] == 3


def test_null_matrix_draws_and_says_what_it_drew(ctx):
    s = chart(ctx, "null_matrix")
    png_of(s)
    assert "stored order" in s["basis"] and "10 rows" in s["basis"]


def test_the_null_matrix_is_the_whole_relation_not_one_column(ctx):
    """Ten columns wide: the picture's job is the pattern ACROSS columns."""
    wide = png_of(chart(ctx, "null_matrix"))
    narrow = png_of(draw(ctx, resolve(ctx, sql="SELECT n FROM t"),
                         "null_matrix"))
    assert len(wide) != len(narrow)


# ── refusals ───────────────────────────────────────────────────────────────

def test_ridgeline_requires_categories(ctx):
    with pytest.raises(TargetError, match="the categories"):
        draw(ctx, resolve(ctx, table="wide"), "ridgeline", x="v")


def test_kde_refuses_a_single_valued_column(ctx):
    with pytest.raises(TargetError, match="single value"):
        draw(ctx, resolve(ctx, sql="SELECT 1 AS one FROM t"), "kde", x="one")


def test_kde_refuses_a_text_column(ctx):
    with pytest.raises(TargetError, match="numeric"):
        chart(ctx, "kde", x="grade")


def test_a_column_with_no_values_says_so(ctx):
    """An entirely-NULL column reports type "unknown" (typeof reads a
    VALUE's type). "needs a numeric column; 'v' is unknown" would puzzle
    anyone — the real fact is that there is nothing in it."""
    with pytest.raises(TargetError, match="no values at all"):
        draw(ctx, resolve(ctx, sql="SELECT CAST(NULL AS INTEGER) AS v "
                                   "FROM range(1, 10) t(i)"), "kde", x="v")
    with pytest.raises(TargetError, match="no values at all"):
        chart(ctx, "kde", x="empty")           # the fixture's all-null column


# ── the dispatcher knows about them ────────────────────────────────────────

def test_unknown_kind_lists_the_png_kinds_too(ctx):
    with pytest.raises(TargetError) as e:
        chart(ctx, "sunburst")
    for kind in ("hexbin", "kde", "ridgeline", "null_matrix"):
        assert kind in str(e.value)


def test_a_png_spec_names_itself_generically(ctx):
    """`type: "png"` on purpose: a frontend that knows nothing about this
    plugin's dialect can still show the image."""
    s = chart(ctx, "null_matrix")
    assert s["type"] == "png" and s["kind"] == "null_matrix"
    assert s["png_base64"]
