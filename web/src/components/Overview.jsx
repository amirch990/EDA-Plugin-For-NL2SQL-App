import React, { useEffect, useMemo, useState } from "react";
import { post } from "../api.js";
import { fmt } from "../format.js";

const STAT_COLS = [
  ["name", "column"], ["type", "type"], ["count", "count"], ["null_pct", "null %"],
  ["unique", "≈ unique"], ["min", "min"], ["q25", "q25"], ["median", "median"],
  ["mean", "mean"], ["q75", "q75"], ["max", "max"], ["std", "std"],
];

export default function Overview({ db, target, profile }) {
  const [sort, setSort] = useState({ key: "name", dir: 1 });
  const [png, setPng] = useState(null);
  const [pngBusy, setPngBusy] = useState(false);
  const [pngErr, setPngErr] = useState("");

  useEffect(() => { setPng(null); setPngErr(""); }, [profile]);

  const rows = useMemo(() => {
    const r = [...profile.columns];
    r.sort((a, b) => {
      const va = a[sort.key], vb = b[sort.key];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;               // gaps sink whatever the order
      if (vb == null) return -1;
      const d = typeof va === "number" && typeof vb === "number"
        ? va - vb : String(va).localeCompare(String(vb));
      return d * sort.dir;
    });
    return r;
  }, [profile, sort]);

  const nulls = profile.nulls;

  async function drawMatrix() {
    setPngBusy(true); setPngErr("");
    try {
      const out = await post("/eda/chart", { db, ...target, kind: "null_matrix" });
      setPng(out);
    } catch (e) {
      setPngErr(String(e.message || e));
    } finally {
      setPngBusy(false);
    }
  }

  return (
    <div>
      <div className="cards">
        <div className="card"><div className="big">{fmt(profile.row_count)}</div><div className="label">rows</div></div>
        <div className="card"><div className="big">{fmt(profile.column_count)}</div><div className="label">columns</div></div>
        <div className="card"><div className="big">{fmt(nulls.total_null_cells)}</div><div className="label">null cells</div></div>
        <div className="card"><div className="big">{nulls.by_column.length}</div><div className="label">columns with nulls</div></div>
      </div>

      <div className="panel">
        <h2>Descriptive statistics</h2>
        <div className="tablewrap">
          <table className="stats">
            <thead>
              <tr>
                {STAT_COLS.map(([key, label]) => (
                  <th key={key}
                      onClick={() => setSort((s) => ({ key, dir: s.key === key ? -s.dir : 1 }))}>
                    {label}{sort.key === key ? (sort.dir > 0 ? " ▲" : " ▼") : ""}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}<span className="typechip">{c.type}</span></td>
                  <td>{c.simple_type}</td>
                  <td>{fmt(c.count)}</td>
                  <td>{c.null_pct > 0 ? `${c.null_pct}%` : "—"}</td>
                  <td>{fmt(c.unique)}</td>
                  <td>{fmt(c.min)}</td>
                  <td>{fmt(c.q25)}</td>
                  <td>{fmt(c.median)}</td>
                  <td>{fmt(c.mean)}</td>
                  <td>{fmt(c.q75)}</td>
                  <td>{fmt(c.max)}</td>
                  <td>{fmt(c.std)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="basis">{profile.basis} · unique counts are approximate</div>
      </div>

      <div className="panel">
        <h2>Missing values</h2>
        {nulls.by_column.length === 0 ? (
          <p className="note">
            No missing values anywhere — {fmt(profile.row_count)} ×{" "}
            {profile.column_count} cells, all filled.
          </p>
        ) : (
          <>
            {nulls.by_column.map((e) => (
              <div className="nullrow" key={e.column}>
                <span className="name" title={e.column}>{e.column}</span>
                <div className="nullbar"><div style={{ width: `${Math.max(e.pct, 0.6)}%` }} /></div>
                <span>{e.pct}% · {fmt(e.nulls)}</span>
              </div>
            ))}

            {nulls.patterns.length > 0 && (
              <>
                <h2 style={{ marginTop: 14 }}>How the nulls travel together</h2>
                {nulls.patterns.map((p, i) => (
                  <div className="pattern" key={i}>
                    {p.columns.map((c) => <code key={c}>{c}</code>)}{" "}
                    null together in {fmt(p.rows)} rows ({p.pct}%)
                  </div>
                ))}
                {nulls.pairs.map((p, i) => (
                  <div className="pattern" key={`p${i}`}>
                    when <code>{p.a}</code> is null, <code>{p.b}</code> is null too
                    — {Math.round(p.p * 100)}% of the time
                  </div>
                ))}
                {nulls.patterns_truncated && (
                  <p className="note">Pattern list truncated — computed over the most common null combinations.</p>
                )}
              </>
            )}

            <div style={{ marginTop: 12 }}>
              <button className="primary" onClick={drawMatrix} disabled={pngBusy}>
                {pngBusy ? "drawing…" : "Draw the missing-cells matrix"}
              </button>
            </div>
            {pngErr && <div className="error">{pngErr}</div>}
            {png && (
              <div className="pngwrap" style={{ marginTop: 10 }}>
                <img src={`data:image/png;base64,${png.png_base64}`} alt="missing-cells matrix" />
                <div className="basis">{png.basis}</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
