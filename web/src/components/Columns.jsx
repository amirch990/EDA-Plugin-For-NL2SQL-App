import React from "react";
import { fmt } from "../format.js";
import { SparkHist, ValueBars } from "./spark.jsx";

// One card per column, generated from the profile alone — no further calls.
// A numeric column shows its shape, a categorical one its top values, a date
// its range; the point is a page you can SCAN, the way pandas-profiling and
// SweetViz open.
function ColumnCard({ c }) {
  return (
    <div className="colcard">
      <div className="head">
        <span className="cname" title={c.name}>{c.name}</span>
        <span className="typechip">{c.type}</span>
        {c.null_pct > 0 && <span className="nullchip">{c.null_pct}% null</span>}
      </div>

      {c.histogram ? (
        <>
          <SparkHist hist={c.histogram} />
          <div className="foot">
            <span>min {fmt(c.min)}</span>
            <span>median {fmt(c.median)}</span>
            <span>max {fmt(c.max)}</span>
          </div>
        </>
      ) : c.top_values ? (
        <ValueBars values={c.top_values} />
      ) : (
        <div className="foot" style={{ marginTop: 8 }}>
          <span>min {fmt(c.min)}</span>
          <span>max {fmt(c.max)}</span>
        </div>
      )}

      <div className="foot">
        <span>{fmt(c.count)} values</span>
        <span>≈ {fmt(c.unique)} distinct</span>
      </div>
    </div>
  );
}

export default function Columns({ profile }) {
  return (
    <div className="colgrid">
      {profile.columns.map((c) => <ColumnCard key={c.name} c={c} />)}
    </div>
  );
}
