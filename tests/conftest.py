# -*- coding: utf-8 -*-
"""One small database with every shape the profile has to handle:
integers, floats including NaN, DECIMAL, text (high and low cardinality),
dates, booleans, an all-null column, and two columns whose nulls travel
together."""
from __future__ import annotations

import pytest

import nl2sql_engine
from nl2sql_engine.modules import Context


@pytest.fixture()
def ctx(tmp_path) -> Context:
    import duckdb

    path = tmp_path / "eda_test.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""
        CREATE TABLE t (
            n        INTEGER,      -- 1..10, one NULL
            f        DOUBLE,       -- includes a NaN and an inf
            price    DECIMAL(9,2),
            grade    VARCHAR,      -- low cardinality: A/B/C
            name     VARCHAR,      -- high cardinality
            when_    DATE,
            flag     BOOLEAN,
            empty    VARCHAR,      -- entirely NULL
            twin_a   INTEGER,      -- twin_a and twin_b are NULL together
            twin_b   INTEGER
        )""")
    rows = []
    for i in range(1, 11):
        rows.append((
            i if i != 10 else None,
            float(i) if i < 9 else (float("nan") if i == 9 else float("inf")),
            i * 1.5,
            "ABC"[i % 3],
            f"name-{i}",
            f"2026-01-{i:02d}",
            i % 2 == 0,
            None,
            None if i > 7 else i,       # 3 nulls
            None if i > 7 else i * 2,   # the same 3 rows
        ))
    con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute("CREATE TABLE empty_table (x INTEGER)")
    # A column with enough distinct values to earn a histogram rather than a
    # top-values list (the profile switches at 12 distinct).
    con.execute("CREATE TABLE wide AS SELECT i AS v FROM range(1, 101) t(i)")
    con.close()

    nl2sql_engine.configure(data_dir=tmp_path)   # never touch the real one
    return Context(db_path=str(path))
