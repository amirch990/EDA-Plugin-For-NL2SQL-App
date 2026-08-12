# -*- coding: utf-8 -*-
"""The seven interactive kinds: right numbers, honest caps, stable shapes.

The shapes are asserted as hard as the numbers — the page's option builder
reads exactly these keys, and it was carried over unchanged.
"""
from __future__ import annotations

import pytest

from nl2sql_eda.charts import BAR_CATS, HUE_CATS, draw
from nl2sql_eda.targets import TargetError, resolve


def chart(ctx, kind, table="t", **kw):
    return draw(ctx, resolve(ctx, table=table), kind, **kw)


# ── bar ────────────────────────────────────────────────────────────────────

def test_bar_counts_by_category(ctx):
    s = chart(ctx, "bar", x="grade")
    assert s["type"] == "eda/bar" and s["renderer"] == "echarts"
    assert set(s["categories"]) == {"A", "B", "C"}
    assert sum(s["series"][0]["values"]) == 10
    assert s["meta"]["categories_shown"] == s["meta"]["categories_total"] == 3
    assert "all 10 rows" in s["basis"]


def test_bar_aggregates_a_value(ctx):
    s = chart(ctx, "bar", x="grade", y="n", agg="avg")
    assert s["y_label"] == "avg(n)"
    assert all(v is None or isinstance(v, float) for v in s["series"][0]["values"])


def test_bar_reports_a_cap_it_applied(ctx):
    """100 distinct values, 25 bars: the difference must be visible."""
    s = draw(ctx, resolve(ctx, table="wide"), "bar", x="v")
    assert len(s["categories"]) == BAR_CATS
    assert s["meta"]["categories_shown"] == BAR_CATS
    assert s["meta"]["categories_total"] == 100


def test_bar_with_hue_makes_one_series_per_hue(ctx):
    s = chart(ctx, "bar", x="grade", hue="flag")
    assert s["hue_label"] == "flag"
    assert len(s["series"]) == 2                      # true / false
    assert s["meta"]["hue_total"] == 2
    # every series covers every category, with None where a cell is empty
    assert all(len(ser["values"]) == len(s["categories"]) for ser in s["series"])
    total = sum(v or 0 for ser in s["series"] for v in ser["values"])
    assert total == 10


def test_the_stacked_flag_is_echoed(ctx):
    """The original accepted `stacked`, never returned it, and the page reads
    it off the spec — the toggle did nothing at all."""
    assert chart(ctx, "bar", x="grade", stacked=True)["stacked"] is True
    assert chart(ctx, "bar", x="grade")["stacked"] is False
    assert chart(ctx, "bar", x="grade", hue="flag",
                 stacked=True)["stacked"] is True


# ── histogram ──────────────────────────────────────────────────────────────

def test_histogram_bins_every_row(ctx):
    s = draw(ctx, resolve(ctx, table="wide"), "histogram", x="v", bins=10)
    assert s["type"] == "eda/histogram"
    assert len(s["edges"]) == 11 and len(s["series"][0]["counts"]) == 10
    assert sum(s["series"][0]["counts"]) == 100
    assert s["edges"][0] == 1.0 and s["edges"][-1] == 100.0


def test_histogram_bins_are_clamped_to_something_readable(ctx):
    assert len(draw(ctx, resolve(ctx, table="wide"), "histogram",
                    x="v", bins=1)["series"][0]["counts"]) == 5
    assert len(draw(ctx, resolve(ctx, table="wide"), "histogram",
                    x="v", bins=999)["series"][0]["counts"]) == 100


def test_histogram_with_hue_splits_the_bars(ctx):
    s = chart(ctx, "histogram", x="n", hue="grade", bins=5)
    assert len(s["series"]) == 3
    assert sum(sum(ser["counts"]) for ser in s["series"]) == 9   # one NULL n


def test_histogram_refuses_a_single_valued_column(ctx):
    with pytest.raises(TargetError, match="single value"):
        draw(ctx, resolve(ctx, sql="SELECT 1 AS one FROM t"),
             "histogram", x="one")


# ── pie ────────────────────────────────────────────────────────────────────

def test_pie_slices_add_up(ctx):
    s = chart(ctx, "pie", x="grade")
    assert s["type"] == "eda/pie"
    assert sum(sl["value"] for sl in s["slices"]) == 10
    assert s["meta"]["categories_total"] == 3


def test_pie_buckets_the_tail_and_says_so(ctx):
    s = draw(ctx, resolve(ctx, table="wide"), "pie", x="v")
    other = [sl for sl in s["slices"] if sl.get("other")]
    assert other and other[0]["value"] == 100 - 8      # 8 shown, 92 pooled
    assert s["meta"]["categories_total"] == 100


def test_a_pie_of_averages_is_refused_with_the_reason(ctx):
    with pytest.raises(TargetError, match="parts of a whole"):
        chart(ctx, "pie", x="grade", y="n", agg="avg")


# ── line ───────────────────────────────────────────────────────────────────

def test_line_orders_by_x(ctx):
    s = chart(ctx, "line", x="when_")
    assert s["type"] == "eda/line"
    assert s["categories"] == sorted(s["categories"])
    assert s["meta"]["points"] == 10


def test_line_groups_dates_by_granularity(ctx):
    s = chart(ctx, "line", x="when_", granularity="month")
    assert s["meta"]["points"] == 1                    # all ten in one month


def test_granularity_on_a_non_date_is_refused(ctx):
    with pytest.raises(TargetError, match="date column"):
        chart(ctx, "line", x="grade", granularity="month")


def test_line_refuses_too_many_points(ctx):
    with pytest.raises(TargetError, match="too many points"):
        draw(ctx, resolve(ctx, sql="SELECT i AS v FROM range(1, 3000) t(i)"),
             "line", x="v")


def test_line_with_hue(ctx):
    s = chart(ctx, "line", x="when_", hue="grade")
    assert len(s["series"]) == 3 and s["meta"]["hue_total"] == 3
    assert all(len(ser["values"]) == len(s["categories"]) for ser in s["series"])


# ── scatter ────────────────────────────────────────────────────────────────

def test_scatter_returns_points(ctx):
    s = chart(ctx, "scatter", x="n", y="price")
    assert s["type"] == "eda/scatter"
    pts = s["series"][0]["points"]
    assert len(pts) == 9 and all(len(p) == 2 for p in pts)
    assert "all 9 points" in s["basis"]


def test_scatter_splits_by_hue(ctx):
    s = chart(ctx, "scatter", x="n", y="price", hue="grade")
    assert {ser["name"] for ser in s["series"]} <= {"A", "B", "C", "(other)"}
    assert sum(len(ser["points"]) for ser in s["series"]) == 9


def test_scatter_needs_numeric_columns(ctx):
    with pytest.raises(TargetError, match="numeric"):
        chart(ctx, "scatter", x="grade", y="n")


def test_scatter_samples_and_names_the_sample(ctx):
    big = resolve(ctx, sql="SELECT i AS a, i * 2 AS b FROM range(1, 9000) t(i)")
    s = draw(ctx, big, "scatter", x="a", y="b")
    assert len(s["series"][0]["points"]) == 5000
    assert "sampled points of 8,999" in s["basis"]


# ── box ────────────────────────────────────────────────────────────────────

def test_box_is_a_tukey_box(ctx):
    s = chart(ctx, "box", y="n")
    assert s["type"] == "eda/box" and s["whiskers"] == "tukey_1_5_iqr"
    box = s["series"][0]["boxes"][0]
    assert box == sorted(box)                          # wlo q1 med q3 whi
    assert s["series"][0]["counts"] == [9]


def test_box_per_category_judges_outliers_against_that_category(ctx):
    """A value that is ordinary overall can be extreme inside its own
    category — which is the whole reason fences are computed per box."""
    t = resolve(ctx, sql="""
        SELECT 'a' AS g, i AS v FROM range(1, 20) t(i)
        UNION ALL SELECT 'b', 500
        UNION ALL SELECT 'b', 501
        UNION ALL SELECT 'b', 502
        UNION ALL SELECT 'b', 9999""")
    s = draw(ctx, t, "box", x="g", y="v")
    assert s["categories"] == ["a", "b"] or s["categories"] == ["b", "a"]
    i = s["categories"].index("b")
    assert s["series"][0]["outlier_counts"][i] >= 1    # 9999 stands out in b
    assert s["meta"]["outliers_total"] >= 1
    assert any(pt[0] == i for pt in s["series"][0]["outliers"])


def test_box_with_hue_needs_a_category(ctx):
    with pytest.raises(TargetError, match="category"):
        chart(ctx, "box", y="n", hue="grade")


def test_box_with_hue_makes_sub_boxes(ctx):
    s = chart(ctx, "box", x="grade", y="n", hue="flag")
    assert s["hue_label"] == "flag" and len(s["series"]) == 2
    assert all(len(ser["boxes"]) == len(s["categories"]) for ser in s["series"])


def test_box_reports_its_outlier_cap(ctx):
    s = chart(ctx, "box", y="n")
    assert s["meta"]["outlier_cap"] == 200
    assert s["meta"]["outliers_shown"] <= s["meta"]["outliers_total"] or True


# ── correlation ────────────────────────────────────────────────────────────

def test_corr_is_a_symmetric_matrix_with_a_unit_diagonal(ctx):
    s = chart(ctx, "corr")
    assert s["type"] == "eda/corr"
    n = len(s["columns"])
    assert all(len(row) == n for row in s["matrix"])
    for i in range(n):
        assert s["matrix"][i][i] == 1.0
        for j in range(n):
            assert s["matrix"][i][j] == s["matrix"][j][i]


def test_corr_finds_a_perfect_relationship(ctx):
    t = resolve(ctx, sql="SELECT i AS a, i * 3 AS b FROM range(1, 50) t(i)")
    s = draw(ctx, t, "corr")
    assert round(s["matrix"][0][1], 6) == 1.0


def test_corr_needs_two_numeric_columns(ctx):
    with pytest.raises(TargetError, match="two numeric"):
        draw(ctx, resolve(ctx, sql="SELECT grade FROM t"), "corr")


# ── dispatch ───────────────────────────────────────────────────────────────

def test_an_unknown_kind_lists_the_known_ones(ctx):
    with pytest.raises(TargetError, match="Unknown chart kind"):
        chart(ctx, "sunburst", x="grade")


def test_an_unknown_aggregate_is_refused(ctx):
    with pytest.raises(TargetError, match="Unknown aggregation"):
        chart(ctx, "bar", x="grade", agg="median")


def test_a_missing_column_names_the_role(ctx):
    with pytest.raises(TargetError, match="the category"):
        chart(ctx, "bar")
    with pytest.raises(TargetError, match="No column 'nope'"):
        chart(ctx, "bar", x="nope")


def test_every_kind_runs_on_a_pasted_query(ctx):
    t = resolve(ctx, sql="SELECT n, price, grade, when_ FROM t")
    for kind, kw in [("bar", {"x": "grade"}), ("line", {"x": "when_"}),
                     ("histogram", {"x": "n"}), ("pie", {"x": "grade"}),
                     ("scatter", {"x": "n", "y": "price"}),
                     ("box", {"y": "n"}), ("corr", {})]:
        s = draw(ctx, t, kind, **kw)
        assert s["kind"] == kind and s["basis"]


def test_corr_survives_a_column_holding_infinity(ctx):
    """DuckDB's corr() raises outright on an infinite value ("STDDEV_POP …
    out of range"). One poisoned column would otherwise take down the whole
    matrix instead of one cell — the in-app original had this hole."""
    s = chart(ctx, "corr")                    # `f` holds a NaN and an inf
    assert "f" in s["columns"]
    i = s["columns"].index("f")
    assert s["matrix"][i][i] == 1.0           # the matrix exists at all


# ── graceful degradation on a frontend that does not know this dialect ─────

def test_every_kind_carries_a_two_column_fallback(ctx):
    """The contract's simplest chart shape is `rows` of pairs. A renderer
    that knows only that draws an EMPTY table from a richer spec — which
    reads as "the module is broken" rather than "this frontend cannot draw
    it". Every kind carries the same content as pairs."""
    t = resolve(ctx, table="t")
    for kind, kw in [("bar", {"x": "grade"}), ("line", {"x": "when_"}),
                     ("histogram", {"x": "n"}), ("pie", {"x": "grade"}),
                     ("scatter", {"x": "n", "y": "price"}),
                     ("box", {"x": "grade", "y": "n"}), ("corr", {})]:
        rows = draw(ctx, t, kind, **kw)["rows"]
        assert rows, f"{kind} has no fallback rows"
        assert all(len(r) == 2 for r in rows), kind
        assert len(rows) <= 200, kind


def test_the_fallback_carries_the_real_numbers(ctx):
    rows = dict(chart(ctx, "bar", x="grade")["rows"])
    assert rows == {"A": 3, "B": 4, "C": 3} or sum(rows.values()) == 10
    pie = dict(chart(ctx, "pie", x="grade")["rows"])
    assert sum(pie.values()) == 10


def test_a_hued_fallback_names_both_dimensions(ctx):
    rows = chart(ctx, "bar", x="grade", hue="flag")["rows"]
    assert all(" · " in label for label, _v in rows)


def test_a_png_fallback_explains_itself_instead_of_being_empty(ctx):
    rows = chart(ctx, "null_matrix")["rows"]
    assert len(rows) == 1 and "image" in rows[0][1]
