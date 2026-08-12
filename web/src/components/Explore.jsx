import React, { useEffect, useMemo, useRef, useState } from "react";
import { post } from "../api.js";
import { fmt } from "../format.js";
import Chart from "./Chart.jsx";
import { canLog, heightFor, toOption } from "../options.js";

// Which controls each kind needs. This is the Tableau shelf idea reduced to a
// form: X, Y (with an aggregation), and Hue — the seaborn color-by column.
const KINDS = [
  ["bar", "Bar", { x: "any", y: "opt", agg: 1, hue: 1, stacked: 1 }],
  ["line", "Line", { x: "any", y: "opt", agg: 1, hue: 1, gran: 1 }],
  ["histogram", "Histogram", { x: "num", bins: 1, hue: 1 }],
  ["pie", "Pie", { x: "any", y: "opt", agg: "sum-only" }],
  ["scatter", "Scatter", { x: "num", y: "num", hue: 1 }],
  ["box", "Box · outliers", { x: "opt-any", y: "num", hue: 1 }],
  ["corr", "Correlation", {}],
];

const AGGS_ALL = ["count", "sum", "avg", "min", "max"];

function ColSelect({ label, value, onChange, cols, allowNone, noneLabel = "—" }) {
  return (
    <div className="field">
      <label>{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {allowNone && <option value="">{noneLabel}</option>}
        {cols.map((c) => (
          <option key={c.name} value={c.name}>{c.name} · {c.simple_type}</option>
        ))}
      </select>
    </div>
  );
}

export default function Explore({ db, target, profile }) {
  const [kind, setKind] = useState("bar");
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [hue, setHue] = useState("");
  const [agg, setAgg] = useState("count");
  const [bins, setBins] = useState(30);
  const [gran, setGran] = useState("");
  const [stacked, setStacked] = useState(false);
  const [spec, setSpec] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [logY, setLogY] = useState(false);
  const inst = useRef(null);

  function savePng() {
    const url = inst.current?.getDataURL({
      pixelRatio: 2,
      backgroundColor: getComputedStyle(document.body).backgroundColor,
    });
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${spec?.kind || "chart"}.png`;
    a.click();
  }

  const cols = profile.columns;
  const numeric = useMemo(() => cols.filter((c) => ["integer", "number"].includes(c.simple_type)), [cols]);
  const categorical = useMemo(
    () => cols.filter((c) => c.top_values || ["text", "bool"].includes(c.simple_type)), [cols]);
  const xIsDate = cols.find((c) => c.name === x)?.simple_type === "date";

  // New target, fresh start — sensible defaults instead of stale column names
  // that may not exist in the new relation.
  useEffect(() => {
    setSpec(null); setErr("");
    setX((categorical[0] || cols[0])?.name || "");
    setY("");
    setHue("");
    setAgg("count"); setGran(""); setStacked(false);
  }, [profile]);

  const need = KINDS.find(([k]) => k === kind)[2];
  const xCols = need.x === "num" ? numeric : cols;
  const canDraw =
    (need.x ? Boolean(x) || need.x === "opt-any" : true) &&
    (need.y === "num" ? Boolean(y) : true) &&
    (!("agg" in need) || agg === "count" || Boolean(y));

  async function draw() {
    setBusy(true); setErr("");
    try {
      const body = {
        db, ...target, kind,
        x: x || null, y: y || null, hue: hue || null,
        agg: y ? agg : "count", bins: Number(bins) || 30,
        granularity: gran || null, stacked,
      };
      setSpec(await post("/eda/chart", body));
    } catch (e) {
      setSpec(null); setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  const metaLine = useMemo(() => {
    if (!spec?.meta) return "";
    const m = spec.meta, parts = [];
    if (m.categories_total > m.categories_shown)
      parts.push(`top ${m.categories_shown} of ${m.categories_total} categories`);
    if (m.hue_total > m.hue_shown) parts.push(`top ${m.hue_shown} of ${m.hue_total} hues`);
    if (spec.kind === "histogram" && spec.series.length > 1) parts.push("stacked");
    if (spec.kind === "box") {
      parts.push("whiskers: Tukey 1.5×IQR");
      parts.push(m.outliers_total
        ? `${fmt(m.outliers_total)} outliers` +
          (m.outliers_shown < m.outliers_total ? ` (${fmt(m.outliers_shown)} most extreme drawn)` : "")
        : "no outliers beyond the fences");
    }
    if (spec.kind === "corr" && m.numeric_total > spec.columns.length)
      parts.push(`first ${spec.columns.length} of ${m.numeric_total} numeric columns`);
    return parts.join(" · ");
  }, [spec]);

  return (
    <div>
      <div className="controls" style={{ marginTop: 0 }}>
        <div className="field">
          <label>Chart</label>
          <select value={kind} onChange={(e) => { setKind(e.target.value); setSpec(null); setErr(""); }}>
            {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>

        {need.x && (
          <ColSelect label={need.x === "opt-any" ? "Split by (x, optional)" : "X"}
                     value={x} onChange={setX} cols={xCols}
                     allowNone={need.x === "opt-any"} noneLabel="— one box —" />
        )}
        {(need.y === "num" || need.y === "opt") && (
          <ColSelect label={need.y === "num" ? "Y" : "Y (blank = count rows)"}
                     value={y} onChange={setY} cols={numeric}
                     allowNone={need.y === "opt"} noneLabel="— count —" />
        )}
        {"agg" in need && y && (
          <div className="field">
            <label>Aggregate</label>
            <select value={agg} onChange={(e) => setAgg(e.target.value)}>
              {(need.agg === "sum-only" ? ["sum"] : AGGS_ALL.filter((a) => a !== "count"))
                .map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        )}
        {need.hue && (kind !== "box" || x) && (
          <ColSelect label="Hue (color by)" value={hue} onChange={setHue}
                     cols={cols.filter((c) => c.name !== x)} allowNone noneLabel="— none —" />
        )}
        {need.bins && (
          <div className="field">
            <label>Bins</label>
            <input type="number" min="5" max="100" value={bins}
                   onChange={(e) => setBins(e.target.value)} style={{ width: 74 }} />
          </div>
        )}
        {need.gran && xIsDate && (
          <div className="field">
            <label>Group dates by</label>
            <select value={gran} onChange={(e) => setGran(e.target.value)}>
              <option value="">exact value</option>
              <option value="year">year</option>
              <option value="month">month</option>
              <option value="week">week</option>
              <option value="day">day</option>
            </select>
          </div>
        )}
        {need.stacked && hue && (
          <div className="field">
            <label>Bars</label>
            <div className="seg">
              <button className={stacked ? "" : "on"} onClick={() => setStacked(false)}>grouped</button>
              <button className={stacked ? "on" : ""} onClick={() => setStacked(true)}>stacked</button>
            </div>
          </div>
        )}

        <button className="primary" onClick={draw} disabled={busy || !canDraw}>
          {busy ? "drawing…" : "Draw"}
        </button>
      </div>

      {err && <div className="error">{err}</div>}

      {spec && spec.renderer === "echarts" && (
        <div className="panel">
          <Chart option={toOption(spec, { logY })} height={heightFor(spec)}
                 onInit={(c) => { inst.current = c; }} />
          <div className="basis">{spec.basis}{metaLine ? ` · ${metaLine}` : ""}</div>
          <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
            <a className="chip" style={{ cursor: "pointer" }} onClick={savePng}>⬇ download PNG</a>
            {spec.kind === "box" && (
              <label className="chip"
                     style={{ cursor: canLog(spec) ? "pointer" : "not-allowed",
                              opacity: canLog(spec) ? 1 : 0.5 }}
                     title={canLog(spec)
                       ? "Spread a long-tailed axis so the box is readable"
                       : "Log scale needs every drawn value to be positive"}>
                <input type="checkbox" disabled={!canLog(spec)}
                       checked={logY && canLog(spec)}
                       onChange={(e) => setLogY(e.target.checked)}
                       style={{ marginRight: 6 }} />
                log y-scale
              </label>
            )}
          </div>
        </div>
      )}

      {!spec && !err && (
        <div className="empty">
          Choose a chart and its columns, then Draw. Add a <b>hue</b> to color
          bars, lines or points by a category — sales by product, colored by
          country.
        </div>
      )}
    </div>
  );
}
