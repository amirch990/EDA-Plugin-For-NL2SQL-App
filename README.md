# nl2sql-eda

Exploratory data analysis for the NL2SQL app — **as a plugin**. Descriptive
statistics, exact null patterns, value distributions and charts for any table
or any SELECT you paste, computed in the database over every row.

The same capability used to live inside the app, and adding it meant editing
core files. This package needs **zero lines inside the app**: install it,
restart, and it is there. Uninstall it, and it is gone.

## Install

It goes into the **app's** environment, not a new one — a plugin lives inside
the app it extends.

```powershell
git clone https://github.com/amirch990/nl2sql-eda.git
cd <app-folder>
.\.venv\Scripts\python -m pip install ..\nl2sql-eda
```

With `uv`: `uv pip install -p <app-folder>\.venv ..\nl2sql-eda`.
Add `-e` if you intend to edit it — then a restart is all a change needs.

Restart the app. Two things appear, and **nothing in the app changes**
(`git status` there stays empty):

- the module and its actions on the 🧩 **Modules** page;
- on a core that serves plugin pages (`nl2sql-core` ≥ 1.6), a **🔬 EDA**
  entry in the sidebar that opens the full explorer **in its own tab**.

`pip uninstall nl2sql-eda`, restart, and both are gone. Installing IS the
registration; there is no list inside the app to edit.

The app this extends: **[nl2sql-app-closed-core](https://github.com/Amir-kh-z/nl2sql-app-closed-core)**
— a closed core, where the engine is an installed package and features arrive
exactly like this one.

## What it does

Every action takes a **target**: a table, or a SELECT query you paste (the
query wins if you give both). An aggregate query is a perfectly good target —
profile a `GROUP BY` and you are exploring a summary, not a table.

| Action | Returns |
|---|---|
| **List tables** | Every table with its row count |
| **Profile (full)** | The rich profile — statistics, histograms, top values, null analysis. Best seen on the EDA page |
| **Profile (as a table)** | The same per-column statistics as a plain table — readable on any frontend |
| **Null analysis** | Exact null counts, plus the columns whose blanks travel together |
| **Top values** | The most frequent values of one column, with shares |

## Things it is careful about

- **Null counts are exact.** A rounded "0.00%" hides the three null rows in a
  million that somebody is hunting for.
- **Distinct counts are exact** below 200,000 rows and estimated above it,
  and the profile says which. An estimate cannot answer "is this column a
  key?" — and on a 682-row table the estimator reported 701.
- **Caps are reported, never silent**: "16 of 58 distinct values shown".
- **NaN and infinity never reach the browser** — one non-finite cell would
  otherwise break the JSON for the whole response.
- **Nothing calls a model.** EDA is pure computation: free, instant, and
  identical every run.

## How it talks to the database

Only through `ctx.query` — one guardrail-checked, read-only statement at a
time. No cursor, no parameters, no second statement. That constraint is why
this package installs safely on cores it has never met, and it is why the
statistics are hand-written aggregates rather than DuckDB's `SUMMARIZE`
(which is not a SELECT, and which returns min/max as text whatever the column
was).

## Development

```
python -m pytest -q        # 92 tests, needs a core installed
```

## The page

The full explorer — Overview, Columns, Explore, Advanced — ships **inside the
wheel** and appears at `/page/eda/` on a core that serves plugin pages, with
a **🔬 EDA** entry in the app's sidebar that opens it in its own tab, pinned
to the active connection.

The React source lives in `web/`. It is the original app-side page, carried
over with exactly **one file changed**: `web/src/api.js`, which routes the
old endpoint shapes to `POST /api/modules/run`. Every component, the ECharts
option builder and the chart lifecycle are untouched.

```
cd web && npm install && npm run build     # -> nl2sql_eda/webdist (committed)
```

The build output is committed, so installing this package needs no Node.
On a core without page support the page is simply absent and every action
still works.
