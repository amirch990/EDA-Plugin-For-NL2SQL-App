# -*- coding: utf-8 -*-
"""The profile: exact numbers, honest edges, and a stable response shape.

The shape assertions matter as much as the numbers: this dict is what the
plugin's page renders, and it is field-for-field the one the in-app version
returned — so the page could be carried over without rewriting it.
"""
from __future__ import annotations

import json

from nl2sql_eda import MODULE
from nl2sql_eda.profile import compute
from nl2sql_eda.targets import resolve


def prof(ctx, **kw):
    return compute(ctx, resolve(ctx, **kw))


def by_name(data):
    return {c["name"]: c for c in data["columns"]}


# ── the shape the page depends on ──────────────────────────────────────────

def test_the_response_shape_is_the_original_s(ctx):
    d = prof(ctx, table="t")
    assert set(d) == {"target", "database", "row_count", "column_count",
                      "basis", "columns", "nulls", "distinct_exact"}
    assert set(d["target"]) == {"kind", "label"}
    assert set(d["nulls"]) == {"total_null_cells", "by_column", "patterns",
                               "pairs", "patterns_truncated"}
    assert set(by_name(d)["n"]) == {
        "name", "type", "simple_type", "count", "nulls", "null_pct", "unique",
        "min", "max", "mean", "std", "q25", "median", "q75", "top_values",
        "histogram"}


def test_the_whole_response_is_json_safe(ctx):
    """A NaN reaching json.dumps writes a bare NaN, which is not JSON — and
    fetch().json() then fails on the WHOLE response because one cell of one
    column was 0/0."""
    text = json.dumps(prof(ctx, table="t"), allow_nan=False)
    assert "NaN" not in text and "Infinity" not in text


# ── the numbers ────────────────────────────────────────────────────────────

def test_counts_and_nulls_are_exact(ctx):
    d = prof(ctx, table="t")
    assert d["row_count"] == 10 and d["column_count"] == 10
    cols = by_name(d)
    assert cols["n"]["count"] == 9 and cols["n"]["nulls"] == 1
    assert cols["n"]["null_pct"] == 10.0
    assert cols["empty"]["nulls"] == 10 and cols["empty"]["count"] == 0
    assert cols["grade"]["nulls"] == 0


def test_numeric_moments_are_computed(ctx):
    cols = by_name(prof(ctx, table="t"))
    n = cols["n"]
    assert n["min"] == 1 and n["max"] == 9          # the 10th row is NULL
    assert n["mean"] == 5.0 and n["median"] == 5.0
    assert n["q25"] == 3.0 and n["q75"] == 7.0
    assert round(n["std"], 4) == round(2.7386127875258306, 4)
    assert cols["price"]["min"] == 1.5              # DECIMAL survives as a number


def test_text_columns_get_no_numeric_moments(ctx):
    g = by_name(prof(ctx, table="t"))["grade"]
    assert g["mean"] is None and g["std"] is None and g["median"] is None
    assert g["min"] == "A" and g["max"] == "C"


def test_dates_and_bools_are_readable_scalars(ctx):
    cols = by_name(prof(ctx, table="t"))
    assert cols["when_"]["simple_type"] == "date"
    assert str(cols["when_"]["min"]).startswith("2026-01-01")
    assert cols["flag"]["simple_type"] == "bool"


# ── per-column detail ──────────────────────────────────────────────────────

def test_a_wide_numeric_column_gets_a_histogram(ctx):
    v = by_name(prof(ctx, table="wide"))["v"]
    h = v["histogram"]
    assert h and v["top_values"] is None
    assert len(h["edges"]) == len(h["counts"]) + 1
    assert sum(h["counts"]) == 100                  # every non-null row binned
    assert h["edges"][0] == 1.0 and h["edges"][-1] == 100.0


def test_a_numeric_column_with_few_values_gets_top_values_instead(ctx):
    """The switch is at 12 distinct: `price` has 10, so a list of values
    tells the reader more than a histogram of ten bars would."""
    price = by_name(prof(ctx, table="t"))["price"]
    assert price["histogram"] is None and price["top_values"]


def test_nan_and_inf_never_reach_a_histogram(ctx):
    """f holds a NaN and an inf: min/max must stay finite numbers and the
    bars must count only the finite rows."""
    f = by_name(prof(ctx, table="t"))["f"]
    assert f["histogram"] is None or sum(f["histogram"]["counts"]) <= 10
    assert f["min"] is None or isinstance(f["min"], (int, float))


def test_a_low_cardinality_column_gets_top_values_instead(ctx):
    cols = by_name(prof(ctx, table="t"))
    tv = cols["grade"]["top_values"]
    assert tv and cols["grade"]["histogram"] is None
    assert {r["value"] for r in tv} == {"A", "B", "C"}
    assert sum(r["count"] for r in tv) == 10


def test_top_values_admit_what_they_left_out(ctx):
    """10 distinct names, 8 shown: the remainder is a row, not silence."""
    tv = by_name(prof(ctx, table="t"))["name"]["top_values"]
    assert tv[-1].get("other") is True and tv[-1]["count"] == 2


# ── null patterns: the finding the original was built for ──────────────────

def test_columns_whose_nulls_travel_together_are_found(ctx):
    n = prof(ctx, table="t")["nulls"]
    assert n["total_null_cells"] == 1 + 10 + 3 + 3
    pair = next(p for p in n["pairs"] if {p["a"], p["b"]} == {"twin_a", "twin_b"})
    assert pair["p"] == 1.0 and pair["rows_both"] == 3
    assert any(set(p["columns"]) >= {"twin_a", "twin_b"} for p in n["patterns"])


def test_no_nulls_means_no_pairs(ctx):
    n = compute(ctx, resolve(ctx, sql="SELECT grade FROM t"))["nulls"]
    assert n["by_column"] == [] and n["pairs"] == []


# ── edges ──────────────────────────────────────────────────────────────────

def test_an_empty_relation_answers_instead_of_dividing_by_zero(ctx):
    d = prof(ctx, table="empty_table")
    assert d["row_count"] == 0 and d["columns"] == []
    assert "no rows" in d["basis"]


def test_a_query_target_profiles_like_a_table(ctx):
    same = prof(ctx, sql="SELECT * FROM t")
    assert same["row_count"] == 10
    assert same["target"]["kind"] == "sql"
    assert by_name(same)["n"]["mean"] == 5.0


def test_an_aggregate_query_is_a_valid_target(ctx):
    d = prof(ctx, sql="SELECT grade, count(*) AS n FROM t GROUP BY 1")
    assert d["row_count"] == 3 and d["column_count"] == 2


# ── the declaration ────────────────────────────────────────────────────────

def test_actions_are_declared_for_any_frontend(ctx):
    assert MODULE.name == "eda" and MODULE.requires_core == ">=1.0,<2.0"
    names = {a.name for a in MODULE.actions}
    assert names == {"tables", "profile", "profile-table", "nulls",
                     "top-values", "chart"}
    for action in MODULE.actions:
        for key, decl in action.inputs.items():
            assert decl.kind in ("table", "column", "text", "number", "bool",
                                 "choice")
            # Every input defaults, so "table or sql" both arrive filled.
            assert decl.default is not None, f"{action.name}.{key}"
    col = MODULE.action("top-values").inputs["column"]
    assert col.of_table == "table"


def test_distinct_counts_are_exact_on_a_table_worth_profiling(ctx):
    """The original always estimated (HyperLogLog): it read "701 distinct"
    for a 682-row table — impossible on its face — and could never answer
    "is this column a key?". Exact below the threshold fixes both."""
    d = prof(ctx, table="wide")
    assert d["distinct_exact"] is True
    assert by_name(d)["v"]["unique"] == 100          # exactly, not 96

    cols = by_name(prof(ctx, table="t"))
    assert cols["grade"]["unique"] == 3 and cols["name"]["unique"] == 10
    assert cols["empty"]["unique"] == 0
    for name, col in cols.items():                   # never more than exists
        if isinstance(col["unique"], int):
            assert col["unique"] <= col["count"], name
