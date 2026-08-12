# -*- coding: utf-8 -*-
"""EDA for the NL2SQL app — as a plugin.

Descriptive statistics, null-pattern analysis and charts for one relation:
a table, or any SELECT somebody pastes. Everything is computed IN the
database over every row, and nothing here calls a model — EDA is pure
computation: free, instant, and identical every run.

The point of this package: the same capability used to live inside the app
(32 lines of it inside core files). Here it needs **none** — installing the
package is the whole integration. Two ways to use it:

  * **Actions** — declared inputs, `Result` out. They work on any core that
    honours the module contract, including cores this package has never met.
  * **A page** (`nl2sql.pages` entry point) — the interactive explorer, for
    cores that serve plugin pages. A bonus, never a requirement: without it
    every action still works.

Everything reaches the database through `ctx.query` — one guardrail-checked
read-only statement at a time. That constraint is not a limitation to work
around; it is what makes this package safe to install anywhere.
"""
from nl2sql_engine.modules import Action, Input, Module, Result

from . import plain
from .profile import compute
from .targets import TargetError, resolve

__version__ = "1.0.0"

# Every chart kind the `chart` action can draw. The first seven are drawn by
# the browser from numbers this module aggregates; the last four are images
# this module draws itself. (Kinds land in phases: see charts.py.)
CHART_KINDS = ["bar", "line", "histogram", "pie", "scatter", "box", "corr",
               "hexbin", "kde", "ridgeline", "null_matrix"]

# The two inputs every action takes. Declared with an empty default so BOTH
# arrive filled: the contract's missing-input gate passes, and the action
# decides which one wins (a non-empty query beats a dropdown that always has
# something selected).
TARGET_INPUTS = {
    "table": Input(kind="table", label="Table", default="",
                   help="The table to analyse. Ignored if you paste a query."),
    "sql": Input(kind="text", label="…or a SELECT query", default="",
                 help="Any read-only query. Wins over the table above."),
}


def _target(ctx, table, sql):
    """Resolve, or raise TargetError — the actions turn that into a Result."""
    return resolve(ctx, table or "", sql or "")


def _guard(fn):
    """A person's mistake is an ANSWER, not a traceback. Anything a person
    can fix comes back as an error Result with the reason in a sentence; the
    contract already wraps genuine bugs, so this only changes the tone of the
    survivable half."""
    def wrapped(ctx, **kw):
        try:
            return fn(ctx, **kw)
        except TargetError as exc:
            return Result.error(str(exc))
    wrapped.__name__ = getattr(fn, "__name__", "action")
    return wrapped


# ── the actions ────────────────────────────────────────────────────────────

@_guard
def run_tables(ctx):
    return plain.tables(ctx)


@_guard
def run_profile(ctx, table="", sql=""):
    """The rich profile, as a spec this plugin's page draws. A frontend that
    does not know the dialect shows the data — never a crash."""
    data = compute(ctx, _target(ctx, table, sql))
    # `rows` is the same content as [column, non-null] pairs, for a frontend
    # that knows only the simple chart shape — without it such a renderer
    # draws an empty table, which reads as a broken module rather than an
    # undrawable dialect. The EDA page ignores the key.
    spec = {"type": "eda/profile",
            "rows": [[c["name"], c["count"]] for c in data["columns"]],
            **data}
    # Constructed directly rather than through Result.chart(), which takes no
    # note — the field exists on the dataclass (same order on every core that
    # honours the contract), and a note is what tells a person WHY a chart is
    # showing as numbers here.
    return Result("chart", spec, f"Profile — {data['target']['label']}",
                  "The full profile draws on the EDA page. For a plain table "
                  "here, use “Profile (as a table)”.")


@_guard
def run_profile_table(ctx, table="", sql=""):
    return plain.profile_table(ctx, _target(ctx, table, sql))


@_guard
def run_nulls(ctx, table="", sql=""):
    return plain.nulls(ctx, _target(ctx, table, sql))


@_guard
def run_top_values(ctx, table="", sql="", column=""):
    if not (column or "").strip():
        return Result.error("Choose a column.")
    return plain.top_values(ctx, _target(ctx, table, sql), column.strip())


@_guard
def run_chart(ctx, table="", sql="", kind="bar", x="", y="", hue="",
              agg="count", bins=30, granularity="as-is", stacked=False):
    """Any of the chart kinds, as a spec. The page draws it; a frontend that
    does not know the dialect shows the numbers."""
    from . import charts
    target = _target(ctx, table, sql)
    spec = charts.draw(ctx, target, kind=(kind or "bar").strip(),
                       x=(x or "").strip() or None,
                       y=(y or "").strip() or None,
                       hue=(hue or "").strip() or None,
                       agg=(agg or "count").strip(), bins=bins,
                       granularity=(granularity or "as-is").strip(),
                       stacked=bool(stacked))
    drawn = "as an image" if spec.get("renderer") == "png" else "interactively"
    return Result("chart", spec, f"{kind} — {target['label']}",
                  f"{spec['basis']}. Drawn {drawn} on the EDA page; the "
                  f"numbers are shown here for any other frontend.")


MODULE = Module(
    name="eda",
    label="🔬 EDA",
    description="Explore a table or any query: descriptive statistics, exact "
                "null patterns, value distributions and charts — computed in "
                "the database, over every row.",
    requires_core=">=1.0,<2.0",
    actions=[
        Action(name="tables", label="List tables",
               help="Every table in this connection, with its row count.",
               inputs={}, run=run_tables),
        Action(name="profile", label="Profile (full)",
               help="Everything worth knowing before the first chart. Rich "
                    "output — best seen on the EDA page.",
               inputs=dict(TARGET_INPUTS), run=run_profile),
        Action(name="profile-table", label="Profile (as a table)",
               help="The per-column statistics as a plain table.",
               inputs=dict(TARGET_INPUTS), run=run_profile_table),
        Action(name="nulls", label="Null analysis",
               help="Exact null counts per column, plus the columns whose "
                    "blanks travel together.",
               inputs=dict(TARGET_INPUTS), run=run_nulls),
        Action(name="top-values", label="Top values",
               help="The most frequent values of one column, with shares.",
               inputs={**TARGET_INPUTS,
                       "column": Input(kind="column", label="Column",
                                       default="", of_table="table")},
               run=run_top_values),
        Action(name="chart", label="Chart",
               help="Draw one chart. Which inputs matter depends on the "
                    "kind: bar/line need x (and y unless counting), "
                    "histogram and scatter need numeric columns, corr needs "
                    "none, box needs y.",
               inputs={
                   **TARGET_INPUTS,
                   "kind": Input(kind="choice", label="Chart kind",
                                 default="bar", choices=list(CHART_KINDS)),
                   "x": Input(kind="column", label="X / category",
                              default="", of_table="table"),
                   "y": Input(kind="column", label="Y / value",
                              default="", of_table="table"),
                   "hue": Input(kind="column", label="Colour by (hue)",
                                default="", of_table="table"),
                   "agg": Input(kind="choice", label="Aggregate",
                                default="count",
                                choices=["count", "sum", "avg", "min", "max"]),
                   "bins": Input(kind="number", label="Bins (histogram)",
                                 default=30),
                   "granularity": Input(kind="choice", label="Date grouping",
                                        default="as-is",
                                        choices=["as-is", "year", "month",
                                                 "week", "day"]),
                   "stacked": Input(kind="bool", label="Stacked bars",
                                    default=False),
               },
               run=run_chart),
    ],
)
