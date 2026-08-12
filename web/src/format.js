// Numbers the way a person scans them. Integers keep their thousands
// separators because "1,056,320 rows" is the exactness the page is selling;
// floats are cut to the digits that could change a reading of them.
export function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "—";
    if (Number.isInteger(v)) return v.toLocaleString("en-US");
    const a = Math.abs(v);
    if (a >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
    if (a >= 1) return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
    return v.toLocaleString("en-US", { maximumFractionDigits: 4 });
  }
  return String(v);
}

export function pctLabel(v) {
  return v === null || v === undefined ? "—" : `${v}%`;
}
