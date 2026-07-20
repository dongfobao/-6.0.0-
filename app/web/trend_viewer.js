(function overallTrendViewer() {
  const TARGET_HOST = "overallChartHost";
  const ECHARTS_SRC = "./vendor/echarts.min.js";
  let echartsReady = null;
  let chart = null;
  const externalCharts = new Map();
  let payload = null;
  let selectionState = { startPercent: 0, endPercent: 100 };
  let history = [];
  let lastPayloadSignature = "";

  function ensureEcharts() {
    if (window.echarts) return Promise.resolve(window.echarts);
    if (echartsReady) return echartsReady;
    echartsReady = new Promise((resolve, reject) => {
      const existing = document.querySelector('script[data-echarts-vendor="1"]');
      if (existing) {
        existing.addEventListener("load", () => resolve(window.echarts), { once: true });
        existing.addEventListener("error", reject, { once: true });
        return;
      }
      const script = document.createElement("script");
      script.src = ECHARTS_SRC;
      script.dataset.echartsVendor = "1";
      script.onload = () => resolve(window.echarts);
      script.onerror = reject;
      document.head.appendChild(script);
    });
    return echartsReady;
  }

  function toDate(value) {
    const date = value instanceof Date ? value : new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatTime(value) {
    const date = toDate(value);
    if (!date) return "--";
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const hh = String(date.getHours()).padStart(2, "0");
    const mi = String(date.getMinutes()).padStart(2, "0");
    const ss = String(date.getSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
  }

  function formatNumber(value, digits = 2) {
    const number = Number(value);
    if (Number.isNaN(number)) return "--";
    return number.toFixed(digits);
  }

  function disposeExternalChart(hostId) {
    const existing = externalCharts.get(hostId);
    if (existing) {
      existing.chart.dispose();
      externalCharts.delete(hostId);
    }
  }

  function getExternalChartState(hostId) {
    return externalCharts.get(hostId) || null;
  }

  function seriesValue(row, key) {
    const rawValue = row ? row[key] : null;
    if (rawValue === null || rawValue === undefined || rawValue === "") return null;
    const value = Number(rawValue);
    return Number.isFinite(value) ? value : null;
  }

  function buildStandardOption(nextPayload) {
    const points = nextPayload.points || [];
    const seriesMeta = nextPayload.series || [];
    const units = [];
    const minSpanByUnit = {
      "°C": 1,
      "%": 3,
      "kPa": 0.5,
      "L/min": 2,
    };
    seriesMeta.forEach((item) => {
      const unit = item.unit || "";
      if (!units.includes(unit)) units.push(unit);
    });
    const axisExtents = units.map((unit) => {
      const values = [];
      seriesMeta
        .filter((item) => (item.unit || "") === unit)
        .forEach((item) => {
          points.forEach((row) => {
            const value = seriesValue(row, item.key);
            if (value !== null) values.push(value);
          });
        });
      if (!values.length) {
        return { min: null, max: null };
      }
      const rawMin = Math.min(...values);
      const rawMax = Math.max(...values);
      const rawSpan = rawMax - rawMin;
      const minSpan = minSpanByUnit[unit] || 1;
      const targetSpan = Math.max(rawSpan * 1.2, minSpan);
      const center = (rawMin + rawMax) / 2;
      return {
        min: Number((center - targetSpan / 2).toFixed(4)),
        max: Number((center + targetSpan / 2).toFixed(4)),
      };
    });
    const yAxes = units.map((unit, index) => ({
      type: "value",
      name: unit || `Y${index + 1}`,
      scale: false,
      min: axisExtents[index]?.min ?? undefined,
      max: axisExtents[index]?.max ?? undefined,
      position: index % 2 === 0 ? "left" : "right",
      offset: index < 2 ? 0 : (Math.floor(index / 2) * 40),
      axisLabel: { color: "#6f7b7f" },
      axisLine: { show: true, lineStyle: { color: "#9aa6ac" } },
      splitLine: index === 0 ? { lineStyle: { color: "rgba(31,42,48,0.10)" } } : { show: false },
      nameTextStyle: { color: "#6f7b7f", padding: [0, 0, 4, 0] },
    }));
    const mainYAxisIndex = 0;
    const eventSeries = (nextPayload.events || []).map((item) => {
      const anchorRow = points.find((row) => row.ts >= item.ts) || points[points.length - 1];
      const anchorValue = anchorRow && seriesMeta.length ? anchorRow[seriesMeta[0].key] : null;
      return [item.ts, anchorValue, item.title || item.type || "事件", item.detail || ""];
    }).filter((row) => row[1] !== null && row[1] !== undefined && !Number.isNaN(Number(row[1])));
    return {
      animation: false,
      grid: {
        left: units.length > 1 ? 64 : 52,
        right: Math.max(18, Math.ceil(units.length / 2) * 48),
        top: 40,
        bottom: 88,
        containLabel: true,
      },
      legend: {
        top: 0,
        type: "scroll",
        textStyle: { color: "#49545a" },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        confine: true,
      },
      toolbox: {
        right: 0,
        feature: {
          dataZoom: { yAxisIndex: "none" },
          restore: {},
          saveAsImage: {},
        },
      },
      xAxis: {
        type: "time",
        boundaryGap: false,
        axisLabel: { color: "#6f7b7f" },
      },
      yAxis: yAxes,
      dataZoom: [
        { type: "inside", xAxisIndex: 0, filterMode: "filter" },
        { type: "slider", xAxisIndex: 0, filterMode: "filter", height: 24, bottom: 18 },
      ],
      series: [
        ...seriesMeta.map((item) => ({
          name: item.label,
          type: "line",
          yAxisIndex: Math.max(0, units.indexOf(item.unit || "")),
          showSymbol: false,
          connectNulls: false,
          smooth: false,
          sampling: "average",
          lineStyle: { width: 2, color: item.color || "#2c6d76" },
          emphasis: { focus: "series" },
          data: points.map((row) => {
            return [row.ts, seriesValue(row, item.key)];
          }).filter((row) => row[1] !== null),
        })),
        ...(eventSeries.length ? [{
          name: "事件",
          type: "scatter",
          yAxisIndex: mainYAxisIndex,
          symbolSize: 8,
          itemStyle: { color: "#b93030" },
          tooltip: {
            trigger: "item",
            formatter(params) {
              const data = params.data || [];
              const detail = data[3] ? `<br>${escapeHtml(data[3])}` : "";
              return `${formatTime(data[0])}<br>${escapeHtml(data[2] || "事件")}${detail}`;
            },
          },
          data: eventSeries,
        }] : []),
      ],
    };
  }

  function renderStandardChartStable(hostId, rawPayload) {
    const host = document.getElementById(hostId);
    if (!host) return;
    const nextPayload = normalize(rawPayload);
    if (!nextPayload.points.length || !(nextPayload.series || []).length) {
      disposeExternalChart(hostId);
      host.innerHTML = `<div class="empty-state">当前时间窗内还没有实时曲线数据。</div>`;
      return;
    }
    ensureEcharts().then(() => {
      let state = getExternalChartState(hostId);
      let chartHost = document.getElementById(`${hostId}__echart`);
      if (!state || !chartHost) {
        host.innerHTML = `<div class="echart-trend-host live-echart-trend-host" id="${hostId}__echart"></div>`;
        chartHost = document.getElementById(`${hostId}__echart`);
        if (!chartHost) return;
        const nextChart = window.echarts.init(chartHost, null, { renderer: "canvas" });
        state = { chart: nextChart, zoom: { start: 0, end: 100 } };
        nextChart.on("datazoom", () => {
          const option = nextChart.getOption();
          const zoom = option.dataZoom?.[0];
          if (!zoom) return;
          state.zoom = {
            start: Number(zoom.start ?? 0),
            end: Number(zoom.end ?? 100),
          };
        });
        externalCharts.set(hostId, state);
      }
      state.chart.resize();
      state.chart.setOption(buildStandardOption(nextPayload), true);
      state.chart.dispatchAction({
        type: "dataZoom",
        start: state.zoom?.start ?? 0,
        end: state.zoom?.end ?? 100,
      });
    }).catch((error) => {
      host.innerHTML = `<div class="parameter-placeholder">ECharts 加载失败：${escapeHtml(error.message || String(error))}</div>`;
    });
  }

  function normalize(rawPayload) {
    return {
      ...rawPayload,
      points: (rawPayload?.points || [])
        .map((row) => ({ ...row, ts: toDate(row.ts) }))
        .filter((row) => row.ts)
        .sort((a, b) => a.ts - b.ts),
      events: (rawPayload?.events || [])
        .map((row) => ({ ...row, ts: toDate(row.ts) }))
        .filter((row) => row.ts)
        .sort((a, b) => a.ts - b.ts),
    };
  }

  function payloadSignature(nextPayload) {
    return JSON.stringify({
      pointCount: nextPayload?.points?.length || 0,
      eventCount: nextPayload?.events?.length || 0,
      firstTs: nextPayload?.points?.[0]?.ts ? nextPayload.points[0].ts.getTime() : 0,
      lastTs: nextPayload?.points?.length ? nextPayload.points[nextPayload.points.length - 1].ts.getTime() : 0,
      series: (nextPayload?.series || []).map((item) => item.key),
    });
  }

  function getWindowPoints() {
    if (!payload?.points?.length) return [];
    const maxIndex = payload.points.length - 1;
    const startIndex = Math.max(0, Math.floor((selectionState.startPercent / 100) * maxIndex));
    const endIndex = Math.max(startIndex, Math.ceil((selectionState.endPercent / 100) * maxIndex));
    return payload.points.slice(startIndex, endIndex + 1);
  }

  function getWindowEvents(points) {
    if (!points.length) return [];
    return payload.events.filter((item) => item.ts >= points[0].ts && item.ts <= points[points.length - 1].ts);
  }

  function computeStats(points, series) {
    return series.map((item) => {
      const values = points.map((row) => Number(row[item.key])).filter((value) => !Number.isNaN(value));
      if (!values.length) {
        return { ...item, min: null, max: null, avg: null, delta: null };
      }
      return {
        ...item,
        min: Math.min(...values),
        max: Math.max(...values),
        avg: values.reduce((sum, value) => sum + value, 0) / values.length,
        delta: values[values.length - 1] - values[0],
      };
    });
  }

  function buildDetailPanel(points, events) {
    const stats = computeStats(points, payload.series || []);
    const sampleStep = Math.max(1, Math.floor(points.length / 30));
    const sampleRows = points.filter((_, index) => index % sampleStep === 0).slice(0, 30);
    return `
      <div class="trend-stats-card">
        <div class="trend-stats-head">
          <strong>总体曲线选段</strong>
          <span>${points.length} 点 / ${events.length} 事件</span>
        </div>
        <div class="trend-stats-range">${escapeHtml(formatTime(points[0]?.ts))} ~ ${escapeHtml(formatTime(points[points.length - 1]?.ts))}</div>
        <div class="trend-stats-grid">
          ${stats.map((item) => `
            <div class="trend-stat-item">
              <div class="trend-stat-title">${escapeHtml(item.label)} (${escapeHtml(item.unit || "")})</div>
              <div>最小 ${escapeHtml(formatNumber(item.min))}</div>
              <div>最大 ${escapeHtml(formatNumber(item.max))}</div>
              <div>平均 ${escapeHtml(formatNumber(item.avg))}</div>
              <div>变化 ${escapeHtml(formatNumber(item.delta))}</div>
            </div>
          `).join("")}
        </div>
        <div class="trend-records-wrap">
          <div class="trend-records-panel">
            <div class="trend-records-title">该时段采样记录</div>
            <div class="trend-records-table-wrap">
              <table class="trend-records-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    ${stats.map((item) => `<th>${escapeHtml(item.label)}</th>`).join("")}
                  </tr>
                </thead>
                <tbody>
                  ${sampleRows.map((row) => `
                    <tr>
                      <td>${escapeHtml(formatTime(row.ts))}</td>
                      ${stats.map((item) => `<td>${escapeHtml(formatNumber(row[item.key]))}</td>`).join("")}
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
          </div>
          <div class="trend-records-panel">
            <div class="trend-records-title">该时段事件记录</div>
            <div class="trend-event-list">
              ${events.length ? events.slice(0, 60).map((item) => `
                <div class="trend-event-item">
                  <div class="trend-event-time">${escapeHtml(formatTime(item.ts))}</div>
                  <div class="trend-event-body">
                    <strong>${escapeHtml(item.title || item.type || "事件")}</strong>
                    <div>${escapeHtml(item.detail || "")}</div>
                  </div>
                </div>
              `).join("") : '<div class="parameter-placeholder">该时段没有事件。</div>'}
            </div>
          </div>
        </div>
      </div>
    `;
  }

  function renderShell(host) {
    host.innerHTML = `
      <div class="trend-viewer-shell">
        <div class="trend-toolbar">
          <div class="trend-toolbar-group">
            <button class="mini-btn" data-overall-action="reset">返回全时段</button>
            <button class="mini-btn" data-overall-action="back">上一步</button>
          </div>
          <div class="trend-toolbar-hint">总体曲线已切换到标准趋势查看器。用图内缩放或底部滑条选择时段。</div>
        </div>
        <div id="overallTrendEchart" class="echart-trend-host"></div>
        <div id="overallTrendDetails"></div>
      </div>
    `;
  }

  function buildOption() {
    const points = payload.points;
    const xData = points.map((row) => row.ts);
    const eventSeries = payload.events.map((item) => [item.ts, 0, item.title || item.type || "事件"]);
    return {
      animation: false,
      grid: { left: 58, right: 28, top: 24, bottom: 110 },
      legend: {
        top: 0,
        textStyle: { color: "#49545a" },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
      },
      toolbox: {
        right: 0,
        feature: {
          dataZoom: { yAxisIndex: "none" },
          restore: {},
        },
      },
      xAxis: {
        type: "time",
        boundaryGap: false,
        axisLabel: { color: "#6f7b7f" },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: "#6f7b7f" },
        splitLine: { lineStyle: { color: "rgba(31,42,48,0.10)" } },
      },
      dataZoom: [
        { type: "inside", xAxisIndex: 0, filterMode: "filter" },
        { type: "slider", xAxisIndex: 0, filterMode: "filter", height: 24, bottom: 34 },
      ],
      series: [
        ...(payload.series || []).map((item) => ({
          name: item.label,
          type: "line",
          showSymbol: false,
          smooth: false,
          lineStyle: { width: 2, color: item.color || "#2c6d76" },
          emphasis: { focus: "series" },
          data: points.map((row) => [row.ts, row[item.key]]),
        })),
        {
          name: "事件点",
          type: "scatter",
          yAxisIndex: 0,
          symbolSize: 7,
          itemStyle: { color: "#b93030" },
          tooltip: {
            trigger: "item",
            formatter(params) {
              const data = params.data || [];
              return `${formatTime(data[0])}<br>${escapeHtml(data[2] || "事件")}`;
            },
          },
          data: eventSeries,
        },
      ],
    };
  }

  function syncDetails() {
    const host = document.getElementById("overallTrendDetails");
    if (!host || !payload) return;
    const points = getWindowPoints();
    const events = getWindowEvents(points);
    host.innerHTML = buildDetailPanel(points, events);
  }

  function bindToolbar() {
    const root = document.getElementById(TARGET_HOST);
    if (!root) return;
    root.querySelectorAll("[data-overall-action]").forEach((button) => {
      button.addEventListener("click", () => {
        if (!chart) return;
        if (button.dataset.overallAction === "reset") {
          history.push({ ...selectionState });
          selectionState = { startPercent: 0, endPercent: 100 };
          chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
          syncDetails();
          return;
        }
        if (button.dataset.overallAction === "back") {
          const previous = history.pop();
          if (!previous) return;
          selectionState = previous;
          chart.dispatchAction({ type: "dataZoom", start: previous.startPercent, end: previous.endPercent });
          syncDetails();
        }
      });
    });
  }

  function renderChart() {
    const host = document.getElementById(TARGET_HOST);
    if (!host || !payload?.points?.length) return;
    renderShell(host);
    const chartHost = document.getElementById("overallTrendEchart");
    if (chart) {
      chart.dispose();
      chart = null;
    }
    chart = window.echarts.init(chartHost, null, { renderer: "canvas" });
    chart.setOption(buildOption(), true);
    chart.off("datazoom");
    chart.on("datazoom", () => {
      const option = chart.getOption();
      const zoom = option.dataZoom?.[0];
      if (!zoom) return;
      const next = {
        startPercent: Number(zoom.start ?? 0),
        endPercent: Number(zoom.end ?? 100),
      };
      if (next.startPercent !== selectionState.startPercent || next.endPercent !== selectionState.endPercent) {
        history.push({ ...selectionState });
        if (history.length > 20) history.shift();
        selectionState = next;
      }
      syncDetails();
    });
    selectionState = { startPercent: 0, endPercent: 100 };
    history = [];
    syncDetails();
    bindToolbar();
  }

  function register(hostId, rawPayload) {
    if (hostId !== TARGET_HOST) return;
    const nextPayload = normalize(rawPayload);
    const nextSignature = payloadSignature(nextPayload);
    if (nextSignature === lastPayloadSignature) return;
    lastPayloadSignature = nextSignature;
    payload = nextPayload;
    if (!payload.points.length) return;
    ensureEcharts().then(() => {
      renderChart();
    }).catch((error) => {
      const host = document.getElementById(TARGET_HOST);
      if (host) {
        host.innerHTML = `<div class="parameter-placeholder">ECharts 加载失败：${escapeHtml(error.message || String(error))}</div>`;
      }
    });
  }

  function processPending() {
    const pending = window.__PENDING_INTERACTIVE_CHARTS__ || {};
    if (pending[TARGET_HOST]) register(TARGET_HOST, pending[TARGET_HOST]);
  }

  window.__registerInteractiveChart = register;
  window.__renderStandardTrendChart = renderStandardChartStable;

  function boot() {
    processPending();
    window.addEventListener("resize", () => {
      if (chart) chart.resize();
      externalCharts.forEach((item) => item.chart.resize());
    });
  }

  if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
