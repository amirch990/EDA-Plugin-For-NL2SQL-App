# Rules for building this module (read me first)

You are helping a student build a module for the NL2SQL app. The module is an
installed Python package; the app discovers it automatically. These rules are
what keep that safe — do not bend them:

1. **Never edit the app or the engine.** Everything this module needs lives in
   THIS folder. If a capability seems to require touching the app, it belongs
   in the module contract instead — say so rather than working around it.
2. **Data only through `ctx`.** Read with `ctx.query(sql)` / `ctx.tables()` /
   `ctx.columns(table)` / `ctx.schema_text()`. Never open the database
   yourself, never import from the app's `api/` package.
3. **Files only under `ctx.data_dir()`.** That directory survives upgrades;
   anywhere else is lost or worse. Prefix your filenames with the module name.
4. **Every action returns a `Result`** — `Result.table(rows, columns)`,
   `Result.markdown(text)`, `Result.sql(text)`, or `Result.error(message)`.
   Never return raw data, never print.
5. **After editing: restart the app, then refresh the browser.** Python caches
   imported code; the editable install removes the reinstall step, not the
   restart.
6. **Declare, don't draw.** A module states its inputs and returns Results;
   the app renders both. No HTML, no UI code in here.
7. `requires_core` states the contract range this module needs (against the
   core's `API_VERSION`, currently `>=1.0,<2.0`). Leave it unless the module
   starts using a newer contract feature.

## Specific to this module

- The rich actions (`profile`, later `chart`) return `Result.chart(spec)`
  where the spec is this plugin's own dialect, named by `spec["type"]`
  (`eda/profile`, `eda/bar`, …). The plugin's page draws them; any other
  frontend shows the data. Never invent a new Result *kind* — the contract's
  set is closed on purpose.
- The plain actions (`profile-table`, `nulls`, `top-values`) must stay
  useful on a frontend that knows nothing about this plugin. If you add a
  rich action, consider whether a plain sibling is worth it.
- All SQL goes through `ctx.query`: ONE read-only SELECT/WITH, no bound
  parameters. Compose caps with CTE joins rather than IN-lists of values.
- Identifiers reach SQL only via `common.q()`; numbers only if this code
  computed them. Nothing a person typed is ever interpolated raw.
- Every number a person reads must pass `common.num()`/`scalar()` — a NaN in
  the JSON breaks the whole response, not one cell.
