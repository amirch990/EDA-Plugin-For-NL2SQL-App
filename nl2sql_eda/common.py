# -*- coding: utf-8 -*-
"""Small shared pieces: identifier quoting, JSON safety, type names.

Nothing here talks to a database or to the engine — which is why every other
file in the package can import it freely.
"""
from __future__ import annotations

import math
from decimal import Decimal

# Mini-histograms in the profile. Enough bars to show a shape, few enough
# that forty of them on one page stay readable.
PROFILE_BINS = 15
# Top values listed per column. Eight covers a code column (A/B/C/D…)
# completely and truncates a name column honestly.
TOP_K = 8
# Null-pattern analysis looks at this many nullable columns at most: the mask
# GROUP BY is exponential in columns in the worst case, and a pattern over 30
# columns is unreadable anyway.
MAX_NULL_COLS = 12
# How many distinct null-masks are fetched. More than this and the pairwise
# numbers are computed over the top patterns only — and say so.
MAX_MASKS = 200


def q(ident: str) -> str:
    """One identifier, made safe to sit inside double quotes.

    The ONLY way a name reaches SQL in this package. There are no bound
    parameters available through the module contract, so anything that is not
    a quoted identifier is a number this code computed itself.
    """
    return '"' + str(ident).replace('"', '""') + '"'


def num(v):
    """A value made JSON-safe. NaN and infinity become None rather than
    reaching the browser: json.dumps writes them as bare NaN, which is not
    JSON, and fetch().json() then fails on the WHOLE response because one
    cell of one column was 0/0."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    return v


def scalar(v):
    """A value for a cell a person reads: JSON-safe, and dates/times as text
    rather than objects a JSON encoder has to guess about."""
    v = num(v)
    if v is None or isinstance(v, (int, float, bool, str)):
        return v
    return str(v)


_TYPE_MAP = {
    "BOOLEAN": "bool",
    "TINYINT": "integer", "SMALLINT": "integer", "INTEGER": "integer",
    "BIGINT": "integer", "HUGEINT": "integer",
    "UTINYINT": "integer", "USMALLINT": "integer", "UINTEGER": "integer",
    "UBIGINT": "integer",
    "FLOAT": "number", "DOUBLE": "number", "REAL": "number",
    "DATE": "date", "TIMESTAMP": "date", "TIMESTAMP WITH TIME ZONE": "date",
    "TIME": "date", "INTERVAL": "text",
}


def simple_type(duck_type) -> str:
    """The five families a frontend actually branches on."""
    name = str(duck_type).upper()
    if name.startswith("DECIMAL"):
        return "number"
    return _TYPE_MAP.get(name, "text")


def is_numeric(duck_type) -> bool:
    return simple_type(duck_type) in ("integer", "number")


# Types that do not answer min/max/count(DISTINCT) sensibly (or at all).
# Asking anyway turns one exotic column into a failed profile for the whole
# table, which is a bad trade for a statistic nobody reads on a LIST column.
_COMPLEX = ("LIST", "STRUCT", "MAP", "UNION", "BLOB", "ARRAY", "[]")


def is_orderable(duck_type) -> bool:
    name = str(duck_type).upper()
    return not any(k in name for k in _COMPLEX)


def is_float(duck_type) -> bool:
    return str(duck_type).upper() in ("FLOAT", "DOUBLE", "REAL")
