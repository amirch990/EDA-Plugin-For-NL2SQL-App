// Server chart specs → ECharts options. The server sends NUMBERS (categories,
// series, edges, matrices) and this file decides how they look — the same
// split charts.py makes for the PNG kinds, drawn on the other side of the
// wire. Nothing here recomputes anything.
import { fmt } from "./format.js";

// The engine's palette (nl2sql_engine/charts.py), so an interactive bar chart
// and an exported PNG read as the same product.
export const PALETTE = ["#0d9488", "#00b4d8", "#f7931e", "#9b59b6", "#2ecc71", "#e74c3c"];
const OTHER = "#8b98a9";

function ui() {
  const dark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
  return {
    fg: dark ? "#e6edf3" : "#1a1f26",
    muted: dark ? "#8b98a9" : "#5b6673",
    grid: dark ? "#262d38" : "#e8e4e0",
    mid: dark ? "#161b22" : "#f4f6f8",
  };
}

function axes(t, xLabel, yLabel, categories) {
  return {
    xAxis: {
      type: categories ? "category" : "value",
      ...(categories ? { data: categories } : {}),
      name: xLabel, nameLocation: "middle", nameGap: 34,
      nameTextStyle: { color: t.muted },
      axisLabel: { color: t.muted, hideOverlap: true,
                   rotate: categories && categories.some((c) => String(c).length > 9) ? 35 : 0 },
      axisLine: { lineStyle: { color: t.grid } },
    },
    yAxis: {
      type: "value", name: yLabel,
      nameTextStyle: { color: t.muted, align: "left" },
      axisLabel: { color: t.muted },
      splitLine: { lineStyle: { color: t.grid } },
    },
  };
}

function base(t, hasLegend) {
  return {
    color: PALETTE,
    textStyle: { color: t.fg },
    legend: hasLegend
      ? { top: 4, textStyle: { color: t.fg }, type: "scroll" }
      : { show: false },
    grid: { left: 14, right: 18, top: hasLegend ? 40 : 24, bottom: 44, containLabel: true },
  };
}

const seriesColor = (s, i) =>
  s.other ? { color: OTHER } : { color: PALETTE[i % PALETTE.length] };

function bar(spec, t) {
  const many = spec.series.length > 1;
  return {
    ...base(t, many),
    ...axes(t, spec.x_label, spec.y_label, spec.categories),
    tooltip: { trigger: "axis", confine: true },
    series: spec.series.map((s, i) => ({
      name: s.name, type: "bar", data: s.values,
      stack: spec.stacked ? "all" : undefined,
      itemStyle: seriesColor(s, i),
    })),
  };
}

function line(spec, t) {
  const many = spec.series.length > 1;
  return {
    ...base(t, many),
    ...axes(t, spec.x_label, spec.y_label, spec.categories),
    tooltip: { trigger: "axis", confine: true },
    series: spec.series.map((s, i) => ({
      name: s.name, type: "line", data: s.values,
      showSymbol: spec.categories.length <= 40,
      itemStyle: seriesColor(s, i), lineStyle: { width: 2 },
    })),
  };
}

function histogram(spec, t) {
  const cats = spec.edges.slice(0, -1).map((e, i) => `${fmt(e)}–${fmt(spec.edges[i + 1])}`);
  const many = spec.series.length > 1;
  return {
    ...base(t, many),
    ...axes(t, spec.x_label, "count", cats),
    tooltip: { trigger: "axis", confine: true },
    // With a hue the bins STACK — side-by-side slivers at 30 bins are
    // unreadable, and stacked counts still add up to the plain histogram.
    series: spec.series.map((s, i) => ({
      name: s.name, type: "bar", data: s.counts,
      stack: many ? "h" : undefined, barCategoryGap: "8%",
      itemStyle: seriesColor(s, i),
    })),
  };
}

function pie(spec, t) {
  return {
    ...base(t, true),
    tooltip: { trigger: "item", confine: true,
               valueFormatter: (v) => fmt(v) },
    series: [{
      type: "pie", radius: ["34%", "68%"],
      label: { color: t.fg, formatter: "{b}: {d}%" },
      data: spec.slices.map((s, i) => ({
        name: s.name, value: s.value,
        itemStyle: s.other ? { color: OTHER } : { color: PALETTE[i % PALETTE.length] },
      })),
    }],
  };
}

function scatter(spec, t) {
  const many = spec.series.length > 1;
  const total = spec.series.reduce((n, s) => n + s.points.length, 0);
  return {
    ...base(t, many),
    ...axes(t, spec.x_label, spec.y_label, null),
    tooltip: {
      trigger: "item", confine: true,
      formatter: (p) => `${p.seriesName}<br/>${spec.x_label}: ${fmt(p.value[0])}<br/>${spec.y_label}: ${fmt(p.value[1])}`,
    },
    series: spec.series.map((s, i) => ({
      name: s.name, type: "scatter", data: s.points,
      symbolSize: s.other ? 4 : 6, large: total > 2000,
      itemStyle: { ...seriesColor(s, i), opacity: 0.72 },
    })),
  };
}

// A log y-axis draws nothing for values ≤ 0, so the toggle is only offered
// when every drawn value — whisker ends and outlier points alike — is
// positive. Deciding here keeps the checkbox honest instead of silently
// producing an empty chart.
export function canLog(spec) {
  if (spec.kind !== "box") return false;
  let min = Infinity;
  for (const s of spec.series) {
    for (const b of s.boxes) if (b) min = Math.min(min, b[0]);
    for (const o of s.outliers) min = Math.min(min, o[1]);
  }
  return Number.isFinite(min) && min > 0;
}

function box(spec, t, view) {
  const hued = Boolean(spec.hue_label);
  const info = Object.fromEntries(spec.series.map((s) => [s.name, s]));
  const series = [];
  spec.series.forEach((s, i) => {
    const color = hued ? PALETTE[i % PALETTE.length] : PALETTE[0];
    series.push({
      name: s.name, type: "boxplot", data: s.boxes,
      itemStyle: { color: "transparent", borderColor: color, borderWidth: 1.6 },
    });
    // The outliers, as dots. Same series NAME as the box, so the legend
    // toggles a hue's box and its dots together.
    if (s.outliers.length) {
      series.push({
        name: s.name, type: "scatter", data: s.outliers,
        symbolSize: 5, itemStyle: { color, opacity: 0.55 },
      });
    }
  });
  const ax = axes(t, spec.x_label || "", spec.y_label, spec.categories);
  if (view?.logY && canLog(spec)) ax.yAxis.type = "log";
  return {
    ...base(t, hued),
    ...ax,
    tooltip: {
      trigger: "item", confine: true,
      formatter: (p) => {
        const s = info[p.seriesName] || {};
        if (p.seriesType === "scatter") {
          return `${hued ? p.seriesName + "<br/>" : ""}outlier: ${fmt(p.data[1])}`;
        }
        const b = p.data;
        if (!b) return "";
        return `${p.name}${hued ? " · " + p.seriesName : ""}` +
               `<br/>whisker high ${fmt(b[4])}<br/>q75 ${fmt(b[3])}` +
               `<br/>median ${fmt(b[2])}<br/>q25 ${fmt(b[1])}` +
               `<br/>whisker low ${fmt(b[0])}` +
               `<br/>${fmt((s.counts || [])[p.dataIndex])} values · ` +
               `${fmt((s.outlier_counts || [])[p.dataIndex])} outliers`;
      },
    },
    series,
  };
}

function corr(spec, t) {
  const n = spec.columns.length;
  const data = [];
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const v = spec.matrix[i][j];
      if (v !== null) data.push([j, i, Math.round(v * 100) / 100]);
    }
  }
  return {
    color: PALETTE,
    textStyle: { color: t.fg },
    tooltip: {
      confine: true,
      formatter: (p) => `${spec.columns[p.value[1]]} × ${spec.columns[p.value[0]]}: ${p.value[2]}`,
    },
    grid: { left: 14, right: 18, top: 14, bottom: 70, containLabel: true },
    xAxis: { type: "category", data: spec.columns,
             axisLabel: { color: t.muted, rotate: 40 } },
    yAxis: { type: "category", data: spec.columns, inverse: true,
             axisLabel: { color: t.muted } },
    visualMap: {
      min: -1, max: 1, calculable: false, orient: "horizontal",
      left: "center", bottom: 0, textStyle: { color: t.muted },
      inRange: { color: ["#00b4d8", t.mid, "#f7931e"] },
    },
    series: [{
      type: "heatmap", data,
      label: { show: n <= 9, color: t.fg, fontSize: 9 },
      itemStyle: { borderColor: t.grid, borderWidth: 1 },
    }],
  };
}

export function toOption(spec, view) {
  const t = ui();
  switch (spec.kind) {
    case "bar": return bar(spec, t);
    case "line": return line(spec, t);
    case "histogram": return histogram(spec, t);
    case "pie": return pie(spec, t);
    case "scatter": return scatter(spec, t);
    case "box": return box(spec, t, view);
    case "corr": return corr(spec, t);
    default: return null;
  }
}

// A reasonable canvas height per kind — corr grows with its matrix.
export function heightFor(spec) {
  if (spec.kind === "corr") return Math.max(340, 42 * spec.columns.length + 130);
  return 430;
}
