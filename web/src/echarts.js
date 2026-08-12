// ECharts, tree-shaken: only the chart types this page draws. The full
// bundle is ~1 MB of parsed JS; registering the pieces keeps the build to
// roughly half, and the import list doubles as documentation of what the
// Explore tab can render.
import * as echarts from "echarts/core";
import {
  BarChart, BoxplotChart, HeatmapChart, LineChart, PieChart, ScatterChart,
} from "echarts/charts";
import {
  GridComponent, LegendComponent, TooltipComponent, VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  BarChart, BoxplotChart, HeatmapChart, LineChart, PieChart, ScatterChart,
  GridComponent, LegendComponent, TooltipComponent, VisualMapComponent,
  CanvasRenderer,
]);

export default echarts;
