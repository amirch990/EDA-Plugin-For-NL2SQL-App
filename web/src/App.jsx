import React, { useEffect, useMemo, useRef, useState } from "react";
import { get, post } from "./api.js";
import Overview from "./components/Overview.jsx";
import Columns from "./components/Columns.jsx";

import Advanced from "./components/Advanced.jsx";

// Lazy, exactly as the main SPA loads its pages: ECharts is ~700 KB of the
// bundle and only the Explore tab needs it — the profile tabs open light.
const Explore = React.lazy(() => import("./components/Explore.jsx"));

// Deep links work: /eda/?db=financial&table=loan opens profiled, and
// /eda/?db=financial&sql=SELECT… profiles a query. That is what lets any
// other page (or a demo script) point AT a specific view of the data.
const params = new URLSearchParams(window.location.search);

const TABS = [["overview", "Overview"], ["columns", "Columns"], ["explore", "Explore"],
              ["advanced", "Advanced"]];

export default function App() {
  const [connections, setConnections] = useState(null);
  const [db, setDb] = useState(params.get("db") || "");
  const [targets, setTargets] = useState(null);
  const [mode, setMode] = useState(params.get("sql") ? "sql" : "table");
  const [table, setTable] = useState(params.get("table") || "");
  const [histIdx, setHistIdx] = useState(-1);
  const [sqlText, setSqlText] = useState(params.get("sql") || "");
  const [profile, setProfile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("overview");
  const deepLinkedSql = useRef(Boolean(params.get("sql")));

  // ── the connection is PINNED, not chosen here. The launcher passes the
  // main app's active connection in the URL; every page of the app follows
  // one active connection, and this page is no exception. A visit with no
  // parameter (a typed URL, a bookmark) falls back to the connection used
  // most recently — the closest thing the server knows to "active". To
  // explore another database: switch it in the main app, click 🔬 EDA again.
  useEffect(() => {
    get("/connections")
      .then((list) => {
        setConnections(list);
        if (!params.get("db") && list.length) {
          const used = [...list].sort((a, b) =>
            String(b.last_used || "").localeCompare(String(a.last_used || "")));
          setDb(used[0].name);
        }
      })
      .catch((e) => { setConnections([]); setError(String(e.message || e)); });
  }, []);

  useEffect(() => {
    if (db) document.title = `NL2SQL · EDA · ${db}`;
  }, [db]);

  // ── targets for the chosen database ──
  useEffect(() => {
    if (!db) return;
    setTargets(null); setProfile(null); setError(""); setHistIdx(-1);
    get(`/eda/targets?db=${encodeURIComponent(db)}`)
      .then((t) => {
        setTargets(t);
        const names = t.tables.map((x) => x.table);
        if (mode === "table" && !names.includes(table)) setTable(names[0] || "");
      })
      .catch((e) => setError(String(e.message || e)));
  }, [db]);

  async function runProfile(target) {
    setBusy(true); setError("");
    try {
      setProfile(await post("/eda/profile", { db, ...target }));
    } catch (e) {
      setProfile(null); setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  // Tables and past queries profile on selection — the calls are sub-second
  // and free. Typed SQL waits for its button, so half-typed queries are
  // never sent.
  useEffect(() => {
    if (!db || !targets) return;
    if (mode === "table" && table) runProfile({ table });
    else if (mode === "history" && histIdx >= 0 && targets.history[histIdx]) {
      runProfile({ sql: targets.history[histIdx].sql });
    } else if (mode === "sql" && deepLinkedSql.current && sqlText.trim()) {
      deepLinkedSql.current = false;
      runProfile({ sql: sqlText });
    }
  }, [db, targets, mode, table, histIdx]);

  // What the chart calls should run on — the SAME target the profile ran on.
  const target = useMemo(() => {
    if (mode === "table") return table ? { table } : null;
    if (mode === "history") return histIdx >= 0 && targets?.history[histIdx]
      ? { sql: targets.history[histIdx].sql } : null;
    return sqlText.trim() ? { sql: sqlText.trim() } : null;
  }, [mode, table, histIdx, sqlText, targets]);

  const targetLabel = profile
    ? (profile.target.kind === "table" ? `table · ${profile.target.label}` : `query · ${profile.target.label}`)
    : null;

  return (
    <div className="page">
      <div className="header">
        <h1>🔬 EDA</h1>
        <span className="sub">summary statistics · nulls · charts — computed in the database, no model calls</span>
        {targetLabel && <span className="chip accent" title={profile.target.label}>{targetLabel}</span>}
        {busy && <span className="chip busy">profiling…</span>}
      </div>

      <div className="controls">
        <div className="field">
          <label>Connection — follows the main app</label>
          <span className="chip" style={{ padding: "6px 12px" }}
                title="EDA is pinned to the app's active connection. To explore a different database, switch the connection in the main app's sidebar and click 🔬 EDA again.">
            🗄 {db || "—"}
          </span>
        </div>

        <div className="field">
          <label>Explore</label>
          <div className="seg">
            <button className={mode === "table" ? "on" : ""} onClick={() => setMode("table")}>Table</button>
            <button className={mode === "history" ? "on" : ""} onClick={() => setMode("history")}>Past query</button>
            <button className={mode === "sql" ? "on" : ""} onClick={() => setMode("sql")}>SQL</button>
          </div>
        </div>

        {mode === "table" && (
          <div className="field">
            <label>Table</label>
            <select value={table} onChange={(e) => setTable(e.target.value)}>
              {(targets?.tables || []).map((t) => (
                <option key={t.table} value={t.table}>
                  {t.table}{t.rows != null ? ` · ${t.rows.toLocaleString("en-US")} rows` : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        {mode === "history" && (
          <div className="field">
            <label>Question already asked in Chat (its SQL is re-run, fresh)</label>
            <select value={histIdx} onChange={(e) => setHistIdx(Number(e.target.value))}
                    style={{ maxWidth: 520 }}>
              <option value={-1}>— choose a past question —</option>
              {(targets?.history || []).map((h, i) => (
                <option key={i} value={i} title={h.sql}>
                  {h.question || h.sql}
                </option>
              ))}
            </select>
            {targets && targets.history.length === 0 && (
              <span className="note" style={{ fontSize: 11.5 }}>
                Nothing yet — ask something in 💬 Chat first, then come back.
              </span>
            )}
          </div>
        )}

        {mode === "sql" && (
          <>
            <div className="field" style={{ flex: 1 }}>
              <label>A read-only SELECT — same guardrail as everywhere else in the app</label>
              <textarea value={sqlText} onChange={(e) => setSqlText(e.target.value)}
                        placeholder="SELECT district_id, avg(amount) AS avg_loan FROM loan JOIN account USING (account_id) GROUP BY district_id" />
            </div>
            <button className="primary" disabled={busy || !sqlText.trim()}
                    onClick={() => runProfile({ sql: sqlText })}>
              Profile it
            </button>
          </>
        )}
      </div>

      {error && <div className="error">{error}</div>}

      {profile && (
        <>
          <div className="tabs">
            {TABS.map(([id, label]) => (
              <button key={id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
                {label}
              </button>
            ))}
          </div>
          {tab === "overview" && <Overview db={db} target={target} profile={profile} />}
          {tab === "columns" && <Columns profile={profile} />}
          {tab === "explore" && (
            <React.Suspense fallback={<div className="empty">loading charts…</div>}>
              <Explore db={db} target={target} profile={profile} />
            </React.Suspense>
          )}
          {tab === "advanced" && <Advanced db={db} target={target} profile={profile} />}
        </>
      )}

      {!profile && !busy && !error && (
        <div className="empty">Pick a table, a past question, or paste a SELECT — the profile appears here.</div>
      )}
    </div>
  );
}
