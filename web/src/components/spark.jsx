import React from "react";
import { fmt } from "../format.js";

// Inline SVG, not a chart library instance. A profile page draws forty of
// these at once; forty canvases with event systems is a page that stutters,
// forty <svg> elements is nothing.
export function SparkHist({ hist, width = 226, height = 54 }) {
  const counts = hist?.counts || [];
  if (!counts.length) return null;
  const max = Math.max(...counts, 1);
  const bw = width / counts.length;
  return (
    <svg className="spark" width={width} height={height} role="img">
      {counts.map((c, i) => {
        const h = c > 0 ? Math.max((c / max) * (height - 4), 2) : 0;
        return (
          <rect key={i} x={i * bw + 0.5} y={height - h} width={Math.max(bw - 1, 1)} height={h} rx="1">
            <title>
              {fmt(hist.edges[i])} – {fmt(hist.edges[i + 1])}: {fmt(c)} rows
            </title>
          </rect>
        );
      })}
    </svg>
  );
}

export function ValueBars({ values }) {
  const max = Math.max(...values.map((v) => v.count), 1);
  return (
    <div>
      {values.map((v, i) => (
        <div className={"valrow" + (v.other ? " other" : "")} key={i}>
          <span className="vallabel" title={v.other ? "everything else" : String(v.value)}>
            {v.other ? "(other values)" : String(v.value)}
          </span>
          <div className="valbar">
            <div style={{ width: `${(v.count / max) * 100}%` }} />
          </div>
          <span className="valn">{v.pct}%</span>
        </div>
      ))}
    </div>
  );
}
