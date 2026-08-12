import React, { useEffect, useMemo, useState } from "react";
import { post } from "../api.js";

// The plots a browser charting library does not draw: the server renders
// them with matplotlib and sends a finished PNG — the same division of
// labour the app's reports use, and the same picture wherever it travels.
const KINDS = [
  ["kde", "KDE — smooth distribution", { x: "num", hue: "opt" }],
  ["ridgeline", "Ridgeline — one density per category", { x: "num", hue: "req" }],
  ["hexbin", "Hexbin — scatter at scale", { x: "num", y: "num", bins: 1 }],
];

export default function Advanced({ db, target, profile }) {
  const [kind, setKind] = useState("kde");
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [hue, setHue] = useState("");
  const [bins, setBins] = useState(30);
  const [out, setOut] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const numeric = useMemo(
    () => profile.columns.filter((c) => ["integer", "number"].includes(c.simple_type)),
    [profile]);
  const categorical = useMemo(
    () => profile.columns.filter((c) => c.top_values || ["text", "bool"].includes(c.simple_type)),
    [profile]);

  useEffect(() => {
    setOut(null); setErr("");
    setX(numeric[0]?.name || "");
    setY(numeric[1]?.name || "");
    setHue("");
  }, [profile]);

  const need = KINDS.find(([k]) => k === kind)[2];
  const canDraw = Boolean(x) && (need.y ? Boolean(y) : true) &&
    (need.hue === "req" ? Boolean(hue) : true);

  async function draw() {
    setBusy(true); setErr("");
    try {
      setOut(await post("/eda/chart", {
        db, ...target, kind, x, y: need.y ? y : null,
        hue: need.hue ? hue || null : null, bins: Number(bins) || 30,
      }));
    } catch (e) {
      setOut(null); setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="controls" style={{ marginTop: 0 }}>
        <div className="field">
          <label>Plot</label>
          <select value={kind} onChange={(e) => { setKind(e.target.value); setOut(null); setErr(""); }}>
            {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
        </div>

        <div className="field">
          <label>{kind === "hexbin" ? "X" : "Value (x)"}</label>
          <select value={x} onChange={(e) => setX(e.target.value)}>
            {numeric.map((c) => <option key={c.name} value={c.name}>{c.name} · {c.simple_type}</option>)}
          </select>
        </div>

        {need.y && (
          <div className="field">
            <label>Y</label>
            <select value={y} onChange={(e) => setY(e.target.value)}>
              {numeric.map((c) => <option key={c.name} value={c.name}>{c.name} · {c.simple_type}</option>)}
            </select>
          </div>
        )}

        {need.hue && (
          <div className="field">
            <label>{need.hue === "req" ? "Categories (hue)" : "Hue (optional)"}</label>
            <select value={hue} onChange={(e) => setHue(e.target.value)}>
              <option value="">{need.hue === "req" ? "— choose —" : "— none —"}</option>
              {categorical.map((c) => <option key={c.name} value={c.name}>{c.name} · {c.simple_type}</option>)}
            </select>
          </div>
        )}

        {need.bins && (
          <div className="field">
            <label>Hex grid</label>
            <input type="number" min="12" max="60" value={bins}
                   onChange={(e) => setBins(e.target.value)} style={{ width: 74 }} />
          </div>
        )}

        <button className="primary" onClick={draw} disabled={busy || !canDraw}>
          {busy ? "drawing…" : "Draw"}
        </button>
      </div>

      {err && <div className="error">{err}</div>}

      {out && (
        <div className="panel pngwrap">
          <img src={`data:image/png;base64,${out.png_base64}`} alt={kind} />
          <div className="basis">{out.basis}
            {out.meta?.hue_total > out.meta?.hue_shown
              ? ` · top ${out.meta.hue_shown} of ${out.meta.hue_total} categories` : ""}
          </div>
          <div style={{ marginTop: 8 }}>
            <a className="chip" download={`${kind}.png`}
               href={`data:image/png;base64,${out.png_base64}`}>⬇ download PNG</a>
          </div>
        </div>
      )}

      {!out && !err && (
        <div className="empty">
          KDE smooths a histogram into a curve; a ridgeline draws one density
          per category; hexbin is a scatter plot that stays readable at fifty
          thousand points.
        </div>
      )}
    </div>
  );
}
