// The one file this page needed when it moved out of the app.
//
// It used to call endpoints the app owned (`/api/eda/profile`,
// `/api/eda/chart`, `/api/eda/targets`). Those endpoints no longer exist —
// the whole feature is a plugin now, reached through the app's generic
// module runner. So this file keeps the OLD SHAPES and routes them to the
// new door: every component, App.jsx, the option builder and the chart
// lifecycle were carried over untouched.
//
//   post("/eda/profile", …)  ->  POST /api/modules/run  {action:"profile"}
//   post("/eda/chart",   …)  ->  POST /api/modules/run  {action:"chart"}
//   get("/eda/targets?db=…") ->  the "tables" action + the app's own
//                                /api/chat/history, composed here
//   get("/connections")      ->  straight through (an app route, still there)
//
// JSON in, JSON out — and an error is the SERVER'S sentence, not "request
// failed". The backend writes its refusals to be read ("`DROP` is not
// allowed — EDA only reads"), so the one job here is not to lose them on the
// way to the screen.

const MODULE = "eda";

async function handle(r) {
  if (r.ok) return r.json();
  let message = `${r.status} ${r.statusText}`;
  try {
    const body = await r.json();
    message = body?.detail?.message || body?.detail || message;
  } catch {
    /* no JSON body — keep the status line */
  }
  throw new Error(message);
}

const raw = (path) => fetch(`/api${path}`).then(handle);

// Run one module action and hand back what it produced.
//
// Two failure layers, deliberately kept apart by the app's contract and
// flattened into one throw here, because every component already has a catch
// that shows a sentence:
//   ok:false          the CALL failed (no such module, missing input, the
//                     module raised) — `error`, sometimes with a `hint`
//   kind:"error"      the module ANSWERED with a refusal it wrote itself
async function run(action, db, inputs) {
  const res = await fetch("/api/modules/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ module: MODULE, action, db, inputs }),
  }).then(handle);

  if (!res.ok) {
    throw new Error(res.hint ? `${res.error}\n${res.hint}` : res.error);
  }
  if (res.kind === "error") throw new Error(res.data);
  return res.data;
}

// A target is `{table}` or `{sql}`; both inputs are always sent because the
// module declares both and lets a non-empty query win.
const target = (body) => ({ table: body.table || "", sql: body.sql || "" });

export async function get(path) {
  const targets = path.match(/^\/eda\/targets\?db=(.*)$/);
  if (targets) {
    const db = decodeURIComponent(targets[1]);
    // The table list comes from the module; the chat history is the APP's,
    // and stays the app's — a plugin has no business reading another
    // feature's store, and the app already publishes it.
    const [tablesResult, turns] = await Promise.all([
      run("tables", db, {}),
      raw(`/chat/history?db=${encodeURIComponent(db)}`).catch(() => []),
    ]);
    const tables = (tablesResult?.rows || []).map(([table, rows]) => ({
      table,
      rows,
    }));

    // Newest first, one entry per distinct query — the same question asked
    // three times is one target, and the latest wording is the one shown.
    // (Lifted from the app-side targets() this replaces.)
    const history = [];
    const seen = new Set();
    for (let i = (turns || []).length - 1; i >= 0; i--) {
      const turn = turns[i] || {};
      const sql = (turn.sql || "").trim();
      if (turn.shape !== "answer" || !sql) continue;
      const key = sql.toLowerCase().split(/\s+/).join(" ");
      if (seen.has(key)) continue;
      seen.add(key);
      history.push({
        question: (turn.question || "").trim(),
        sql,
        rows: turn.rows,
      });
      if (history.length >= 25) break;
    }
    return { database: db, tables, history };
  }
  return raw(path);                       // /connections, and anything later
}

export async function post(path, body) {
  if (path === "/eda/profile") {
    const data = await run("profile", body.db, target(body));
    // The module cannot know what the app calls this connection, and the
    // page prints it — so the caller fills it in.
    return { ...data, database: body.db };
  }
  if (path === "/eda/chart") {
    return run("chart", body.db, {
      ...target(body),
      kind: body.kind || "bar",
      x: body.x || "",
      y: body.y || "",
      hue: body.hue || "",
      agg: body.agg || "count",
      bins: body.bins ?? 30,
      // The module's "no grouping" is a named choice rather than an empty
      // one: a blank option in a dropdown reads as a mistake.
      granularity: body.granularity || "as-is",
      stacked: !!body.stacked,
    });
  }
  return fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(handle);
}
