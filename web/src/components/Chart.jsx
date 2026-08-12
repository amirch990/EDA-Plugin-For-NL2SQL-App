import React, { useEffect, useRef } from "react";
import echarts from "../echarts.js";

// One ECharts instance per mounted chart, resized with its container and
// disposed with it. The option is replaced wholesale (`notMerge: true`) —
// merging a bar option into a leftover scatter is how charts end up wearing
// two axes from different lives.
export default function Chart({ option, height = 430, onInit }) {
  const el = useRef(null);
  const chart = useRef(null);

  useEffect(() => {
    const c = echarts.init(el.current);
    chart.current = c;
    if (onInit) onInit(c);                 // lets the parent offer "save as PNG"
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); c.dispose(); };
  }, []);

  useEffect(() => {
    if (chart.current && option) chart.current.setOption(option, true);
  }, [option]);

  return <div ref={el} style={{ width: "100%", height }} />;
}
