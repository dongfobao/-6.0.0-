const METRICS = {
  pressure: { label: "压力", unit: "kPa", color: "#b14d2d" },
  temperature: { label: "温度", unit: "°C", color: "#2c6d76" },
  flow: { label: "流速", unit: "L/min", color: "#b07a24" },
  humidity: { label: "湿度", unit: "%", color: "#4f7c55" },
};

const STATE_LABELS = {
  "-1": "未定义",
  0: "呼气",
  1: "吸气",
  2: "无呼吸",
  3: "低流速告警",
  4: "高流速告警",
};

const RHYTHM_LABELS = {
  0: "普通采样",
  1: "状态切换",
  2: "呼吸段开始",
  3: "呼吸段结束",
};

const BREATH_STATE_META = {
  "-1": { label: "未定义", color: "#94a3b8", detail: "系统初始状态，尚未进入有效呼吸判定" },
  0: { label: "呼气", color: "#16a34a", detail: "低于呼气判定下界，但还没有触发低报警" },
  1: { label: "吸气", color: "#2563eb", detail: "高于吸气判定上界，但还没有触发高报警" },
  2: { label: "无呼吸", color: "#9ca3af", detail: "流速落在死区范围内，接近无明显气流" },
  3: { label: "低流速告警", color: "#ea580c", detail: "流速低于低报警阈值，属于过度呼气告警" },
  4: { label: "高流速告警", color: "#dc2626", detail: "流速高于高报警阈值，属于过度吸气告警" },
};

const EVENT_TYPES = {
  valve: { label: "阀门开关", color: "#1d4ed8" },
  breath: { label: "呼吸事件", color: "#0f766e" },
  alarm: { label: "报警/错误", color: "#dc2626" },
  system: { label: "系统事件", color: "#7c3aed" },
};

const EVENT_COLORS = {
  valve:      { CH1: "#1d4ed8", CH2: "#2563eb", CHT: "#0284c7", DRAIN: "#0891b2", "12V": "#0ea5e9", "220V": "#38bdf8", ALARM_OUT: "#6366f1", other: "#1d4ed8" },
  alarm:      { critical: "#dc2626", warning: "#f97316", info: "#e11d48", other: "#dc2626" },
  breath:     { alert: "#059669", normal: "#0f766e", other: "#14b8a6" },
  system:     { other: "#7c3aed" },
};

const LIVE_PARAMETER_GROUPS = [
  { key: "control", label: "控制参数", tone: "control" },
  { key: "config", label: "配置参数", tone: "config" },
  { key: "task", label: "任务参数", tone: "task" },
];

const ENV_ROW_RE = /^\[(?<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\],\/\*\s*(?<pressure>[-\d.]+),(?<temperature>[-\d.]+),(?<flow>[-\d.]+),(?<humidity>[-\d.]+),?\s*\*\//;
const RUN_ROW_RE = /^(?<level>[IWE])\/YLDQ\s+\[(?<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(?<message>.*)$/;
const RUN_CONTROL_CHANNELS = {
  CH1: { channel: "CH1", label: "通道一加热" },
  HEATCHANNEL1: { channel: "CH1", label: "通道一加热" },
  HEAT_CHANNEL_1: { channel: "CH1", label: "通道一加热" },
  HTC1: { channel: "CH1", label: "通道一加热" },
  CH2: { channel: "CH2", label: "通道二加热" },
  HEATCHANNEL2: { channel: "CH2", label: "通道二加热" },
  HEAT_CHANNEL_2: { channel: "CH2", label: "通道二加热" },
  HTC2: { channel: "CH2", label: "通道二加热" },
  CHT: { channel: "CHT", label: "防冻" },
  HCT: { channel: "CHT", label: "防冻" },
  ANTIFREEZE: { channel: "CHT", label: "防冻" },
  DRAIN: { channel: "DRAIN", label: "阀门" },
  VALVE: { channel: "DRAIN", label: "阀门" },
  "12V": { channel: "12V", label: "12V" },
  "220V": { channel: "220V", label: "220V" },
  ALARM_OUT: { channel: "ALARM_OUT", label: "报警输出" },
};

const IS_STATIC_REPORT = Boolean(window.__STATIC_REPORT__);
const EMBEDDED_ANALYSIS = window.__ANALYSIS__ || null;

const uiState = {
  currentView: "import",
  analysis: null,
  sourceData: null,
  runtimeAvailable: false,
  importedLocal: false,
  configPayload: null,
  envMetric: "pressure",
  runFilter: "all",
  selectedMetrics: new Set(["temperature", "humidity", "flow"]),
  selectedEventTypes: new Set(["valve", "breath", "alarm", "system"]),
  masterFilter: {
    selectedDate: "all",
    start: null,
    end: null,
  },
  masterFilterHistory: [],
  activeTab: {
    live: "device-settings",
    master: "overlay",
    environment: "overlay",
    breath: "flow",
    run: "charts",
  },
  simulation: {
    defaults: null,
    presets: [],
    params: null,
    selectedPreset: "recommended",
    result: null,
    running: false,
  },
  originalConfig: {},
  live: {
    devicesPayload: { ok: true, devices: [], selectedDeviceId: null, profiles: [] },
    catalogPayload: { ok: true, catalog: [], summary: null },
    sessionStatus: { ok: true, session: { running: false, selected_device_id: null, sample_counts: {} } },
    snapshotPayload: { ok: true, snapshot: { device: null, metrics: [], statuses: [], session: { running: false } } },
    seriesPayload: { ok: true, series: { rows: [] } },
    eventsPayload: { ok: true, events: [] },
    trafficPayload: { ok: true, traffic: [] },
    parametersPayload: { ok: true, sections: { control: [], config: [], task: [] } },
    metaPayload: { ok: true, meta: { available: false, session: { running: false } } },
    deviceStatuses: {},
    lastExportDir: "",
    selectedDeviceId: null,
    selectedDeviceDraft: null,
    curveWindowMinutes: 5,
    visibleMetrics: new Set(["pressure", "temperature", "flow", "humidity"]),
    parameterDrafts: {},
    parameterEditingId: null,
    pollTimer: null,
    pollBusy: false,
    parameterPollBusy: false,
    debugDraft: {
      deviceId: null,
      requestHex: "",
      appendCrc: true,
      expectResponse: true,
      responseTimeoutMs: 1200,
    },
    debugResult: null,
  },
};

function qs(id) {
  return document.getElementById(id);
}

function qsa(selector) {
  return Array.from(document.querySelectorAll(selector));
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeSelectorValue(value) {
  if (window.CSS && typeof window.CSS.escape === "function") {
    return window.CSS.escape(String(value));
  }
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function getRunControlChannel(token) {
  const key = String(token || "").replace(/[\s-]/g, "_").toUpperCase();
  return RUN_CONTROL_CHANNELS[key] || null;
}

function buildRunControlEvent(row, match, channelTokenIndex, actionTokenIndex, extraTitle = "") {
  const meta = getRunControlChannel(match[channelTokenIndex]);
  if (!meta) return null;
  const actionToken = String(match[actionTokenIndex] || "").toLowerCase();
  const action = /^(open|on)$/.test(actionToken) ? "打开" : "关闭";
  const titleExtra = extraTitle ? ` ${extraTitle}` : "";
  return {
    ts: row.timestamp,
    type: "valve",
    severity: row.level === "E" ? "critical" : row.level === "W" ? "warning" : "info",
    title: `${meta.label}${titleExtra} ${action}`,
    detail: row.message || "",
    channel: meta.channel,
    source: `${row.source_file}:${row.line_number}`,
    level: row.level,
    valveChannel: meta.channel,
    valveAction: action,
  };
}

function normalizeRunControlEvent(row) {
  const message = row.message || "";
  const patterns = [
    { re: /\b(CH1|CH2|CHT|HCT|DRAIN|12V|220V|ALARM_OUT|HTC1|HTC2)\b.*\b(open|close)\b/i, channel: 1, action: 2 },
    { re: /\b(HeatChannel1|HeatChannel2|Antifreeze|Valve)\s*--\s*(open|close)\b/i, channel: 1, action: 2 },
    { re: /\bONLINE\s*(open|close)\s+([A-Za-z0-9_]+)\b/i, channel: 2, action: 1, extra: "在线检测" },
    { re: /\b(ANTIFREEZE|VALVE)\s+(ON|OFF)\b/i, channel: 1, action: 2 },
    { re: /\b(VALVE)\s+(PULSE|FAN)\s+(ON|OFF)\b/i, channel: 1, action: 3, extraIndex: 2 },
  ];
  for (let i = 0; i < patterns.length; i += 1) {
    const item = patterns[i];
    const match = message.match(item.re);
    if (match) {
      const extraTitle = item.extra || (item.extraIndex ? match[item.extraIndex] : "");
      return buildRunControlEvent(row, match, item.channel, item.action, extraTitle);
    }
  }
  return null;
}

function setStatus(text) {
  var el = qs("statusText");
  if (el) el.textContent = text;
  var dot = qs("statusDot");
  if (dot) {
    dot.className = "status-dot";
    if (/失败|错误|error|fail/i.test(text)) dot.classList.add("error");
    else if (/未|加载|读取/i.test(text)) dot.classList.add("warn");
  }
}

function setImportSummary(text) {
  qs("importSummary").textContent = text;
}

function setConfigEditorStatus(text) {
  qs("configEditorStatus").textContent = text;
}

function setConfigSnapshotStatus(text) {
  var el = qs("configSnapshotStatus");
  if (el) el.textContent = text;
}

function clearRenderedViews() {
  [
    "overviewCards",
    "overviewSummaryBoard",
    "insightsList",
    "overallChartHost",
    "accumulationChartHost",
    "masterSummary",
    "masterEventList",
    "envChart",
    "completenessChart",
    "thresholdChart",
    "envDailyTable",
    "breathFlowChart",
    "breathStateChart",
    "breathRhythmChart",
    "breathSummaryBoard",
    "breathEventList",
    "runDailyChart",
    "runKeywordChart",
    "runTimeline",
    "runLogTable",
    "configSnapshot",
    "qualityPanel",
    "configEditor",
  ].forEach((id) => {
    const node = qs(id);
    if (node) node.innerHTML = "";
  });
}

function resetLoadedData(message = "当前已清空，请重新导入数据。") {
  uiState.analysis = null;
  uiState.sourceData = null;
  uiState.masterModel = null;
  uiState.runtimeAvailable = false;
  uiState.importedLocal = false;
  uiState.originalConfig = {};
  uiState.configPayload = { config: {}, schema: [], editable: false };
  uiState.runFilter = "all";
  uiState.selectedMetrics = new Set(["temperature", "humidity", "flow"]);
  uiState.selectedEventTypes = new Set(["valve", "breath", "alarm", "system"]);
  uiState.masterFilter = { selectedDate: "all", start: null, end: null };
  uiState.envFilter = { search: "", start: null, end: null };
  uiState.breathFilter = { ...uiState.breathFilter, search: "", state: "all", rhythm: "all", start: null, end: null, page: 1 };
  uiState.breathFilterHistory = [];
  uiState.runQueryFilter = { ...uiState.runQueryFilter, search: "", level: "all", start: null, end: null, page: 1 };
  clearRenderedViews();
  renderImportRecognition(null);
  setImportSummary(message);
  setStatus("当前没有已加载的数据。");
  setConfigEditorStatus("当前没有可编辑配置，请先读取运行目录或重新导入数据。");
  if (qs("datePresetSelect")) qs("datePresetSelect").innerHTML = `<option value="all">全部日期</option>`;
  [
    "rangeStartInput",
    "rangeEndInput",
    "envRangeStartInput",
    "envRangeEndInput",
    "breathRangeStartInput",
    "breathRangeEndInput",
    "runRangeStartInput",
    "runRangeEndInput",
  ].forEach((id) => {
    if (qs(id)) qs(id).value = "";
  });
  [
    "runSearchInput",
  ].forEach((id) => {
    if (qs(id)) qs(id).value = "";
  });
  if (qs("breathRhythmFilter")) qs("breathRhythmFilter").innerHTML = `<option value="all">全部节律</option>`;
  if (qs("runLevelFilter")) qs("runLevelFilter").value = "all";
  if (qs("breathPageInfo")) qs("breathPageInfo").textContent = "第 1 / 1 页";
  if (qs("runPageInfo")) qs("runPageInfo").textContent = "第 1 / 1 页";
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Number(value).toFixed(digits);
}

function formatDateTime(value) {
  if (!value) return "-";
  if (value instanceof Date) return toLocalDateTimeText(value);
  return String(value).replace("T", " ");
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "-";
  if (seconds >= 3600) return `${formatNumber(seconds / 3600, 1)} 小时`;
  if (seconds >= 60) return `${formatNumber(seconds / 60, 1)} 分钟`;
  return `${formatNumber(seconds, 1)} 秒`;
}

function toDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  return new Date(String(value).replace(" ", "T"));
}

function toIsoText(date) {
  if (!date) return null;
  return toLocalDateTimeText(date);
}

function toLocalDateTimeText(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function toDateInputValue(date) {
  if (!date) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function mean(values) {
  if (!values.length) return null;
  return values.reduce((sum, item) => sum + item, 0) / values.length;
}

function minMax(values, fallback = null) {
  if (!values.length) return { min: fallback, max: fallback };
  let min = values[0];
  let max = values[0];
  for (let i = 1; i < values.length; i += 1) {
    const value = values[i];
    if (value < min) min = value;
    if (value > max) max = value;
  }
  return { min, max };
}

function maxOf(values, fallback = null) {
  if (!values.length) return fallback;
  let max = values[0];
  for (let i = 1; i < values.length; i += 1) {
    if (values[i] > max) max = values[i];
  }
  return max;
}

function percentile(values, q) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] !== undefined
    ? sorted[base] + rest * (sorted[base + 1] - sorted[base])
    : sorted[base];
}

function computeStats(values) {
  if (!values.length) return { min: null, max: null, avg: null, p10: null, p90: null };
  const range = minMax(values);
  return {
    min: Number(range.min.toFixed(2)),
    max: Number(range.max.toFixed(2)),
    avg: Number(mean(values).toFixed(2)),
    p10: Number(percentile(values, 0.1).toFixed(2)),
    p90: Number(percentile(values, 0.9).toFixed(2)),
  };
}

function computeMedianInterval(rows, key = "timestamp", defaultValue = 60) {
  if (rows.length < 2) return defaultValue;
  const diffs = [];
  for (let i = 1; i < rows.length; i += 1) {
    const diff = Math.round((rows[i][key] - rows[i - 1][key]) / 1000);
    if (diff > 0) diffs.push(diff);
  }
  if (!diffs.length) return defaultValue;
  diffs.sort((a, b) => a - b);
  return diffs[Math.floor(diffs.length / 2)];
}

function downsample(rows, maxPoints) {
  if (rows.length <= maxPoints) return rows;
  const step = Math.ceil(rows.length / maxPoints);
  const result = rows.filter((_, index) => index % step === 0);
  if (result[result.length - 1] !== rows[rows.length - 1]) result.push(rows[rows.length - 1]);
  return result;
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url} 返回 ${response.status}`);
  return response.json();
}

async function fetchAnalysis(forceRefresh = false) {
  return fetchJson(`/api/analysis${forceRefresh ? "?refresh=1" : ""}`);
}

async function fetchSimulationDefaults(forceRefresh = false) {
  return fetchJson(`/api/simulation/defaults${forceRefresh ? "?refresh=1" : ""}`);
}

async function runSimulationScenario(params) {
  const rawData = uiState.analysis?.raw_data || {};
  const config = uiState.sourceData?.config || uiState.analysis?.config || {};
  const response = await fetch("/api/simulation/run", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({
      rawData,
      config,
      scenarios: [{ id: "active", name: "当前模拟", params }],
    }),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || `模拟失败: ${response.status}`);
  }
  return payload;
}

async function fetchConfigPayload() {
  return fetchJson("/api/config");
}

async function saveConfigPayload(config) {
  const response = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ config }),
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message || `保存失败: ${response.status}`);
  }
  return payload;
}

async function fetchPreviewConfigRecommendations(config, history, schema) {
  const response = await fetch("/api/parameter-recommendations-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ config, history, schema, strategy: "balanced" }),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || `生成失败: ${response.status}`);
  }
  return payload;
}

async function fetchLiveDevices() {
  return fetchJson("/api/live/devices");
}

async function fetchLiveCatalog() {
  return fetchJson("/api/live/catalog");
}

function buildLiveQuery(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  });
  const queryText = query.toString();
  return queryText ? `${path}?${queryText}` : path;
}

async function fetchLiveSessionStatus(deviceId) {
  return fetchJson(buildLiveQuery("/api/live/session/status", { deviceId }));
}

async function fetchLiveSnapshot(deviceId) {
  return fetchJson(buildLiveQuery("/api/live/snapshot", { deviceId }));
}

async function fetchLiveSeries(windowMinutes = 5, deviceId) {
  const minutes = Math.max(1, Number(windowMinutes) || 5);
  const limit = Math.min(2000, Math.max(600, Math.ceil(minutes * 60) + 60));
  return fetchJson(buildLiveQuery("/api/live/series", {
    deviceId,
    windowMs: minutes * 60 * 1000,
    limit,
  }));
}

async function fetchLiveEvents(deviceId) {
  return fetchJson(buildLiveQuery("/api/live/events", { deviceId, limit: 80 }));
}

async function fetchLiveTraffic() {
  return fetchJson(buildLiveQuery("/api/live/traffic", { limit: 160 }));
}

async function clearLiveTraffic() {
  return fetchJson("/api/live/traffic/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({}),
  });
}

async function fetchLiveParameters(deviceId) {
  return fetchJson(buildLiveQuery("/api/live/parameters", { deviceId }));
}

async function fetchLivePollParameters(deviceId) {
  return fetchJson("/api/live/poll-parameters", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ deviceId }),
  });
}

async function fetchAllDeviceStatuses() {
  return fetchJson("/api/live/session/all-device-statuses");
}

async function downloadLiveDevicesConfig() {
  const response = await fetch("/api/live/devices/export");
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      message = payload?.message || message;
    } catch (error) {
      // Ignore parse failures and keep status message.
    }
    throw new Error(message);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "live_devices.json";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function importLiveDevicesConfig(config) {
  return fetchJson("/api/live/devices/import", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ config }),
  });
}

async function fetchLiveSessionMeta(deviceId) {
  return fetchJson(buildLiveQuery("/api/live/session/meta", { deviceId }));
}

async function writeLiveParameter(deviceId, itemId, value) {
  return fetchJson("/api/live/write", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ deviceId, itemId, value }),
  });
}

async function createLiveDevice(payload) {
  return fetchJson("/api/live/devices", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify(payload || {}),
  });
}

async function updateLiveDevice(deviceId, payload) {
  return fetchJson(`/api/live/devices/${encodeURIComponent(deviceId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify(payload || {}),
  });
}

async function deleteLiveDevice(deviceId) {
  return fetchJson(`/api/live/devices/${encodeURIComponent(deviceId)}`, { method: "DELETE" });
}

async function selectLiveDevice(deviceId) {
  return fetchJson("/api/live/session/select", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ deviceId }),
  });
}

async function startLiveSession() {
  return fetchJson("/api/live/session/start", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({}),
  });
}

async function stopLiveSession() {
  return fetchJson("/api/live/session/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({}),
  });
}

async function shutdownSystem() {
  return fetchJson("/api/shutdown", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
  });
}

async function exportLiveSession(deviceId, targetDir) {
  return fetchJson("/api/live/session/export", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ deviceId, targetDir: targetDir || "" }),
  });
}

async function analyzeLiveSession(deviceId, targetDir) {
  return fetchJson("/api/live/session/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify({ deviceId, targetDir: targetDir || "" }),
  });
}

function getLiveDefaultSession(deviceId = null) {
  return {
    running: false,
    selected_device_id: deviceId,
    sample_counts: { metrics: 0, statuses: 0, controls: 0, parameters: 0, history: 0 },
    request_count: 0,
    error_count: 0,
  };
}

function getLiveDefaultSnapshot(deviceId = null) {
  return {
    ok: true,
    selectedDeviceId: deviceId,
    activeDeviceId: null,
    matchesSelectedDevice: false,
    snapshot: { device: null, deviceId, metrics: [], statuses: [], controls: [], session: getLiveDefaultSession(deviceId) },
  };
}

function getLiveDefaultParameters(deviceId = null) {
  return { ok: true, selectedDeviceId: deviceId, activeDeviceId: null, matchesSelectedDevice: false, sections: { control: [], config: [], task: [] } };
}

function getLiveDefaultTraffic(deviceId = null) {
  return { ok: true, selectedDeviceId: deviceId, activeDeviceId: null, matchesSelectedDevice: false, traffic: [] };
}

function getLiveDefaultMeta(deviceId = null) {
  return {
    ok: true,
    selectedDeviceId: deviceId,
    activeDeviceId: null,
    matchesSelectedDevice: false,
    meta: { available: false, sessionDir: null, lastSnapshot: null, session: getLiveDefaultSession(deviceId) },
  };
}

async function safeLiveRequest(loader, fallbackFactory) {
  try {
    return await loader();
  } catch (error) {
    const fallback = typeof fallbackFactory === "function" ? fallbackFactory(error) : fallbackFactory;
    if (fallback && typeof fallback === "object") fallback.error = error.message;
    return fallback;
  }
}

function setLiveStatusNotice(text) {
  const el = qs("liveStatusNotice");
  if (el) el.textContent = text;
}

function showLiveExportModal(deviceId, deviceName, onExport) {
  const modal = qs("liveExportModal");
  if (!modal) { setLiveStatusNotice("导出弹窗未就绪，请刷新页面后重试。"); return; }
  const deviceEl = qs("liveExportModalDevice");
  const resultEl = qs("liveExportModalResult");
  const exportBtn = qs("liveExportModalExportBtn");
  const cancelBtn = qs("liveExportModalCancelBtn");
  const closeBtn = qs("liveExportModalCloseBtn");
  const input = qs("liveExportModalInput");
  if (!deviceEl || !resultEl || !exportBtn || !cancelBtn || !closeBtn || !input) {
    setLiveStatusNotice("导出弹窗控件未就绪，请刷新页面后重试。");
    return;
  }
  deviceEl.textContent = `设备：${deviceName || "-"}`;
  input.value = uiState.live.lastExportDir || "";
  resultEl.classList.add("hidden");
  resultEl.textContent = "";
  modal.style.display = "flex";
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");

  const close = () => {
    modal.classList.add("hidden");
    modal.style.display = "";
    modal.setAttribute("aria-hidden", "true");
  };

  const doExport = async () => {
    const targetDir = input.value.trim();
    if (!targetDir) { setLiveStatusNotice("请先输入导出目录路径"); return; }
    uiState.live.lastExportDir = targetDir;
    resultEl.classList.remove("hidden");
    resultEl.textContent = "正在导出...";
    try {
      await onExport(targetDir);
      resultEl.textContent = `已导出到：${targetDir}`;
    } catch (error) {
      resultEl.textContent = `导出失败：${error.message}`;
    }
  };

  exportBtn.onclick = doExport;
  cancelBtn.onclick = close;
  closeBtn.onclick = close;
  modal.onclick = (event) => { if (event.target === modal) close(); };
}

function resetLiveProjection(deviceId = uiState.live.selectedDeviceId) {
  uiState.live.sessionStatus = {
    ok: true,
    selectedDeviceId: deviceId || null,
    activeDeviceIds: [],
    activeDeviceId: null,
    matchesSelectedDevice: false,
    selectedDevice: getSelectedLiveDevice(),
    session: { running: false, device_ids: [], device_count: 0 },
    activeSession: { running: false, device_ids: [], device_count: 0 },
    state: { running: false, device_ids: [], device_count: 0 },
  };
  uiState.live.snapshotPayload = getLiveDefaultSnapshot(deviceId || null);
  uiState.live.seriesPayload = { ok: true, selectedDeviceId: deviceId || null, activeDeviceId: null, matchesSelectedDevice: false, series: { rows: [], byMetric: {} } };
  uiState.live.eventsPayload = { ok: true, selectedDeviceId: deviceId || null, activeDeviceId: null, matchesSelectedDevice: false, events: [] };
  uiState.live.trafficPayload = getLiveDefaultTraffic(deviceId || null);
  uiState.live.parametersPayload = getLiveDefaultParameters(deviceId || null);
  uiState.live.metaPayload = getLiveDefaultMeta(deviceId || null);
}

function getLiveSessionNotice() {
  const selected = getSelectedLiveDevice();
  const activeSession = uiState.live.sessionStatus?.activeSession || {};
  const globalRunning = uiState.live.sessionStatus?.state?.running || activeSession.running || false;
  const deviceCount = uiState.live.sessionStatus?.state?.device_count || activeSession.device_count || 0;
  const matchesSelected = uiState.live.sessionStatus?.matchesSelectedDevice;
  if (!selected) return "当前还没有设备。请先新增设备并保存。";
  if (globalRunning) {
    if (matchesSelected) return `采集中 (${deviceCount} 台设备) - 当前显示：${selected.name}`;
    return `采集中 (${deviceCount} 台设备) - 当前选中：${selected.name}`;
  }
  return `已停止 - 当前选中：${selected.name}。可点击"开始全部采集"。`;
}

function refreshLiveStatusNotice() {
  setLiveStatusNotice(getLiveSessionNotice());
}

function pickNumber(...values) {
  for (const value of values) {
    const num = Number(value);
    if (value !== null && value !== undefined && value !== "" && Number.isFinite(num)) return num;
  }
  return null;
}

function normalizeLiveTs(value) {
  const date = toDate(value);
  return date instanceof Date && !Number.isNaN(date.getTime()) ? date : null;
}

function getLiveSnapshotDeviceId(snapshotPayload = uiState.live.snapshotPayload) {
  return snapshotPayload?.snapshot?.deviceId || snapshotPayload?.snapshot?.session?.selected_device_id || null;
}

function isSelectedLiveDeviceAligned(snapshotPayload = uiState.live.snapshotPayload) {
  const selectedId = uiState.live.selectedDeviceId || null;
  const snapshotDeviceId = getLiveSnapshotDeviceId(snapshotPayload);
  if (snapshotPayload?.matchesSelectedDevice === false) return false;
  if (!selectedId) return true;
  if (!snapshotDeviceId) return false;
  return selectedId === snapshotDeviceId;
}

function getSelectedLiveDevice() {
  const devices = uiState.live.devicesPayload?.devices || [];
  return devices.find((item) => item.id === uiState.live.selectedDeviceId) || null;
}

function buildLiveDeviceDraft(device) {
  const draft = clone(device || {
    name: "新设备",
    deviceType: "YLDQ-4.0.6",
    transport: "rtu",
    address: "COM1",
    slaveId: 1,
    baudrate: 9600,
    databits: 8,
    stopbits: 1,
    parity: "N",
    timeoutMs: 1200,
    retryCount: 2,
    pollingProfile: "default-yldq",
    pollingCommands: clone(uiState.live.catalogPayload?.defaultPollingCommands || []),
    enabled: true,
  });
  if (!Array.isArray(draft.pollingCommands) || !draft.pollingCommands.length) {
    draft.pollingCommands = clone(uiState.live.catalogPayload?.defaultPollingCommands || []);
  }
  return draft;
}

function buildLiveDeviceCopyName(baseName) {
  const rawBase = String(baseName || "新设备").trim() || "新设备";
  const normalizedBase = rawBase.replace(/(?:[-\s]副本)(\d+)?$/, "").trim() || "新设备";
  const existingNames = new Set(
    (uiState.live.devicesPayload?.devices || [])
      .map((item) => String(item?.name || "").trim())
      .filter(Boolean)
  );
  let candidate = `${normalizedBase}-副本`;
  let index = 2;
  while (existingNames.has(candidate)) {
    candidate = `${normalizedBase}-副本${index}`;
    index += 1;
  }
  return candidate;
}

function buildLiveNewDeviceDraft() {
  let template = null;
  if (uiState.live.selectedDeviceDraft) {
    try {
      template = collectLiveDeviceDraft();
    } catch (error) {
      template = uiState.live.selectedDeviceDraft;
    }
  } else {
    template = getSelectedLiveDevice();
  }
  const draft = buildLiveDeviceDraft(template || undefined);
  delete draft.id;
  draft.name = buildLiveDeviceCopyName(draft.name);
  return draft;
}

function collectLiveDeviceDraft() {
  const draft = buildLiveDeviceDraft(uiState.live.selectedDeviceDraft || {});
  qsa("#liveDeviceEditor [data-live-field]").forEach((input) => {
    const key = input.dataset.liveField;
    if (!key) return;
    if (input.type === "checkbox") draft[key] = input.checked;
    else if (input.type === "number") draft[key] = Number(input.value);
    else draft[key] = input.value;
  });
  draft.pollingCommands = collectLivePollingCommands();
  if (uiState.live.selectedDeviceDraft?.id) draft.id = uiState.live.selectedDeviceDraft.id;
  return draft;
}

function bindLiveDeviceEditorInputs() {
  qsa("#liveDeviceEditor [data-live-field]").forEach((input) => {
    const eventName = input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input";
    input.addEventListener(eventName, () => {
      uiState.live.selectedDeviceDraft = collectLiveDeviceDraft();
    });
  });
}

function buildLiveMetricMap(snapshotPayload) {
  const map = {};
  const metrics = snapshotPayload?.snapshot?.metrics || [];
  if (!Array.isArray(metrics)) return map;
  metrics.forEach((item) => {
    const raw = String(item?.id || item?.key || item?.name || "").trim();
    const key = raw.includes(".") ? raw.split(".").pop() : raw;
    if (!key) return;
    map[key] = {
      label: item?.label || item?.name || key,
      unit: item?.unit || METRICS[key]?.unit || "",
      value: pickNumber(item?.currentValue, item?.value),
      updatedAt: item?.updatedAt || "",
    };
  });
  return map;
}

function normalizeLiveSeriesRows(seriesPayload, snapshotPayload) {
  if (!isSelectedLiveDeviceAligned(snapshotPayload)) return [];
  const rows = Array.isArray(seriesPayload?.series?.rows) ? seriesPayload.series.rows : [];
  const normalized = rows.map((row) => ({
    timestamp: normalizeLiveTs(row?.ts || row?.timestamp),
    pressure: pickNumber(row?.pressure),
    temperature: pickNumber(row?.temperature),
    flow: pickNumber(row?.flow),
    humidity: pickNumber(row?.humidity),
  })).filter((row) => row.timestamp);
  if (normalized.length) return normalized;
  const ts = normalizeLiveTs(snapshotPayload?.snapshot?.ts || snapshotPayload?.snapshot?.snapshotAt);
  const metricMap = buildLiveMetricMap(snapshotPayload);
  if (!ts) return [];
  const fallback = {
    timestamp: ts,
    pressure: metricMap.pressure?.value ?? null,
    temperature: metricMap.temperature?.value ?? null,
    flow: metricMap.flow?.value ?? null,
    humidity: metricMap.humidity?.value ?? null,
  };
  return Object.keys(METRICS).some((key) => fallback[key] !== null) ? [fallback] : [];
}

function normalizeLiveEvents(eventsPayload, seriesRows) {
  const rows = Array.isArray(eventsPayload?.events) ? eventsPayload.events : [];
  return rows.map((item, index) => {
    const ts = normalizeLiveTs(item?.ts || item?.timestamp);
    if (!ts) return null;
    const typeText = String(item?.type || "system").toLowerCase();
    const type = ["valve", "breath", "alarm", "system"].includes(typeText) ? typeText : "system";
    return {
      id: item?.id || `event-${index}`,
      ts,
      type,
      title: item?.message || item?.title || EVENT_TYPES[type]?.label || type,
      detail: item?.detail || "",
      source: item?.source || "",
    };
  }).filter(Boolean).sort((a, b) => a.ts - b.ts);
}

function formatLiveStatusValue(value) {
  if (value === true) return "开";
  if (value === false) return "关";
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function getLiveStatusTone(item, index) {
  const value = item?.currentValue ?? item?.value;
  if (value === true) return "on";
  if (value === false) return "off";
  return ["warm", "cool", "alert", "mint", "sun"][index % 5];
}

function getLiveDeviceAccent(deviceId) {
  const palette = ["#ef4444", "#2563eb", "#16a34a", "#d97706", "#db2777", "#0891b2"];
  const text = String(deviceId || "default");
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) >>> 0;
  }
  return palette[hash % palette.length];
}

function normalizeLiveTrafficRows(trafficPayload) {
  const rows = Array.isArray(trafficPayload?.traffic) ? trafficPayload.traffic : [];
  return rows.map((item) => {
    const sentAt = item?.sentAt || item?.replyAt || "";
    const replyAt = item?.replyAt || "";
    return {
      id: item?.id || `${item?.traceId || "trace"}-${sentAt}`,
      traceId: item?.traceId || null,
      deviceId: item?.deviceId || "",
      deviceName: item?.deviceName || item?.deviceId || "未知设备",
      port: item?.port || "-",
      slaveId: item?.slaveId ?? "-",
      sentAt,
      replyAt,
      timeText: formatDateTime(replyAt || sentAt || "-"),
      requestHex: item?.requestHex || "-",
      responseHex: item?.responseHex || "",
      requestSummary: item?.requestSummary || "request",
      responseSummary: item?.responseSummary || "",
      status: item?.status || "pending",
      error: item?.error || "",
      accent: getLiveDeviceAccent(item?.deviceId || item?.deviceName || ""),
    };
  });
}

function getLiveAnalogCards() {
  const rows = normalizeLiveSeriesRows(uiState.live.seriesPayload, uiState.live.snapshotPayload);
  const latestRow = rows.length ? rows[rows.length - 1] : null;
  const metricMap = buildLiveMetricMap(uiState.live.snapshotPayload);
  return Object.entries(METRICS).map(([key, meta]) => {
    const value = latestRow?.[key] ?? metricMap[key]?.value;
    return {
      key,
      label: meta.label,
      color: meta.color,
      value: value === null || value === undefined ? "-" : `${formatNumber(value)} ${meta.unit}`,
      detail: metricMap[key]?.updatedAt ? `更新时间 ${formatDateTime(metricMap[key].updatedAt)}` : "等待采集数据",
    };
  });
}

function renderLiveDeviceList() {
  const host = qs("liveDeviceList");
  if (!host) return;
  const devices = uiState.live.devicesPayload?.devices || [];
  if (!devices.length) {
    host.innerHTML = `<div class="empty-state">当前还没有设备。点击“新增设备”后再保存。</div>`;
    return;
  }
  const statuses = uiState.live.deviceStatuses || {};
  host.innerHTML = devices.map((device) => {
    const devStatus = statuses[device.id] || {};
    const health = devStatus.communication_health || "idle";
    let dataClass = "";
    if (device.enabled !== false) {
      if (health === "ok") dataClass = "data-ok";
      else if (health === "error") dataClass = "data-error";
      else if (health === "warn" || health === "pending" || health === "starting") dataClass = "data-pending";
      else dataClass = "data-idle";
    }
    const statusText = device.enabled === false ? "已停用"
      : devStatus.communication_text || (health === "ok" ? "收到数据" : health === "error" ? "通信异常" : devStatus.running ? "等待数据..." : "待采集");
    const statusTitle = [
      devStatus.last_success_at ? `最近成功：${devStatus.last_success_at}` : "",
      devStatus.last_error ? `最近错误：${devStatus.last_error}` : "",
      devStatus.consecutive_error_count ? `连续错误：${devStatus.consecutive_error_count}` : "",
    ].filter(Boolean).join(" | ");
    return `
    <div class="live-device-row ${uiState.live.selectedDeviceId === device.id ? "active" : ""} ${device.enabled !== false ? "enabled" : "disabled"} ${dataClass}">
      <button class="live-device-item" data-live-device-id="${escapeHtml(device.id)}">
        <strong>${escapeHtml(device.name)}</strong>
        <span>${escapeHtml(device.deviceType || "-")}</span>
        <span>${escapeHtml((device.transport || "rtu").toUpperCase())} | ${escapeHtml(device.address || "-")} | 站号 ${escapeHtml(device.slaveId ?? "-")}</span>
        <span class="live-device-status-line" title="${escapeHtml(statusTitle)}">${escapeHtml(statusText)}</span>
      </button>
      <button class="live-device-toggle" data-live-device-toggle="${escapeHtml(device.id)}" title="${device.enabled !== false ? "已启用，点击停用" : "已停用，点击启用"}">
        ${device.enabled !== false ? "●" : "○"}
      </button>
    </div>
  `}).join("");
  qsa("[data-live-device-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      uiState.live.selectedDeviceId = button.dataset.liveDeviceId;
      uiState.live.selectedDeviceDraft = buildLiveDeviceDraft(getSelectedLiveDevice());
      try {
        await selectLiveDevice(uiState.live.selectedDeviceId);
        await refreshLiveRuntimeData();
      } catch (error) {
        setLiveStatusNotice(`切换设备失败：${error.message}`);
      }
      renderLiveView();
      refreshLiveStatusNotice();
    });
  });
  qsa("[data-live-device-toggle]").forEach((toggle) => {
    toggle.addEventListener("click", async (event) => {
      event.stopPropagation();
      const deviceId = toggle.dataset.liveDeviceToggle;
      const device = devices.find((d) => d.id === deviceId);
      if (!device) return;
      const newEnabled = device.enabled === false;
      try {
        await updateLiveDevice(deviceId, { ...device, enabled: newEnabled });
        await refreshLiveModule();
        setLiveStatusNotice(`${device.name} 已${newEnabled ? "启用" : "停用"}`);
      } catch (error) {
        setLiveStatusNotice(`操作失败：${error.message}`);
      }
    });
  });
}

function updateLiveDeviceStatusClasses() {
  const statuses = uiState.live.deviceStatuses || {};
  qsa("[data-live-device-id]").forEach((button) => {
    const deviceId = button.dataset.liveDeviceId;
    const row = button.closest(".live-device-row");
    if (!row) return;
    const devStatus = statuses[deviceId] || {};
    const health = devStatus.communication_health || "idle";
    row.classList.remove("data-ok", "data-error", "data-pending", "data-idle");
    let statusText = "待采集";
    if (row.classList.contains("disabled")) {
      statusText = "已停用";
    } else if (health === "ok") {
      row.classList.add("data-ok");
      statusText = devStatus.communication_text || "收到数据";
    } else if (health === "error") {
      row.classList.add("data-error");
      statusText = devStatus.communication_text || "通信异常";
    } else if (health === "warn" || health === "pending" || health === "starting") {
      row.classList.add("data-pending");
      statusText = devStatus.communication_text || "等待数据...";
    } else {
      row.classList.add("data-idle");
    }
    const line = row.querySelector(".live-device-status-line");
    if (line) {
      line.textContent = statusText;
      line.title = [
        devStatus.last_success_at ? `最近成功：${devStatus.last_success_at}` : "",
        devStatus.last_error ? `最近错误：${devStatus.last_error}` : "",
        devStatus.consecutive_error_count ? `连续错误：${devStatus.consecutive_error_count}` : "",
      ].filter(Boolean).join(" | ");
    }
  });
}

function formatLiveTrafficStatus(status) {
  if (status === "ok") return "已回复";
  if (status === "no_response") return "未回复";
  if (status === "error") return "回复异常";
  if (status === "sent") return "仅发送";
  return "等待回复";
}

function buildLiveTrafficFeed(rows, emptyText = "暂无命令收发日志。", showDevice = true) {
  return rows.length ? rows.map((item) => `
    <article class="live-traffic-item status-${escapeHtml(item.status)}" style="--device-accent:${item.accent}">
      <div class="live-traffic-head">
        <span class="live-traffic-device">${showDevice ? escapeHtml(item.deviceName) : escapeHtml(item.port)}</span>
        <span class="live-traffic-status">${escapeHtml(formatLiveTrafficStatus(item.status))}</span>
      </div>
      <div class="live-traffic-meta">${escapeHtml(item.timeText)} · ${escapeHtml(item.port)} · 站号 ${escapeHtml(item.slaveId)}</div>
      <div class="live-traffic-code tx" title="${escapeHtml(item.requestSummary)}">${escapeHtml(item.requestHex)}</div>
      <div class="live-traffic-code rx ${item.responseHex ? "" : "empty"}" title="${escapeHtml(item.responseSummary || (item.status === "ok" ? "-" : item.error || "未收到回复"))}">${escapeHtml(item.responseHex || (item.status === "sent" ? "仅发送" : item.status === "ok" ? "-" : "无回复"))}</div>
    </article>
  `).join("") : `<div class="empty-state">${emptyText}</div>`;
}

async function sendLiveDebugFrame(payload) {
  return fetchJson("/api/live/debug/send", {
    method: "POST",
    headers: { "Content-Type": "application/json;charset=utf-8" },
    body: JSON.stringify(payload || {}),
  });
}

function getLivePollingCommandsDraft() {
  const draft = uiState.live.selectedDeviceDraft || {};
  if (Array.isArray(draft.pollingCommands) && draft.pollingCommands.length) return draft.pollingCommands;
  return uiState.live.catalogPayload?.defaultPollingCommands || [];
}

function collectLivePollingCommands() {
  const rows = qsa("[data-live-command-row]");
  if (!rows.length) return clone(getLivePollingCommandsDraft());
  return rows.map((row, index) => {
    const pick = (field) => row.querySelector(`[data-live-command-field="${field}"]`);
    const functionCode = Number(pick("functionCode")?.value || 0);
    const address = Number(pick("address")?.value || 0);
    const count = Number(pick("count")?.value || 1);
    return {
      id: row.dataset.liveCommandRow || `cmd-${index + 1}`,
      name: pick("name")?.value || `命令 ${index + 1}`,
      mode: pick("mode")?.value || "modbus_read",
      functionCode,
      area: row.dataset.liveCommandArea || "",
      address,
      count,
      requestHex: pick("requestHex")?.value || "",
      appendCrc: Boolean(pick("appendCrc")?.checked),
      expectResponse: Boolean(pick("expectResponse")?.checked),
      responseMode: pick("responseMode")?.value || "modbus",
      responseTimeoutMs: Number(pick("responseTimeoutMs")?.value || 0) || null,
      autoPoll: Boolean(pick("autoPoll")?.checked),
      delayAfterMs: Number(pick("delayAfterMs")?.value || 0),
      sourceGroup: row.dataset.liveCommandSource || "custom",
      decodeMode: pick("decodeMode")?.value || "catalog",
      catalogItemIds: String(row.dataset.liveCommandItems || "").split(",").filter(Boolean),
    };
  });
}

function buildLiveCommandRequestTemplate(functionCode, address, count) {
  const fc = Number(functionCode || 1);
  const addr = Math.max(0, Number(address || 0));
  const len = Math.max(1, Number(count || 1));
  const hex = (value) => Number(value).toString(16).padStart(2, "0").toUpperCase();
  return `{slaveId} ${hex(fc)} ${hex(addr >> 8)} ${hex(addr & 0xFF)} ${hex(len >> 8)} ${hex(len & 0xFF)}`;
}

function buildLiveNewPollingCommand() {
  const existingCount = getLivePollingCommandsDraft().length;
  return {
    id: `custom-${Date.now()}`,
    name: `自定义命令 ${existingCount + 1}`,
    mode: "raw_hex",
    functionCode: 3,
    area: "raw",
    address: 0,
    count: 1,
    requestHex: "{slaveId} 03 00 00 00 01",
    appendCrc: true,
    expectResponse: true,
    responseMode: "raw",
    responseTimeoutMs: null,
    autoPoll: false,
    delayAfterMs: 500,
    sourceGroup: "custom",
    decodeMode: "none",
    catalogItemIds: [],
  };
}

function normalizeLiveCommandLabel(command) {
  if (command.sourceGroup === "slow") return "参数";
  if (command.sourceGroup === "fast" || command.sourceGroup === "standard") return "默认";
  return "自定义";
}

function renderLiveDeviceEditor() {
  const host = qs("liveDeviceEditor");
  const draft = uiState.live.selectedDeviceDraft;
  if (!host) return;
  if (!draft) {
    host.innerHTML = `<div class="empty-state">请先新增设备，或在左侧选择已有设备。</div>`;
    return;
  }
  host.innerHTML = `
    <div class="live-form-grid">
      <label class="live-field"><span>设备名称</span><input data-live-field="name" value="${escapeHtml(draft.name || "")}"></label>
      <label class="live-field"><span>设备型号</span><input data-live-field="deviceType" value="${escapeHtml(draft.deviceType || "")}"></label>
      <label class="live-field"><span>通讯方式</span>
        <select data-live-field="transport">
          <option value="rtu" ${draft.transport === "rtu" ? "selected" : ""}>Modbus RTU</option>
          <option value="tcp" ${draft.transport === "tcp" ? "selected" : ""}>Modbus TCP</option>
        </select>
      </label>
      <label class="live-field"><span>串口或地址</span><input data-live-field="address" value="${escapeHtml(draft.address || "")}"></label>
      <label class="live-field"><span>站号</span><input data-live-field="slaveId" type="number" min="1" max="247" value="${escapeHtml(draft.slaveId ?? 1)}"></label>
      <label class="live-field"><span>波特率</span><input data-live-field="baudrate" type="number" value="${escapeHtml(draft.baudrate ?? 9600)}"></label>
      <label class="live-field"><span>数据位</span><input data-live-field="databits" type="number" value="${escapeHtml(draft.databits ?? 8)}"></label>
      <label class="live-field"><span>停止位</span><input data-live-field="stopbits" type="number" value="${escapeHtml(draft.stopbits ?? 1)}"></label>
      <label class="live-field"><span>校验位</span>
        <select data-live-field="parity">
          <option value="N" ${draft.parity === "N" ? "selected" : ""}>无校验</option>
          <option value="E" ${draft.parity === "E" ? "selected" : ""}>偶校验</option>
          <option value="O" ${draft.parity === "O" ? "selected" : ""}>奇校验</option>
        </select>
      </label>
      <label class="live-field"><span>超时 (ms)</span><input data-live-field="timeoutMs" type="number" min="100" value="${escapeHtml(draft.timeoutMs ?? 1200)}"></label>
      <label class="live-field"><span>重试次数</span><input data-live-field="retryCount" type="number" min="0" value="${escapeHtml(draft.retryCount ?? 2)}"></label>
      <label class="live-field"><span>轮询配置名</span><input data-live-field="pollingProfile" value="${escapeHtml(draft.pollingProfile || "default-yldq")}"></label>
    </div>
  `;
}

function renderLiveSessionSummary() {
  const host = qs("liveSessionSummary");
  if (!host) return;
  const session = uiState.live.sessionStatus?.session || getLiveDefaultSession();
  const selected = getSelectedLiveDevice();
  const matches = Boolean(uiState.live.sessionStatus?.matchesSelectedDevice);
  const sampleCounts = session.sample_counts || {};
  host.innerHTML = [
    `<div class="summary-item">当前设备：${escapeHtml(selected?.name || "未选择")}</div>`,
    `<div class="summary-item">采集状态：${session.running ? "运行中" : (matches ? "已停止" : "未采集")}</div>`,
    `<div class="summary-item">开始时间：${escapeHtml(session.started_at || "-")}</div>`,
    `<div class="summary-item">最近成功：${escapeHtml(session.last_success_at || "-")}</div>`,
    `<div class="summary-item">请求数 / 错误数：${escapeHtml(session.request_count ?? 0)} / ${escapeHtml(session.error_count ?? 0)}</div>`,
    `<div class="summary-item">指标 / 状态 / 历史点：${escapeHtml(sampleCounts.metrics ?? 0)} / ${escapeHtml(sampleCounts.statuses ?? 0)} / ${escapeHtml(sampleCounts.history ?? 0)}</div>`,
    `<div class="summary-item">最近错误：${escapeHtml(session.last_error || "-")}</div>`,
  ].join("");
}

function renderLiveCatalogSummary() {
  const host = qs("liveCatalogSummary");
  if (!host) return;
  const summary = uiState.live.catalogPayload?.summary;
  if (!summary) {
    host.innerHTML = `<div class="empty-state">点表尚未加载。</div>`;
    return;
  }
  host.innerHTML = [
    `<div class="summary-item">点位总数：${escapeHtml(summary.total ?? 0)}</div>`,
    `<div class="summary-item">可读点位：${escapeHtml(summary.readable ?? 0)}</div>`,
    `<div class="summary-item">可写点位：${escapeHtml(summary.writable ?? 0)}</div>`,
    `<div class="summary-item">线圈 / 离散输入：${escapeHtml(summary.areas?.coil || 0)} / ${escapeHtml(summary.areas?.discrete_input || 0)}</div>`,
    `<div class="summary-item">保持寄存器 / 输入寄存器：${escapeHtml(summary.areas?.holding_register || 0)} / ${escapeHtml(summary.areas?.input_register || 0)}</div>`,
  ].join("");
}

function renderLiveCatalogTable() {
  const catalog = uiState.live.catalogPayload?.catalog || [];
  renderTable("liveCatalogTable", [
    { key: "name", label: "名称" },
    { key: "group", label: "分组" },
    { key: "area", label: "区域" },
    { key: "address", label: "地址" },
    { key: "dataType", label: "数据类型" },
    { key: "unit", label: "单位" },
    { key: "pollGroup", label: "轮询组" },
    { key: "readable", label: "可读", render: (row) => row.readable ? "是" : "否" },
    { key: "writable", label: "可写", render: (row) => row.writable ? "是" : "否" },
    { key: "notes", label: "说明" },
  ], catalog.slice(0, 40));
}

function buildLivePollingCommandTableRow(command, index) {
  const itemIds = Array.isArray(command.catalogItemIds) ? command.catalogItemIds.join(",") : "";
  const sourceLabel = normalizeLiveCommandLabel(command);
  return `
    <tr data-live-command-row="${escapeHtml(command.id || `cmd-${index + 1}`)}" data-live-command-source="${escapeHtml(command.sourceGroup || "custom")}" data-live-command-items="${escapeHtml(itemIds)}" data-live-command-area="${escapeHtml(command.area || "")}">
      <td class="live-command-index">${escapeHtml(index + 1)}</td>
      <td class="live-command-checkbox-cell"><input data-live-command-field="autoPoll" type="checkbox" ${command.autoPoll ? "checked" : ""}></td>
      <td><span class="live-command-badge">${escapeHtml(sourceLabel)}</span></td>
      <td><input class="live-command-name-input" data-live-command-field="name" value="${escapeHtml(command.name || "")}"></td>
      <td>
        <select data-live-command-field="mode">
          <option value="modbus_read" ${command.mode === "modbus_read" ? "selected" : ""}>读命令</option>
          <option value="raw_hex" ${command.mode === "raw_hex" ? "selected" : ""}>原始HEX</option>
        </select>
      </td>
      <td>
        <select data-live-command-field="functionCode">
          ${[1, 2, 3, 4].map((fc) => `<option value="${fc}" ${Number(command.functionCode) === fc ? "selected" : ""}>FC${String(fc).padStart(2, "0")}</option>`).join("")}
        </select>
      </td>
      <td><input class="live-command-number" data-live-command-field="address" type="number" min="0" value="${escapeHtml(command.address ?? 0)}"></td>
      <td><input class="live-command-number" data-live-command-field="count" type="number" min="1" value="${escapeHtml(command.count ?? 1)}"></td>
      <td><input class="live-command-send-input" data-live-command-field="requestHex" value="${escapeHtml(command.requestHex || "")}" title="${escapeHtml(itemIds ? `点表项：${itemIds}` : "自定义命令")}"></td>
      <td class="live-command-checkbox-cell"><input data-live-command-field="appendCrc" type="checkbox" ${command.appendCrc !== false ? "checked" : ""}></td>
      <td class="live-command-checkbox-cell"><input data-live-command-field="expectResponse" type="checkbox" ${command.expectResponse !== false ? "checked" : ""}></td>
      <td>
        <select data-live-command-field="responseMode">
          <option value="modbus" ${command.responseMode === "modbus" ? "selected" : ""}>Modbus</option>
          <option value="raw" ${command.responseMode === "raw" ? "selected" : ""}>原始</option>
        </select>
      </td>
      <td>
        <select data-live-command-field="decodeMode">
          <option value="catalog" ${command.decodeMode !== "none" ? "selected" : ""}>点表</option>
          <option value="none" ${command.decodeMode === "none" ? "selected" : ""}>不解码</option>
        </select>
      </td>
      <td>
        <span class="live-command-ms-cell"><input class="live-command-delay" data-live-command-field="responseTimeoutMs" type="number" min="0" step="50" placeholder="跟随设备" value="${escapeHtml(command.responseTimeoutMs ?? "")}"><span>ms</span></span>
      </td>
      <td>
        <span class="live-command-ms-cell"><input class="live-command-delay" data-live-command-field="delayAfterMs" type="number" min="0" step="50" value="${escapeHtml(command.delayAfterMs ?? 0)}"><span>ms</span></span>
      </td>
      <td><button type="button" class="secondary live-command-delete" data-live-command-delete="${escapeHtml(command.id || "")}">删除</button></td>
    </tr>
  `;
}

function renderLivePollingCommandEditor() {
  const host = qs("livePollingCommandEditor");
  if (!host) return;
  const commands = getLivePollingCommandsDraft();
  const autoCount = commands.filter((item) => item.autoPoll).length;
  const parameterCount = commands.filter((item) => item.sourceGroup === "slow").length;
  host.innerHTML = `
    <div class="live-command-toolbar">
      <div class="live-command-summary">共 ${escapeHtml(commands.length)} 条命令，${escapeHtml(autoCount)} 条加入自动轮询，${escapeHtml(parameterCount)} 条参数命令默认保留为手动读取；自动轮询按表格顺序逐行执行。</div>
      <div class="button-row">
        <button type="button" class="secondary" id="liveCommandAddBtn">新增命令</button>
        <button type="button" class="secondary" id="liveCommandResetBtn">恢复默认命令</button>
      </div>
    </div>
    ${commands.length ? `
      <div class="live-command-table-wrap">
        <table class="live-command-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>轮询</th>
              <th>来源</th>
              <th>命令名称</th>
              <th>模式</th>
              <th>功能码</th>
              <th>地址</th>
              <th>数量</th>
              <th>发送命令模板</th>
              <th>CRC</th>
              <th>等待接收</th>
              <th>接收解析</th>
              <th>数据解码</th>
              <th>接收超时</th>
              <th>命令间隔</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${commands.map((command, index) => buildLivePollingCommandTableRow(command, index)).join("")}
          </tbody>
        </table>
      </div>
    ` : `<div class="empty-state">暂无轮询命令。</div>`}
  `;
  bindLivePollingCommandEditor();
}

function updateLivePollingCommandDraftFromEditor() {
  if (!uiState.live.selectedDeviceDraft) return;
  uiState.live.selectedDeviceDraft.pollingCommands = collectLivePollingCommands();
}

function bindLivePollingCommandEditor() {
  qsa("[data-live-command-field]").forEach((input) => {
    const eventName = input.tagName === "SELECT" || input.type === "checkbox" ? "change" : "input";
    input.addEventListener(eventName, () => {
      const row = input.closest("[data-live-command-row]");
      if (row && ["functionCode", "address", "count"].includes(input.dataset.liveCommandField)) {
        const mode = row.querySelector('[data-live-command-field="mode"]')?.value;
        const hexInput = row.querySelector('[data-live-command-field="requestHex"]');
        if (mode === "modbus_read" && hexInput) {
          const fc = row.querySelector('[data-live-command-field="functionCode"]')?.value;
          const address = row.querySelector('[data-live-command-field="address"]')?.value;
          const count = row.querySelector('[data-live-command-field="count"]')?.value;
          hexInput.value = buildLiveCommandRequestTemplate(fc, address, count);
        }
      }
      updateLivePollingCommandDraftFromEditor();
    });
  });
  qsa("[data-live-command-delete]").forEach((button) => {
    button.onclick = () => {
      const row = button.closest("[data-live-command-row]");
      if (row) row.remove();
      updateLivePollingCommandDraftFromEditor();
      renderLivePollingCommandEditor();
    };
  });
  const addBtn = qs("liveCommandAddBtn");
  if (addBtn) {
    addBtn.onclick = () => {
      updateLivePollingCommandDraftFromEditor();
      uiState.live.selectedDeviceDraft.pollingCommands.push(buildLiveNewPollingCommand());
      renderLivePollingCommandEditor();
    };
  }
  const resetBtn = qs("liveCommandResetBtn");
  if (resetBtn) {
    resetBtn.onclick = () => {
      if (!uiState.live.selectedDeviceDraft) return;
      uiState.live.selectedDeviceDraft.pollingCommands = clone(uiState.live.catalogPayload?.defaultPollingCommands || []);
      renderLivePollingCommandEditor();
    };
  }
}

function renderLiveOverview() {
  const cards = getLiveAnalogCards();
  const statusList = Array.isArray(uiState.live.snapshotPayload?.snapshot?.statuses) ? uiState.live.snapshotPayload.snapshot.statuses : [];
  if (qs("liveStatusList")?.previousElementSibling) qs("liveStatusList").previousElementSibling.textContent = "状态项";
  const sessionPanel = qs("liveOverviewSession")?.closest(".chart-panel");
  if (sessionPanel) sessionPanel.style.display = "none";
  qs("liveOverviewMetrics").innerHTML = cards.map((card) => `
    <div class="overview-card">
      <div class="overview-label">${escapeHtml(card.label)}</div>
      <strong style="color:${card.color}">${escapeHtml(card.value)}</strong>
      <div class="muted">${escapeHtml(card.detail)}</div>
    </div>
  `).join("");
  qs("liveStatusList").innerHTML = statusList.length ? `
    <div class="live-status-grid">
      ${statusList.slice(0, 18).map((item, index) => `
        <article class="live-status-card tone-${getLiveStatusTone(item, index)}">
          <div class="live-status-name">${escapeHtml(item.label || item.name || item.id || "-")}</div>
          <div class="live-status-value">${escapeHtml(formatLiveStatusValue(item.currentValue ?? item.value ?? "-"))}</div>
        </article>
      `).join("")}
    </div>
  ` : `<div class="empty-state">暂无状态量数据。</div>`;
}

function renderLiveCurveChart() {
  const host = qs("liveCurveChartHost");
  const summaryHost = qs("liveCurveSummary");
  if (!host || !summaryHost) return;
  const rows = normalizeLiveSeriesRows(uiState.live.seriesPayload, uiState.live.snapshotPayload);
  const events = normalizeLiveEvents(uiState.live.eventsPayload, rows);
  const latest = rows.length ? rows[rows.length - 1] : null;
  const first = rows.length ? rows[0] : null;
  const metricMap = buildLiveMetricMap(uiState.live.snapshotPayload);
  const visibleMetrics = uiState.live.visibleMetrics || new Set(Object.keys(METRICS));
  const visibleMetricKeys = Object.keys(METRICS).filter((key) => visibleMetrics.has(key));
  const metricCards = Object.entries(METRICS).map(([key, meta]) => {
    const value = latest?.[key] ?? metricMap[key]?.value;
    return `
      <article class="live-curve-metric-card ${visibleMetrics.has(key) ? "" : "muted"}">
        <div class="live-curve-metric-label">${escapeHtml(meta.label)}</div>
        <strong style="color:${meta.color}">${value === null || value === undefined ? "-" : `${formatNumber(value)} ${meta.unit}`}</strong>
      </article>
    `;
  }).join("");
  if (!rows.length) {
    host.innerHTML = `<div class="empty-state">当前时间窗内还没有曲线数据。</div>`;
    summaryHost.innerHTML = [
      `<div class="live-curve-summary-grid">`,
      `<div class="summary-item">时间窗：${uiState.live.curveWindowMinutes} 分钟</div>`,
      `<div class="summary-item">采样点：0</div>`,
      `<div class="summary-item">关键事件：0</div>`,
      `</div>`,
      `<div class="live-curve-metric-grid">${metricCards}</div>`,
    ].join("");
    renderLiveCurveToolbarToggles();
    return;
  }
  if (typeof window.__renderStandardTrendChart === "function") {
    window.__renderStandardTrendChart("liveCurveChartHost", {
      points: rows.map((row) => ({ ts: row.timestamp, pressure: row.pressure, temperature: row.temperature, flow: row.flow, humidity: row.humidity })),
      events: events.map((item) => ({ ts: item.ts, type: item.type, title: item.title, detail: item.detail })),
      series: visibleMetricKeys.map((key) => ({
        key,
        label: `${METRICS[key].label} (${METRICS[key].unit})`,
        unit: METRICS[key].unit,
        color: METRICS[key].color,
      })),
    });
  } else {
    host.innerHTML = `<div class="empty-state">标准趋势图模块未加载。</div>`;
  }
  const spanMinutes = first && latest ? Math.max(0, (latest.timestamp - first.timestamp) / 60000) : 0;
  summaryHost.innerHTML = [
    `<div class="live-curve-summary-grid">`,
    `<div class="summary-item"><span class="live-curve-k">时间窗</span><strong>${uiState.live.curveWindowMinutes} 分钟</strong></div>`,
    `<div class="summary-item"><span class="live-curve-k">采样点</span><strong>${rows.length}</strong></div>`,
    `<div class="summary-item"><span class="live-curve-k">关键事件</span><strong>${events.length}</strong></div>`,
    `<div class="summary-item"><span class="live-curve-k">覆盖时长</span><strong>${formatNumber(spanMinutes, 1)} 分钟</strong></div>`,
    `</div>`,
    `<div class="live-curve-metric-grid">${metricCards}</div>`,
  ].join("");
  renderLiveCurveToolbarToggles();
}

function renderLiveParameterMonitor() {
  const sectionsHost = qs("liveParameterSections");
  if (!sectionsHost) return;
  const panel = document.querySelector('.view-tab-panel[data-tab="parameter-monitor"]');
  const legacyGrid = panel?.querySelector(".live-grid");
  if (legacyGrid) legacyGrid.remove();
  const sections = uiState.live.parametersPayload?.sections || getLiveDefaultParameters().sections;
  const matchesSelectedDevice = Boolean(uiState.live.parametersPayload?.matchesSelectedDevice);
  const globalRunning = uiState.live.sessionStatus?.state?.running || uiState.live.sessionStatus?.activeSession?.running;
  const pollBusy = uiState.live.parameterPollBusy;
  sectionsHost.innerHTML = `
    <div class="live-parameter-toolbar">
      <button id="liveParameterPollBtn" class="primary" ${!globalRunning || pollBusy ? "disabled" : ""}>${pollBusy ? "轮询中..." : "轮询读取所有参数"}</button>
      ${!globalRunning ? '<span class="live-status-notice">采集未启动</span>' : ""}
    </div>
    <section class="live-parameter-workbench">
      <div class="live-parameter-section-stack">
        ${LIVE_PARAMETER_GROUPS.map((group) => buildLiveParameterSection(group, sections[group.key] || [], matchesSelectedDevice)).join("")}
      </div>
    </section>
  `;
  bindLiveParameterMonitor();
}

function renderLiveDebugPanel() {
  const workbenchHost = qs("liveDebugWorkbench");
  const trafficHost = qs("liveDebugTraffic");
  if (!workbenchHost || !trafficHost) return;
  const devices = uiState.live.devicesPayload?.devices || [];
  const draft = uiState.live.debugDraft || {};
  const activeDeviceId = draft.deviceId || uiState.live.selectedDeviceId || devices[0]?.id || "";
  if (!draft.deviceId && activeDeviceId) uiState.live.debugDraft.deviceId = activeDeviceId;
  const activeDevice = devices.find((item) => item.id === activeDeviceId) || null;
  const result = uiState.live.debugResult;
  workbenchHost.innerHTML = `
    <div class="live-debug-form">
      <label class="live-field">
        <span>目标设备</span>
        <select id="liveDebugDeviceSelect">
          ${devices.map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === activeDeviceId ? "selected" : ""}>${escapeHtml(item.name)} · ${escapeHtml(item.address || "-")} · 站号 ${escapeHtml(item.slaveId ?? "-")}</option>`).join("")}
        </select>
      </label>
      <label class="live-field">
        <span>原始十六进制命令</span>
        <textarea id="liveDebugHexInput" class="path-block live-debug-hex" rows="7" placeholder="例如：01 03 00 00 00 01">${escapeHtml(draft.requestHex || "")}</textarea>
      </label>
      <div class="live-debug-options">
        <label><input id="liveDebugAppendCrc" type="checkbox" ${draft.appendCrc !== false ? "checked" : ""}> 自动补 CRC</label>
        <label><input id="liveDebugExpectResponse" type="checkbox" ${draft.expectResponse !== false ? "checked" : ""}> 等待接收</label>
        <label class="live-field compact"><span>超时 (ms)</span><input id="liveDebugTimeoutInput" type="number" min="50" step="50" value="${escapeHtml(draft.responseTimeoutMs ?? 1200)}"></label>
      </div>
      <div class="button-row">
        <button id="liveDebugSendBtn" class="primary" ${activeDevice ? "" : "disabled"}>发送调试命令</button>
        <button id="liveDebugClearInputBtn" class="secondary">清空命令</button>
      </div>
      <div class="live-debug-hint">发送时直接复用设备现有通讯配置，便于复现场景里的真实总线收发。</div>
      <div class="live-debug-result">
        <div class="summary-item">目标：${escapeHtml(activeDevice?.name || "未选择设备")}</div>
        <div class="summary-item">端口：${escapeHtml(activeDevice?.address || "-")} · 站号 ${escapeHtml(activeDevice?.slaveId ?? "-")}</div>
        <div class="summary-item">最近发送：${escapeHtml(result?.requestHex || "-")}</div>
        <div class="summary-item">最近接收：${escapeHtml(result?.responseHex || (result?.status === "sent" ? "仅发送" : "-"))}</div>
        <div class="summary-item">结果：${escapeHtml(result ? formatLiveTrafficStatus(result.status) : "尚未发送")}</div>
      </div>
    </div>
  `;
  const trafficRows = normalizeLiveTrafficRows(uiState.live.trafficPayload);
  trafficHost.innerHTML = buildLiveTrafficFeed(trafficRows, "暂无全局调试日志。", true);
  trafficHost.scrollTop = trafficHost.scrollHeight;
  bindLiveDebugControls();
}

function bindLiveDebugControls() {
  const deviceSelect = qs("liveDebugDeviceSelect");
  const hexInput = qs("liveDebugHexInput");
  const appendCrc = qs("liveDebugAppendCrc");
  const expectResponse = qs("liveDebugExpectResponse");
  const timeoutInput = qs("liveDebugTimeoutInput");
  const sendBtn = qs("liveDebugSendBtn");
  const clearInputBtn = qs("liveDebugClearInputBtn");
  const clearTrafficBtn = qs("liveDebugClearTrafficBtn");
  if (deviceSelect) deviceSelect.onchange = () => { uiState.live.debugDraft.deviceId = deviceSelect.value; };
  if (hexInput) hexInput.oninput = () => { uiState.live.debugDraft.requestHex = hexInput.value; };
  if (appendCrc) appendCrc.onchange = () => { uiState.live.debugDraft.appendCrc = appendCrc.checked; };
  if (expectResponse) expectResponse.onchange = () => { uiState.live.debugDraft.expectResponse = expectResponse.checked; };
  if (timeoutInput) timeoutInput.oninput = () => { uiState.live.debugDraft.responseTimeoutMs = Number(timeoutInput.value) || 1200; };
  if (clearInputBtn) {
    clearInputBtn.onclick = () => {
      uiState.live.debugDraft.requestHex = "";
      renderLiveDebugPanel();
    };
  }
  if (clearTrafficBtn) {
    clearTrafficBtn.onclick = async () => {
      try {
        await clearLiveTraffic();
        uiState.live.trafficPayload = getLiveDefaultTraffic();
        renderLiveDebugPanel();
        setLiveStatusNotice("全局调试日志已清空。");
      } catch (error) {
        setLiveStatusNotice(`清空调试日志失败：${error.message}`);
      }
    };
  }
  if (sendBtn) {
    sendBtn.onclick = async () => {
      try {
        const payload = {
          deviceId: uiState.live.debugDraft.deviceId || uiState.live.selectedDeviceId,
          requestHex: uiState.live.debugDraft.requestHex || "",
          appendCrc: uiState.live.debugDraft.appendCrc !== false,
          expectResponse: uiState.live.debugDraft.expectResponse !== false,
          responseTimeoutMs: Number(uiState.live.debugDraft.responseTimeoutMs) || 1200,
        };
        const result = await sendLiveDebugFrame(payload);
        uiState.live.debugResult = result;
        await refreshLiveRuntimeData();
        renderLiveDebugPanel();
        setLiveStatusNotice(`调试命令已发送：${formatLiveTrafficStatus(result.status)}`);
      } catch (error) {
        setLiveStatusNotice(`调试命令发送失败：${error.message}`);
      }
    };
  }
}

function formatLiveParameterValue(value, unit = "") {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "开" : "关";
  if (typeof value === "number") {
    const text = Number.isInteger(value) ? String(value) : formatNumber(value, 4).replace(/\.?0+$/, "");
    return unit ? `${text} ${unit}` : text;
  }
  return unit ? `${String(value)} ${unit}` : String(value);
}

function getLiveParameterDraftValue(row) {
  if (Object.prototype.hasOwnProperty.call(uiState.live.parameterDrafts || {}, row.id)) {
    return uiState.live.parameterDrafts[row.id];
  }
  const currentValue = row.currentValue ?? row.value;
  if (row.dataType === "bool" || row.area === "coil") {
    return currentValue ? "true" : "false";
  }
  return currentValue ?? "";
}

function buildLiveParameterEditor(row, canWrite) {
  const draftValue = getLiveParameterDraftValue(row);
  if (!row.writable) {
    return `<span class="live-parameter-readonly">只读</span>`;
  }
  if (row.dataType === "bool" || row.area === "coil") {
    return `
      <select class="live-parameter-input" data-live-parameter-input="${escapeHtml(row.id)}" ${canWrite ? "" : "disabled"}>
        <option value="true" ${String(draftValue) === "true" ? "selected" : ""}>开 / true</option>
        <option value="false" ${String(draftValue) === "false" ? "selected" : ""}>关 / false</option>
      </select>
    `;
  }
  let inputType = "text";
  let step = "";
  if (row.dataType === "float32") {
    inputType = "number";
    step = ` step="0.0001"`;
  } else if (row.dataType === "int16" || row.dataType === "uint16" || row.dataType === "uint32") {
    inputType = "number";
    step = ` step="1"`;
  }
  return `<input class="live-parameter-input" data-live-parameter-input="${escapeHtml(row.id)}" type="${inputType}"${step} value="${escapeHtml(draftValue)}" ${canWrite ? "" : "disabled"}>`;
}

function buildLiveParameterRow(row, matchesSelectedDevice) {
  const areaText = `${row.area || "-"} @ ${row.address ?? "-"}`;
  const canWrite = Boolean(matchesSelectedDevice && row.writable);
  const currentValue = formatLiveParameterValue(row.currentValue ?? row.value, row.unit || "");
  return `
    <article class="live-parameter-entry ${row.writable ? "is-writable" : "is-readonly"}">
      <div class="live-parameter-entry-head">
        <div>
          <div class="live-parameter-name">${escapeHtml(row.name || row.id || "-")}</div>
          <div class="live-parameter-submeta">${escapeHtml(row.id || "-")}</div>
        </div>
        <div class="live-parameter-current-badge">${escapeHtml(currentValue)}</div>
      </div>
      <div class="live-parameter-entry-meta">
        <span>${escapeHtml(areaText)}</span>
        <span>${escapeHtml(row.dataType || "-")}${row.unit ? ` · ${escapeHtml(row.unit)}` : ""}</span>
        <span>${escapeHtml(row.updatedAt || "未采集")}</span>
      </div>
      <div class="live-parameter-entry-controls">
        <div class="live-parameter-editor-wrap">${buildLiveParameterEditor(row, canWrite)}</div>
        ${row.writable
          ? `<button type="button" class="secondary live-parameter-write-btn" data-live-parameter-write="${escapeHtml(row.id)}" ${canWrite ? "" : "disabled"}>写入</button>`
          : `<span class="live-parameter-readonly">只读</span>`}
      </div>
    </article>
  `;
}

function parseLiveTaskRowId(rowId) {
  var match = /^holding\.task(\d+)_(.+)$/.exec(String(rowId || ""));
  if (!match) return null;
  return { taskIndex: Number(match[1]), fieldKey: match[2] };
}

function formatLiveTaskStartTime(parts) {
  var month = Number(parts?.start_month);
  var day = Number(parts?.start_day);
  var hour = Number(parts?.start_hour);
  var minute = Number(parts?.start_minute);
  if (![month, day, hour, minute].every((value) => Number.isFinite(value) && value > 0)) return "-";
  return `${String(month).padStart(2, "0")}/${String(day).padStart(2, "0")}-${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function buildLiveTaskStartTimeRow(taskIndex, rowsByField) {
  var values = {};
  ["start_month", "start_day", "start_hour", "start_minute"].forEach((key) => {
    values[key] = rowsByField[key]?.currentValue ?? rowsByField[key]?.value ?? null;
  });
  return {
    id: `holding.task${taskIndex}_start_time`,
    name: "开始时间",
    area: "holding_register",
    address: `${30 + taskIndex * 10}-${33 + taskIndex * 10}`,
    dataType: "string",
    unit: "",
    writable: false,
    currentValue: formatLiveTaskStartTime(values),
    updatedAt: rowsByField.start_month?.updatedAt || rowsByField.start_day?.updatedAt || rowsByField.start_hour?.updatedAt || rowsByField.start_minute?.updatedAt || null,
  };
}

function getLiveActiveTaskCount() {
  var taskCountRow = (uiState.live.parametersPayload?.sections?.config || []).find((row) => row.id === "holding.task_count");
  var activeTaskCount = Number(taskCountRow?.currentValue ?? taskCountRow?.value);
  return Number.isFinite(activeTaskCount) && activeTaskCount >= 0 ? activeTaskCount : null;
}

function buildLiveTaskParameterSection(rows, matchesSelectedDevice) {
  var activeTaskCount = getLiveActiveTaskCount();
  var grouped = new Map();
  rows.forEach((row) => {
    var meta = parseLiveTaskRowId(row.id);
    if (!meta) return;
    if (!grouped.has(meta.taskIndex)) grouped.set(meta.taskIndex, {});
    grouped.get(meta.taskIndex)[meta.fieldKey] = row;
  });
  var indexes = Array.from(grouped.keys()).sort(function(a, b) { return a - b; });
  if (Number.isFinite(activeTaskCount) && activeTaskCount > 0) {
    indexes = indexes.filter((index) => index < activeTaskCount);
  } else {
    indexes = indexes.filter((index) => {
      var taskRows = grouped.get(index) || {};
      return Object.values(taskRows).some((row) => row && row.currentValue !== null && row.currentValue !== undefined && row.currentValue !== "");
    });
  }
  if (!indexes.length) {
    return `<div class="empty-state">当前没有任务参数。</div>`;
  }
  var fieldOrder = [
    "delay",
    "humidity_high",
    "humidity_low",
    "respiratory_on",
    "respiratory_off",
  ];
  return indexes.map((taskIndex) => {
    var taskRows = grouped.get(taskIndex) || {};
    var startTimeRow = buildLiveTaskStartTimeRow(taskIndex, taskRows);
    var bodyRows = [startTimeRow].concat(fieldOrder.map((key) => taskRows[key]).filter(Boolean));
    return `
      <section class="live-parameter-task-card">
        <div class="live-parameter-task-head">
          <strong>任务 ${taskIndex + 1}</strong>
          <span class="live-parameter-submeta">寄存器 ${30 + taskIndex * 10}-${39 + taskIndex * 10}</span>
        </div>
        <div class="live-parameter-grid">
          ${bodyRows.map((row) => buildLiveParameterRow(row, matchesSelectedDevice)).join("")}
        </div>
      </section>
    `;
  }).join("");
}

function buildLiveParameterSection(group, rows, matchesSelectedDevice) {
  const writableCount = rows.filter((row) => row.writable).length;
  const sectionBody = group.key === "task"
    ? buildLiveTaskParameterSection(rows, matchesSelectedDevice)
    : (rows.length ? rows.map((row) => buildLiveParameterRow({ ...row, __group: group.key }, matchesSelectedDevice)).join("") : `<div class="empty-state">当前分组没有参数。</div>`);
  const sectionMeta = group.key === "task"
    ? `${getLiveActiveTaskCount() ?? 0} 个任务 · ${writableCount} 项可写`
    : `${rows.length} 项 · ${writableCount} 项可写`;
  return `
    <section class="live-parameter-card live-parameter-workbench-card tone-${escapeHtml(group.tone || group.key)}">
      <div class="live-parameter-card-head">
        <div>
          <strong>${escapeHtml(group.label)}</strong>
          <div class="live-parameter-submeta">${sectionMeta}</div>
        </div>
      </div>
      <div class="live-parameter-grid">
        ${sectionBody}
      </div>
    </section>
  `;
}

function isLiveParameterEditingActive() {
  const active = document.activeElement;
  return Boolean(active && active.matches && active.matches("[data-live-parameter-input]"));
}

function bindLiveParameterMonitor() {
  qsa("[data-live-parameter-input]").forEach((input) => {
    if (input.dataset.liveParameterInputBound === "1") return;
    input.dataset.liveParameterInputBound = "1";
    const saveDraft = () => {
      uiState.live.parameterDrafts[input.dataset.liveParameterInput] = input.value;
    };
    input.addEventListener("focus", () => {
      uiState.live.parameterEditingId = input.dataset.liveParameterInput;
    });
    input.addEventListener("blur", () => {
      if (uiState.live.parameterEditingId === input.dataset.liveParameterInput) uiState.live.parameterEditingId = null;
    });
    input.addEventListener("input", saveDraft);
    input.addEventListener("change", saveDraft);
  });
  qsa("[data-live-parameter-write]").forEach((button) => {
    if (button.dataset.liveParameterWriteBound === "1") return;
    button.dataset.liveParameterWriteBound = "1";
    button.addEventListener("click", async () => {
      const itemId = button.dataset.liveParameterWrite;
      const input = document.querySelector(`[data-live-parameter-input="${escapeSelectorValue(itemId)}"]`);
      if (!itemId || !input) return;
      const rawValue = input.value;
      button.disabled = true;
      try {
        const deviceId = uiState.live.selectedDeviceId;
        const response = await writeLiveParameter(deviceId, itemId, rawValue);
        delete uiState.live.parameterDrafts[itemId];
        await refreshLiveRuntimeData();
        renderLiveOverview();
        renderLiveParameterMonitor();
        renderLiveSessionSummary();
        setLiveStatusNotice(response.message || `参数已写入：${itemId}`);
      } catch (error) {
        setLiveStatusNotice(`参数写入失败：${error.message}`);
      } finally {
        button.disabled = false;
      }
    });
  });
  const pollBtn = qs("liveParameterPollBtn");
  if (pollBtn && !pollBtn.dataset.livePollBound) {
    pollBtn.dataset.livePollBound = "1";
    pollBtn.addEventListener("click", async () => {
      const deviceId = uiState.live.selectedDeviceId;
      if (!deviceId) return;
      uiState.live.parameterPollBusy = true;
      renderLiveParameterMonitor();
      try {
        const result = await fetchLivePollParameters(deviceId);
        await refreshLiveRuntimeData();
        renderLiveParameterMonitor();
        setLiveStatusNotice(result.message || "参数轮询完成");
      } catch (error) {
        setLiveStatusNotice(`参数轮询失败：${error.message}`);
      } finally {
        uiState.live.parameterPollBusy = false;
        renderLiveParameterMonitor();
      }
    });
  }
}

function bindLiveDeviceActions() {
  const label = qs("liveActionsDeviceName");
  const currentDevice = getSelectedLiveDevice();
  if (label) {
    label.textContent = currentDevice ? `设备：${currentDevice.name}` : "设备工具";
  }
  const bindOnce = (id, handler) => {
    const el = qs(id);
    if (!el || el.dataset.liveBound === "1") return;
    el.dataset.liveBound = "1";
    el.addEventListener("click", handler);
  };
  bindOnce("liveRefreshDeviceBtn", async () => {
    const device = getSelectedLiveDevice();
    if (!device) { setLiveStatusNotice("请先选择设备。"); return; }
    try {
      await refreshLiveDeviceAndCatalog(device.id);
      setLiveStatusNotice(`已刷新设备与点表：${device.name}`);
    } catch (error) {
      setLiveStatusNotice(`刷新失败：${error.message}`);
    }
  });
  bindOnce("liveExportDevicesConfigBtn", async () => {
    try {
      await downloadLiveDevicesConfig();
      setLiveStatusNotice("设备配置已导出：live_devices.json");
    } catch (error) {
      setLiveStatusNotice(`导出设备配置失败：${error.message}`);
    }
  });
  bindOnce("liveImportDevicesConfigBtn", () => {
    const input = qs("liveImportDevicesConfigInput");
    if (!input) {
      setLiveStatusNotice("导入控件未就绪，请刷新页面后重试。");
      return;
    }
    input.value = "";
    input.click();
  });
  bindOnce("liveExportDeviceBtn", async () => {
    const device = getSelectedLiveDevice();
    if (!device) { setLiveStatusNotice("请先选择设备。"); return; }
    showLiveExportModal(device.id, device.name, async (targetDir) => {
      const response = await exportLiveSession(device.id, targetDir);
      setLiveStatusNotice(`已导出：${device.name} -> ${response.export?.exportDir || targetDir}`);
    });
  });
  bindOnce("liveAnalyzeDeviceBtn", async () => {
    const device = getSelectedLiveDevice();
    if (!device) { setLiveStatusNotice("请先选择设备。"); return; }
    showLiveExportModal(device.id, device.name, async (targetDir) => {
      const response = await analyzeLiveSession(device.id, targetDir);
      if (response.analysis) {
        const sourceData = normalizeAnalysisPayload(response.analysis);
        applyDataSet(sourceData, {
          runtime: true,
          importedLocal: false,
          generatedAt: response.analysis.generated_at || new Date().toISOString(),
        });
        showView("master");
      }
      setLiveStatusNotice(`已导出并进入分析：${device.name}`);
    });
  });
}

function bindLiveDevicesConfigImport() {
  const input = qs("liveImportDevicesConfigInput");
  if (!input || input.dataset.liveImportBound === "1") return;
  input.dataset.liveImportBound = "1";
  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      await importLiveDevicesConfig(payload);
      await refreshLiveModule();
      uiState.activeTab.live = "device-settings";
      renderLiveView();
      setLiveStatusNotice(`设备配置已导入：${file.name}`);
    } catch (error) {
      setLiveStatusNotice(`导入设备配置失败：${error.message}`);
    } finally {
      input.value = "";
    }
  });
}

async function refreshLiveDeviceAndCatalog(deviceId) {
  const [devicesPayload, catalogPayload] = await Promise.all([
    fetchLiveDevices(),
    fetchLiveCatalog(),
  ]);
  uiState.live.devicesPayload = devicesPayload;
  uiState.live.catalogPayload = catalogPayload;
  uiState.live.selectedDeviceDraft = buildLiveDeviceDraft(getSelectedLiveDevice());
  renderLiveDeviceList();
  renderLiveDeviceEditor();
  bindLiveDeviceEditorInputs();
  renderLiveCatalogSummary();
  renderLiveCatalogTable();
  renderLivePollingCommandEditor();
}

function ensureLiveCurveLayout() {
  const panel = document.querySelector('.view-tab-panel[data-tab="live-curves"]');
  if (!panel) return;
  panel.classList.add("live-curve-panel");
  const toolbar = panel.querySelector(".live-curve-toolbar");
  const chartPanel = panel.querySelector(".chart-panel");
  if (toolbar && chartPanel && panel.firstElementChild !== chartPanel) {
    chartPanel.classList.add("live-curve-chart-panel");
    panel.insertBefore(chartPanel, toolbar);
  }
  const tabs = qs("liveWindowTabs");
  if (tabs) {
    tabs.classList.add("live-window-grid");
    if (!tabs.querySelector('[data-live-window="60"]')) {
      const button = document.createElement("button");
      button.className = "filter-chip";
      button.dataset.liveWindow = "60";
      button.textContent = "60 分钟";
      tabs.appendChild(button);
    }
  }
  const legacyRail = qs("liveCurveToggleRail");
  if (legacyRail) legacyRail.remove();
}

function renderLiveMetricToggleChips() {
  const selected = uiState.live.visibleMetrics || new Set(Object.keys(METRICS));
  return `
    <div class="live-curve-toggle-block">
      <div class="live-curve-toggle-title">显示曲线</div>
      <div class="chip-row live-curve-toggle-column">
        ${Object.entries(METRICS).map(([key, meta]) => `
          <button
            type="button"
            class="filter-chip live-metric-toggle ${selected.has(key) ? "active" : ""}"
            data-live-metric-toggle="${escapeHtml(key)}"
            aria-pressed="${selected.has(key) ? "true" : "false"}"
            style="${selected.has(key) ? `border-color:${meta.color}; color:${meta.color};` : ""}"
          >${escapeHtml(meta.label)}</button>
        `).join("")}
      </div>
    </div>
  `;
}

function bindLiveMetricToggleChips() {
  qsa("[data-live-metric-toggle]").forEach((button) => {
    if (button.dataset.liveMetricToggleBound === "1") return;
    button.dataset.liveMetricToggleBound = "1";
    button.addEventListener("click", () => {
      const key = button.dataset.liveMetricToggle;
      if (!key || !METRICS[key]) return;
      const visible = new Set(uiState.live.visibleMetrics || Object.keys(METRICS));
      if (visible.has(key) && visible.size === 1) return;
      if (visible.has(key)) visible.delete(key);
      else visible.add(key);
      uiState.live.visibleMetrics = visible;
      renderLiveCurveChart();
    });
  });
}

function renderLiveCurveToolbarToggles() {
  const toolbar = document.querySelector('.live-curve-toolbar');
  const tabs = qs("liveWindowTabs");
  if (!toolbar || !tabs) return;
  const windowGroup = tabs.closest(".filter-group");
  if (!windowGroup) return;
  let host = qs("liveCurveMetricToggles");
  if (!host) {
    host = document.createElement("div");
    host.id = "liveCurveMetricToggles";
    host.className = "live-curve-toggle-host";
    tabs.insertAdjacentElement("afterend", host);
  }
  host.innerHTML = renderLiveMetricToggleChips();
  bindLiveMetricToggleChips();
}

function refreshLiveWindowButtons() {
  qsa("[data-live-window]").forEach((button) => {
    const isActive = Number(button.dataset.liveWindow) === Number(uiState.live.curveWindowMinutes);
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function bindLiveWindowTabs() {
  refreshLiveWindowButtons();
  qsa("[data-live-window]").forEach((button) => {
    if (button.dataset.liveWindowBound === "1") return;
    button.dataset.liveWindowBound = "1";
    button.addEventListener("click", async () => {
      uiState.live.curveWindowMinutes = Number(button.dataset.liveWindow) || 5;
      refreshLiveWindowButtons();
      await refreshLiveRuntimeData();
      renderLiveCurveChart();
      refreshLiveWindowButtons();
    });
  });
}

async function refreshLiveRuntimeData() {
  const selectedDeviceId = uiState.live.selectedDeviceId || null;
  const [sessionStatus, snapshotPayload, seriesPayload, eventsPayload, trafficPayload, parametersPayload, metaPayload, deviceStatusesPayload] = await Promise.all([
    safeLiveRequest(() => fetchLiveSessionStatus(selectedDeviceId), () => ({
      ok: true,
      selectedDeviceId,
      sessionDeviceId: null,
      activeDeviceId: null,
      matchesSelectedDevice: false,
      activeMatchesSelectedDevice: false,
      selectedDevice: getSelectedLiveDevice(),
      sessionDevice: null,
      activeDevice: null,
      session: getLiveDefaultSession(selectedDeviceId),
      activeSession: getLiveDefaultSession(null),
    })),
    safeLiveRequest(() => fetchLiveSnapshot(selectedDeviceId), () => getLiveDefaultSnapshot(selectedDeviceId)),
    safeLiveRequest(() => fetchLiveSeries(uiState.live.curveWindowMinutes, selectedDeviceId), () => ({
      ok: true,
      selectedDeviceId,
      activeDeviceId: null,
      matchesSelectedDevice: false,
      series: { rows: [], byMetric: {} },
    })),
    safeLiveRequest(() => fetchLiveEvents(selectedDeviceId), () => ({ ok: true, selectedDeviceId, activeDeviceId: null, matchesSelectedDevice: false, events: [] })),
    safeLiveRequest(() => fetchLiveTraffic(), () => getLiveDefaultTraffic(selectedDeviceId)),
    safeLiveRequest(() => fetchLiveParameters(selectedDeviceId), () => getLiveDefaultParameters(selectedDeviceId)),
    safeLiveRequest(() => fetchLiveSessionMeta(selectedDeviceId), () => getLiveDefaultMeta(selectedDeviceId)),
    safeLiveRequest(() => fetchAllDeviceStatuses(), () => ({ ok: true, deviceStatuses: {}, globalRunning: false })),
  ]);
  if ((uiState.live.selectedDeviceId || null) !== selectedDeviceId) return;
  uiState.live.sessionStatus = sessionStatus;
  uiState.live.snapshotPayload = snapshotPayload;
  uiState.live.seriesPayload = seriesPayload;
  uiState.live.eventsPayload = eventsPayload;
  uiState.live.trafficPayload = trafficPayload;
  uiState.live.parametersPayload = parametersPayload;
  uiState.live.metaPayload = metaPayload;
  uiState.live.deviceStatuses = deviceStatusesPayload?.deviceStatuses || {};
}

function ensureLivePolling() {
  if (uiState.live.pollTimer) {
    window.clearInterval(uiState.live.pollTimer);
    uiState.live.pollTimer = null;
  }
  const activeSession = uiState.live.sessionStatus?.activeSession || {};
  const globalRunning = uiState.live.sessionStatus?.state?.running || activeSession.running;
  if (!globalRunning) return;
  uiState.live.pollTimer = window.setInterval(async () => {
    if (uiState.live.pollBusy) return;
    uiState.live.pollBusy = true;
    try {
      await refreshLiveRuntimeData();
      if (uiState.currentView === "live") {
        updateLiveDeviceStatusClasses();
        renderLiveOverview();
        renderLiveCurveChart();
        renderLiveSessionSummary();
        renderLiveDebugPanel();
        refreshLiveStatusNotice();
      }
    } catch (error) {
      setLiveStatusNotice(`实时刷新失败：${error.message}`);
    } finally {
      uiState.live.pollBusy = false;
    }
  }, 1000);
}

function renderLiveView() {
  const globalRunning = uiState.live.sessionStatus?.state?.running || uiState.live.sessionStatus?.activeSession?.running;
  const startBtn = qs("liveStartBtn");
  const stopBtn = qs("liveStopBtn");
  if (startBtn && stopBtn) {
    startBtn.classList.toggle("primary", !globalRunning);
    startBtn.classList.toggle("secondary", globalRunning);
    stopBtn.classList.toggle("primary", globalRunning);
    stopBtn.classList.toggle("secondary", !globalRunning);
  }
  ensureLiveCurveLayout();
  renderLiveDeviceList();
  renderLiveDeviceEditor();
  bindLiveDeviceEditorInputs();
  renderLiveSessionSummary();
  renderLiveCatalogSummary();
  renderLiveCatalogTable();
  renderLivePollingCommandEditor();
  renderLiveOverview();
  renderLiveCurveChart();
  renderLiveParameterMonitor();
  renderLiveDebugPanel();
  bindLiveDeviceActions();
  bindLiveDevicesConfigImport();
  bindLiveWindowTabs();
  ensureLivePolling();
  if (uiState.activeTab.live) switchViewTab("live", uiState.activeTab.live);
}

async function refreshLiveModule() {
  const [devicesPayload, catalogPayload] = await Promise.all([
    fetchLiveDevices(),
    fetchLiveCatalog(),
  ]);
  const previousSelectedDeviceId = uiState.live.selectedDeviceId;
  uiState.live.devicesPayload = devicesPayload;
  uiState.live.catalogPayload = catalogPayload;
  uiState.live.selectedDeviceId = previousSelectedDeviceId && devicesPayload.devices?.some((item) => item.id === previousSelectedDeviceId)
    ? previousSelectedDeviceId
    : (devicesPayload.selectedDeviceId || devicesPayload.devices?.[0]?.id || null);
  uiState.live.selectedDeviceDraft = buildLiveDeviceDraft(getSelectedLiveDevice());
  resetLiveProjection(uiState.live.selectedDeviceId);
  await refreshLiveRuntimeData();
  renderLiveView();
  refreshLiveStatusNotice();
}

function normalizeAnalysisPayload(analysis) {
  const raw = analysis.raw_data || {};
  const config = analysis.config || {};
  const envRows = (raw.environment_rows || []).map((row) => ({
    timestamp: toDate(row.ts),
    pressure: Number(row.pressure),
    temperature: Number(row.temperature),
    flow: Number(row.flow),
    humidity: Number(row.humidity),
    source_file: row.source_file || "",
    line_number: row.line_number || 0,
  })).filter((row) => row.timestamp instanceof Date && !Number.isNaN(row.timestamp.getTime()));
  const breathRows = (raw.breath_rows || []).map((row) => ({
    timestamp: toDate(row.ts),
    state: Number(row.state),
    state_name: row.state_name || STATE_LABELS[row.state] || String(row.state),
    flow_rate: Number(row.flow_rate),
    elapsed_since_change: Number(row.elapsed_since_change),
    rhythm: Number(row.rhythm),
    rhythm_name: row.rhythm_name || RHYTHM_LABELS[row.rhythm] || String(row.rhythm),
    source_file: row.source_file || "",
    line_number: row.line_number || 0,
  })).filter((row) => row.timestamp instanceof Date && !Number.isNaN(row.timestamp.getTime()));
  const runRows = (raw.run_rows || []).map((row) => ({
    timestamp: toDate(row.ts),
    level: row.level,
    message: row.message,
    source_file: row.source_file || "",
    line_number: row.line_number || 0,
  })).filter((row) => row.timestamp instanceof Date && !Number.isNaN(row.timestamp.getTime()));
  const allDates = raw.available_dates || buildAvailableDates(envRows, breathRows, runRows);
  return { config, envRows, breathRows, runRows, availableDates: allDates, meta: analysis.meta || {} };
}

function buildAvailableDates(envRows, breathRows, runRows) {
  const dates = new Set();
  [envRows, breathRows, runRows].forEach((rows) => {
    for (let i = 0; i < rows.length; i += 1) {
      dates.add(toIsoText(rows[i].timestamp).slice(0, 10));
    }
  });
  return [...dates].sort();
}

function buildSummaryText(analysis) {
  return [
    "YLDQ 数据分析摘要",
    "====================",
    `生成时间: ${formatDateTime(analysis.meta.generated_at)}`,
    `时间范围: ${analysis.overview.start_at || "-"} -> ${analysis.overview.end_at || "-"}`,
    `环境日志: ${analysis.environment.total_rows} 条`,
    `呼吸日志: ${analysis.breath.total_rows} 条`,
    `运行日志: ${analysis.run_log.total_rows} 条`,
    "",
    ...analysis.insights.map((item) => `- [${item.level}] ${item.title}: ${item.detail}`),
    "",
  ].join("\n");
}

function analyzeEnvironment(rows, config) {
  if (!rows.length) {
    return {
      total_rows: 0,
      files: 0,
      interval_label: "-",
      metrics: {},
      threshold_breaches: {},
      quality: { duplicates: 0, gap_count: 0, largest_gap_sec: 0, malformed_rows: 0, avg_daily_completeness_pct: 0, anomalies: [] },
      daily: [],
      series: [],
    };
  }
  const intervalSec = computeMedianInterval(rows, "timestamp", 60);
  let duplicates = 0;
  let gapCount = 0;
  let largestGapSec = 0;
  const anomalies = [];
  for (let i = 1; i < rows.length; i += 1) {
    const diff = Math.round((rows[i].timestamp - rows[i - 1].timestamp) / 1000);
    if (diff === 0) duplicates += 1;
    if (diff > Math.max(intervalSec * 2, intervalSec + 10)) {
      gapCount += 1;
      largestGapSec = Math.max(largestGapSec, diff);
      anomalies.push({
        type: "gap",
        start_at: toIsoText(rows[i - 1].timestamp),
        end_at: toIsoText(rows[i].timestamp),
        gap_minutes: Number((diff / 60).toFixed(1)),
      });
    }
  }

  const sectionMap = {
    pressure: "PressureValue",
    temperature: "Temperature",
    flow: "RespiratoryRate",
    humidity: "HumidityValue",
  };

  const metrics = {};
  const thresholdBreaches = {};
  Object.keys(METRICS).forEach((key) => {
    const values = rows.map((row) => row[key]);
    const section = config?.[sectionMap[key]] || {};
    const thresholds = key === "flow"
      ? { heatOn: section.HeatOnThreshold ?? null, heatOff: section.HeatOffThreshold ?? null }
      : { high: section.HThreshold ?? null, low: section.LThreshold ?? null };
    metrics[key] = {
      label: METRICS[key].label,
      unit: METRICS[key].unit,
      latest: Number(values[values.length - 1].toFixed(2)),
      thresholds,
      stats: computeStats(values),
    };
    thresholdBreaches[key] = {
      high: values.filter((value) => thresholds.high !== null && value > thresholds.high).length,
      low: values.filter((value) => thresholds.low !== null && value < thresholds.low).length,
    };
  });

  const groups = new Map();
  rows.forEach((row) => {
    const date = toIsoText(row.timestamp).slice(0, 10);
    if (!groups.has(date)) groups.set(date, []);
    groups.get(date).push(row);
  });

  const expectedPerDay = Math.max(1, Math.round((24 * 60 * 60) / intervalSec));
  const daily = [...groups.entries()].map(([date, items]) => {
    const entry = {
      date,
      count: items.length,
      completeness_pct: Number(((items.length / expectedPerDay) * 100).toFixed(1)),
    };
    Object.keys(METRICS).forEach((key) => {
      const values = items.map((row) => row[key]);
      const range = minMax(values, 0);
      entry[`${key}_avg`] = Number(mean(values).toFixed(2));
      entry[`${key}_min`] = Number(range.min.toFixed(2));
      entry[`${key}_max`] = Number(range.max.toFixed(2));
    });
    if (entry.completeness_pct < 85) {
      anomalies.push({ type: "low_daily_completeness", date, completeness_pct: entry.completeness_pct });
    }
    return entry;
  });

  const series = downsample(rows.map((row) => ({
    ts: toIsoText(row.timestamp),
    pressure: Number(row.pressure.toFixed(2)),
    temperature: Number(row.temperature.toFixed(2)),
    flow: Number(row.flow.toFixed(2)),
    humidity: Number(row.humidity.toFixed(2)),
  })), 900);

  return {
    total_rows: rows.length,
    files: new Set(rows.map((row) => row.source_file)).size,
    start_at: toIsoText(rows[0].timestamp),
    end_at: toIsoText(rows[rows.length - 1].timestamp),
    interval_sec: intervalSec,
    interval_label: intervalSec % 60 === 0 ? `${intervalSec / 60} 分钟` : `${intervalSec} 秒`,
    metrics,
    threshold_breaches: thresholdBreaches,
    quality: {
      duplicates,
      gap_count: gapCount,
      largest_gap_sec: largestGapSec,
      malformed_rows: 0,
      avg_daily_completeness_pct: Number(mean(daily.map((item) => item.completeness_pct)).toFixed(2)),
      anomalies: anomalies.slice(0, 30),
    },
    daily,
    series,
  };
}

function analyzeBreath(rows, config) {
  if (!rows.length) {
    return {
      total_rows: 0,
      files: 0,
      state_counts: [],
      rhythm_counts: [],
      flow_distribution: { positive: 0, negative: 0, near_zero: 0 },
      session_summary: { segments: 0, avg_duration_sec: 0, longest_duration_sec: 0 },
      quality: { malformed_rows: 0, longest_elapsed_sec: 0, no_change_alarm_sec: null },
      daily: [],
      series: [],
      insights: [],
    };
  }
  const stateCounts = {};
  const rhythmCounts = {};
  rows.forEach((row) => {
    stateCounts[row.state] = (stateCounts[row.state] || 0) + 1;
    rhythmCounts[row.rhythm] = (rhythmCounts[row.rhythm] || 0) + 1;
  });

  const sessions = [];
  let openStart = null;
  rows.forEach((row) => {
    if (row.rhythm === 2) openStart = row.timestamp;
    if (row.rhythm === 3 && openStart) {
      sessions.push((row.timestamp - openStart) / 1000);
      openStart = null;
    }
  });

  const groups = new Map();
  rows.forEach((row) => {
    const date = toIsoText(row.timestamp).slice(0, 10);
    if (!groups.has(date)) groups.set(date, []);
    groups.get(date).push(row);
  });

  const daily = [...groups.entries()].map(([date, items]) => ({
    date,
    count: items.length,
    alarm_rows: items.filter((item) => item.state === 3 || item.state === 4).length,
    state_switches: items.filter((item) => item.rhythm === 1).length,
    segments_started: items.filter((item) => item.rhythm === 2).length,
    segments_closed: items.filter((item) => item.rhythm === 3).length,
    avg_abs_flow: Number(mean(items.map((item) => Math.abs(item.flow_rate))).toFixed(2)),
    max_abs_flow: Number(maxOf(items.map((item) => Math.abs(item.flow_rate)), 0).toFixed(2)),
  }));

  const longestElapsed = maxOf(rows.map((row) => row.elapsed_since_change), 0);
  const noChangeAlarmSec = config?.RespiratoryRate?.NoChangeAlarmTimeSec ?? null;
  const insights = [];
  if (noChangeAlarmSec && longestElapsed >= noChangeAlarmSec) {
    insights.push({
      level: "warning",
      title: "检测到长时间无变化窗口",
      detail: `最长持续 ${formatNumber(longestElapsed, 1)} 秒，已达到配置阈值 ${noChangeAlarmSec} 秒。`,
    });
  }
  if ((stateCounts[3] || 0) + (stateCounts[4] || 0) > 0) {
    insights.push({
      level: "warning",
      title: "呼吸日志存在告警状态",
      detail: `低流速告警 ${stateCounts[3] || 0} 次，高流速告警 ${stateCounts[4] || 0} 次。`,
    });
  }

  return {
    total_rows: rows.length,
    files: new Set(rows.map((row) => row.source_file)).size,
    start_at: toIsoText(rows[0].timestamp),
    end_at: toIsoText(rows[rows.length - 1].timestamp),
    state_counts: Object.entries(stateCounts).map(([state, count]) => ({
      state: Number(state),
      state_name: STATE_LABELS[state] || `状态 ${state}`,
      count,
    })),
    rhythm_counts: Object.entries(rhythmCounts).map(([rhythm, count]) => ({
      rhythm: Number(rhythm),
      rhythm_name: RHYTHM_LABELS[rhythm] || `节律 ${rhythm}`,
      count,
    })),
    flow_distribution: {
      positive: rows.filter((row) => row.flow_rate > 0).length,
      negative: rows.filter((row) => row.flow_rate < 0).length,
      near_zero: rows.filter((row) => row.flow_rate === 0).length,
    },
    session_summary: {
      segments: sessions.length,
      avg_duration_sec: sessions.length ? Number(mean(sessions).toFixed(1)) : 0,
      longest_duration_sec: sessions.length ? Number(maxOf(sessions, 0).toFixed(1)) : 0,
    },
    quality: {
      malformed_rows: 0,
      longest_elapsed_sec: Number(longestElapsed.toFixed(1)),
      no_change_alarm_sec: noChangeAlarmSec,
    },
    daily,
    series: downsample(rows.map((row) => ({
      ts: toIsoText(row.timestamp),
      flow_rate: Number(row.flow_rate.toFixed(2)),
      state: row.state,
      state_name: row.state_name,
      elapsed_since_change: Number(row.elapsed_since_change.toFixed(2)),
      rhythm: row.rhythm,
    })), 1600),
    insights,
  };
}

function analyzeRun(rows) {
  if (!rows.length) {
    return {
      total_rows: 0,
      files: 0,
      levels: { info: 0, warn: 0, error: 0 },
      daily: [],
      keyword_counts: [],
      important_events: [],
      quality: { malformed_rows: 0 },
    };
  }
  const levelCounts = { info: 0, warn: 0, error: 0 };
  const dailyMap = new Map();
  const keywordMap = new Map();
  const importantEvents = [];
  // 预编译关键词，避免每次循环重新创建数组和调用toLowerCase
  const keywordEntries = [
    { key: "watchdog", test: /watchdog/ },
    { key: "flow", test: /flow|\[flow\]|getflow/ },
    { key: "alarm", test: /alarm|online err|err out/ },
    { key: "valve", test: /open|close|ch1|ch2|drain|cht|hct|htc1|htc2|heatchannel|valve|antifreeze|220v|12v/ },
    { key: "i2c", test: /i2c|bus recovery/ },
    { key: "iec61850", test: /iec61850/ },
  ];
  const importantRe = /alarm|failed|recover|open|close|watchdog|online|manual heat|antifreeze|valve|heatchannel|exhaletimeout|humidity/i;

  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i];
    const level = row.level;
    if (level === "I") levelCounts.info += 1;
    else if (level === "W") levelCounts.warn += 1;
    else if (level === "E") levelCounts.error += 1;

    const date = toIsoText(row.timestamp).slice(0, 10);
    let dailyItem = dailyMap.get(date);
    if (!dailyItem) {
      dailyItem = { date, info: 0, warn: 0, error: 0 };
      dailyMap.set(date, dailyItem);
    }
    if (level === "I") dailyItem.info += 1;
    else if (level === "W") dailyItem.warn += 1;
    else if (level === "E") dailyItem.error += 1;

    const message = row.message;
    const lower = message.toLowerCase();
    for (let k = 0; k < keywordEntries.length; k += 1) {
      if (keywordEntries[k].test.test(lower)) {
        const key = keywordEntries[k].key;
        keywordMap.set(key, (keywordMap.get(key) || 0) + 1);
      }
    }

    if (level !== "I" || importantRe.test(message)) {
      importantEvents.push({
        ts: toIsoText(row.timestamp),
        level: level,
        message: message,
      });
    }
  }

  const sortedKeywords = [];
  keywordMap.forEach((count, keyword) => sortedKeywords.push({ keyword, count }));
  sortedKeywords.sort((a, b) => b.count - a.count);

  return {
    total_rows: rows.length,
    files: new Set(rows.map((row) => row.source_file)).size,
    start_at: toIsoText(rows[0].timestamp),
    end_at: toIsoText(rows[rows.length - 1].timestamp),
    levels: levelCounts,
    daily: [...dailyMap.values()],
    keyword_counts: sortedKeywords,
    important_events: importantEvents.slice(-180),
    quality: { malformed_rows: 0 },
  };
}

function buildConfigSnapshot(config) {
  return {
    version: config?.ver || null,
    config_time: config?.curDateTime || null,
    double_mode: config?.DoubleMode ?? null,
    double_switch: config?.DoubleSwitch ?? null,
    force_close_sec: config?.ForceClose ?? null,
    temperature: config?.Temperature || {},
    humidity: config?.HumidityValue || {},
    pressure: config?.PressureValue || {},
    respiratory: config?.RespiratoryRate || {},
    out_online: config?.outOnline || {},
    tasks: Array.isArray(config?.TaskArray)
      ? config.TaskArray.map((item) => ({
          name: item.name,
          start_time: item.StartTime,
          delay_sec: item.delay,
          humidity: item.HumidityValue || {},
          respiratory: item.RespiratoryRate || {},
        }))
      : [],
  };
}

function buildInsights(environment, breath, runLog) {
  const insights = [];
  if ((environment.quality?.gap_count || 0) > 0) {
    insights.push({
      level: "warning",
      title: "环境日志存在断档",
      detail: `共识别到 ${environment.quality.gap_count} 个断档，最长 ${formatDuration(environment.quality.largest_gap_sec)}。`,
    });
  }
  const flow = environment.threshold_breaches?.flow || {};
  if ((flow.high || 0) + (flow.low || 0) > 0) {
    insights.push({
      level: "warning",
      title: "流速出现阈值越界",
      detail: `高阈值越界 ${flow.high || 0} 次，低阈值越界 ${flow.low || 0} 次。`,
    });
  }
  if ((runLog.levels?.error || 0) > 0) {
    insights.push({
      level: "critical",
      title: "运行日志存在错误记录",
      detail: `当前样本共记录错误 ${runLog.levels.error} 条，建议结合事件时间线排查。`,
    });
  }
  insights.push(...(breath.insights || []));
  if (!insights.length) {
    insights.push({
      level: "ok",
      title: "未发现明显高风险项",
      detail: "当前样本未触发默认规则，可继续查看趋势、累计量和日志事件。",
    });
  }
  return insights;
}

function buildAnalysisFromSource(sourceData, meta = {}) {
  const environment = analyzeEnvironment(sourceData.envRows, sourceData.config);
  const breath = analyzeBreath(sourceData.breathRows, sourceData.config);
  const run_log = analyzeRun(sourceData.runRows);
  const starts = [environment.start_at, breath.start_at, run_log.start_at].filter(Boolean).sort();
  const ends = [environment.end_at, breath.end_at, run_log.end_at].filter(Boolean).sort();
  const overview = {
    start_at: starts[0] || null,
    end_at: ends[ends.length - 1] || null,
    latest_environment_sample: environment.series[environment.series.length - 1] || null,
    env_file_count: environment.files,
    breath_file_count: breath.files,
    run_file_count: run_log.files,
  };
  const analysis = {
    meta: {
      generated_at: meta.generated_at || formatDateTime(new Date()),
      data_root: meta.data_root || "导入数据",
    },
    overview,
    config: sourceData.config,
    config_snapshot: buildConfigSnapshot(sourceData.config),
    environment,
    breath,
    run_log,
    raw_data: {
      available_dates: sourceData.availableDates,
      environment_rows: sourceData.envRows.map((row) => ({
        ts: toIsoText(row.timestamp),
        pressure: row.pressure,
        temperature: row.temperature,
        flow: row.flow,
        humidity: row.humidity,
        source_file: row.source_file,
        line_number: row.line_number,
      })),
      breath_rows: sourceData.breathRows.map((row) => ({
        ts: toIsoText(row.timestamp),
        state: row.state,
        state_name: row.state_name,
        flow_rate: row.flow_rate,
        elapsed_since_change: row.elapsed_since_change,
        rhythm: row.rhythm,
        rhythm_name: row.rhythm_name,
        source_file: row.source_file,
        line_number: row.line_number,
      })),
      run_rows: sourceData.runRows.map((row) => ({
        ts: toIsoText(row.timestamp),
        level: row.level,
        message: row.message,
        source_file: row.source_file,
        line_number: row.line_number,
      })),
    },
  };
  analysis.insights = buildInsights(environment, breath, run_log);
  analysis.summary_text = buildSummaryText(analysis);
  return analysis;
}

function makeOverviewCards(analysis) {
  const overview = analysis.overview;
  const environment = analysis.environment;
  const breath = analysis.breath;
  const runLog = analysis.run_log;
  const latest = overview.latest_environment_sample;
  const cards = [
    {
      label: "时间覆盖",
      value: overview.start_at && overview.end_at ? `${overview.start_at.slice(0, 10)} -> ${overview.end_at.slice(5, 10)}` : "-",
      detail: `生成时间 ${formatDateTime(analysis.meta.generated_at)}`,
    },
    {
      label: "环境日志",
      value: environment.total_rows.toLocaleString(),
      detail: `文件 ${environment.files} 个，采样间隔 ${environment.interval_label || "-"}`,
    },
    {
      label: "呼吸事件",
      value: breath.total_rows.toLocaleString(),
      detail: `片段 ${breath.session_summary?.segments ?? 0} 个，最长 ${formatDuration(breath.session_summary?.longest_duration_sec ?? 0)}`,
    },
    {
      label: "运行日志",
      value: runLog.total_rows.toLocaleString(),
      detail: `告警 ${runLog.levels?.warn ?? 0} 条，错误 ${runLog.levels?.error ?? 0} 条`,
    },
    {
      label: "完整率",
      value: `${formatNumber(environment.quality?.avg_daily_completeness_pct ?? 0, 1)}%`,
      detail: `断档 ${environment.quality?.gap_count ?? 0} 个，重复 ${environment.quality?.duplicates ?? 0} 条`,
    },
  ];
  if (latest) {
    cards.push({
      label: "最新环境点",
      value: latest.ts.slice(11, 16),
      detail: `P ${formatNumber(latest.pressure)} | T ${formatNumber(latest.temperature)} | F ${formatNumber(latest.flow)} | H ${formatNumber(latest.humidity)}`,
    });
  }
  return cards.map((card) => `
    <article class="overview-card">
      <div class="overview-label">${escapeHtml(card.label)}</div>
      <div class="overview-value">${escapeHtml(card.value)}</div>
      <div class="overview-detail">${escapeHtml(card.detail)}</div>
    </article>
  `).join("");
}

function buildSvgLineChart(points, options) {
  if (!points.length) return `<div class="empty-state">没有可绘制的数据</div>`;
  const width = 1040;
  const height = options.height || 320;
  const padding = { top: 24, right: 24, bottom: 34, left: 56 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const values = points.map((point) => point.value);
  const minRef = options.thresholdLow ?? Math.min(...values);
  const maxRef = options.thresholdHigh ?? Math.max(...values);
  const minValue = Math.min(...values, minRef);
  const maxValue = Math.max(...values, maxRef);
  const span = maxValue === minValue ? 1 : maxValue - minValue;
  const xAt = (index) => padding.left + (index / Math.max(points.length - 1, 1)) * innerWidth;
  const yAt = (value) => padding.top + innerHeight - ((value - minValue) / span) * innerHeight;
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${xAt(index)},${yAt(point.value)}`).join(" ");
  const area = `${path} L ${xAt(points.length - 1)},${padding.top + innerHeight} L ${xAt(0)},${padding.top + innerHeight} Z`;
  const seriesData = JSON.stringify(points.map((point, index) => ({
    x: Math.round(xAt(index)),
    y: Math.round(yAt(point.value)),
    v: point.value,
    label: point.label,
    ts: point.ts || (point.timestamp ? new Date(point.timestamp).getTime() : undefined),
  })));
  const grid = [0, 0.25, 0.5, 0.75, 1].map((step) => {
    const y = padding.top + innerHeight - step * innerHeight;
    const value = minValue + step * span;
    return `
      <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="rgba(31,42,48,0.12)" stroke-dasharray="4 6" />
      <text x="${padding.left - 10}" y="${y + 4}" text-anchor="end" font-size="12" fill="#6f7b7f">${formatNumber(value)}</text>
    `;
  }).join("");
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" data-series='${seriesData}'>
      <defs>
        <linearGradient id="lineAreaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="${options.color}" stop-opacity="0.28"></stop>
          <stop offset="100%" stop-color="${options.color}" stop-opacity="0.02"></stop>
        </linearGradient>
      </defs>
      ${grid}
      ${options.thresholdHigh !== null && options.thresholdHigh !== undefined ? `<line x1="${padding.left}" y1="${yAt(options.thresholdHigh)}" x2="${width - padding.right}" y2="${yAt(options.thresholdHigh)}" stroke="#b93030" stroke-dasharray="8 6" />` : ""}
      ${options.thresholdLow !== null && options.thresholdLow !== undefined ? `<line x1="${padding.left}" y1="${yAt(options.thresholdLow)}" x2="${width - padding.right}" y2="${yAt(options.thresholdLow)}" stroke="#2c6d76" stroke-dasharray="8 6" />` : ""}
      <path d="${area}" fill="url(#lineAreaGradient)"></path>
      <path d="${path}" fill="none" stroke="${options.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></path>
    </svg>
    <div class="chart-legend">
      <div class="legend-chip"><span style="background:${options.color}"></span>${escapeHtml(options.legend)}</div>
    </div>
  `;
}

function buildBreathFocusChart(series, respiratoryConfig = {}) {
  if (!series.length) return `<div class="empty-state">当前筛选范围内没有呼吸流速数据</div>`;
  const width = 1260;
  const height = 720;
  const padding = { top: 28, right: 28, bottom: 46, left: 64 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const values = series.map((item) => Number(item.flow_rate));
  const thresholdDefs = [
    { key: "HeatOnThreshold", label: "加热开启阈值", color: "#dc2626", value: Number(respiratoryConfig.HeatOnThreshold) },
    { key: "DERangeHT", label: "吸气判定上界", color: "#2563eb", value: Number(respiratoryConfig.DERangeHT) },
    { key: "DERangeLT", label: "呼气判定下界", color: "#16a34a", value: Number(respiratoryConfig.DERangeLT) },
    { key: "HeatOffThreshold", label: "加热关闭阈值", color: "#ea580c", value: Number(respiratoryConfig.HeatOffThreshold) },
  ].filter((item) => Number.isFinite(item.value));
  const maxAbs = Math.max(10, ...values.map((value) => Math.abs(value)), ...thresholdDefs.map((item) => Math.abs(item.value)));
  const minValue = -maxAbs;
  const maxValue = maxAbs;
  const span = maxValue - minValue || 1;
  const xAt = (index) => padding.left + (index / Math.max(series.length - 1, 1)) * innerWidth;
  const yAt = (value) => padding.top + innerHeight - ((value - minValue) / span) * innerHeight;

  const seriesData = JSON.stringify(series.map((item, index) => {
    const stateMeta = BREATH_STATE_META[item.state] || BREATH_STATE_META["-1"];
    const rhythmName = RHYTHM_LABELS[item.rhythm] || item.rhythm_name || "";
    return {
      x: Math.round(xAt(index)),
      y: Math.round(yAt(item.flow_rate)),
      v: item.flow_rate,
      label: rhythmName ? `${stateMeta.label} | ${rhythmName}` : stateMeta.label,
      ts: new Date(item.ts).getTime(),
    };
  }));

  const grid = [-1, -0.5, 0, 0.5, 1].map((step) => {
    const value = step * maxAbs;
    const y = yAt(value);
    const isZero = value === 0;
    return `
      <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="${isZero ? "rgba(15,23,42,0.38)" : "rgba(31,42,48,0.10)"}" stroke-dasharray="${isZero ? "none" : "4 6"}" />
      <text x="${padding.left - 10}" y="${y + 4}" text-anchor="end" font-size="12" fill="#64748b">${formatNumber(value)}</text>
    `;
  }).join("");

  const stateRuns = [];
  let runStart = 0;
  for (let i = 1; i <= series.length; i += 1) {
    if (i === series.length || series[i].state !== series[runStart].state) {
      stateRuns.push({ start: runStart, end: i - 1, state: series[runStart].state });
      runStart = i;
    }
  }

  const segmentPaths = stateRuns.map((run) => {
    const meta = BREATH_STATE_META[run.state] || BREATH_STATE_META["-1"];
    const pointIndexes = [];
    if (run.start > 0) pointIndexes.push(run.start - 1);
    for (let i = run.start; i <= run.end; i += 1) pointIndexes.push(i);
    const path = pointIndexes.map((pointIndex, idx) => {
      const point = series[pointIndex];
      return `${idx === 0 ? "M" : "L"}${xAt(pointIndex)},${yAt(point.flow_rate)}`;
    }).join(" ");
    return `<path d="${path}" fill="none" stroke="${meta.color}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"></path>`;
  }).join("");

  const thresholdLines = thresholdDefs.map((item) => `
    <line x1="${padding.left}" y1="${yAt(item.value)}" x2="${width - padding.right}" y2="${yAt(item.value)}" stroke="${item.color}" stroke-width="1.6" stroke-dasharray="8 6" opacity="0.88"></line>
    <text x="${width - padding.right - 4}" y="${yAt(item.value) - 6}" text-anchor="end" font-size="11" fill="${item.color}">${escapeHtml(item.label)} ${escapeHtml(formatNumber(item.value))}</text>
  `).join("");

  const stateLabels = stateRuns.map((run) => {
    const meta = BREATH_STATE_META[run.state] || BREATH_STATE_META["-1"];
    const centerX = (xAt(run.start) + xAt(run.end)) / 2;
    if (Math.abs(xAt(run.end) - xAt(run.start)) < 34) return "";
    return `<text x="${centerX}" y="${padding.top + 14}" text-anchor="middle" font-size="11" fill="${meta.color}" font-weight="700">${escapeHtml(meta.label)}</text>`;
  }).join("");

  const firstTs = escapeHtml(series[0].ts.slice(5, 16));
  const lastTs = escapeHtml(series[series.length - 1].ts.slice(5, 16));
  const chartLegend = [
    `<div class="legend-chip"><span style="background:#0f172a"></span>按状态分段着色</div>`,
    ...thresholdDefs.map((item) => `<div class="legend-chip"><span style="background:${item.color}"></span>${escapeHtml(item.label)} ${escapeHtml(formatNumber(item.value))}</div>`),
  ].join("");

  return `
    <svg class="chart-svg breath-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" data-series='${seriesData}'>
      ${grid}
      ${thresholdLines}
      ${stateLabels}
      ${segmentPaths}
      <text x="${padding.left}" y="${height - 14}" font-size="11" fill="#64748b">${firstTs}</text>
      <text x="${width - padding.right}" y="${height - 14}" text-anchor="end" font-size="11" fill="#64748b">${lastTs}</text>
    </svg>
    <div class="chart-legend">${chartLegend}</div>
  `;
}

function buildSvgBarChart(items, options = {}) {
  if (!items.length) return `<div class="empty-state">没有可绘制的数据</div>`;
  const width = 960;
  const height = options.height || 300;
  const padding = { top: 20, right: 20, bottom: 54, left: 50 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(...items.map((item) => item.value), 1);
  const barWidth = innerWidth / items.length;
  const bars = items.map((item, index) => {
    const valueHeight = (item.value / maxValue) * innerHeight;
    const x = padding.left + index * barWidth + barWidth * 0.14;
    const y = padding.top + innerHeight - valueHeight;
    const widthPx = Math.max(8, barWidth * 0.72);
    return `
      <rect x="${x}" y="${y}" width="${widthPx}" height="${valueHeight}" rx="8" fill="${item.color || options.color || "#2c6d76"}"></rect>
      <text x="${x + widthPx / 2}" y="${y - 6}" text-anchor="middle" font-size="11" fill="#6f7b7f">${formatNumber(item.value, options.digits ?? 0)}</text>
      <text x="${x + widthPx / 2}" y="${height - 16}" text-anchor="middle" font-size="11" fill="#6f7b7f">${escapeHtml(item.label)}</text>
    `;
  }).join("");
  return `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">${bars}</svg>`;
}

function buildSvgGroupedBarChart(items, keys, options = {}) {
  if (!items.length) return `<div class="empty-state">没有可绘制的数据</div>`;
  const width = 980;
  const height = options.height || 310;
  const padding = { top: 20, right: 20, bottom: 54, left: 48 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(1, ...items.flatMap((item) => keys.map((key) => Number(item[key.name] || 0))));
  const groupWidth = innerWidth / items.length;
  const barWidth = Math.min(26, (groupWidth * 0.74) / keys.length);
  const bars = items.map((item, index) => keys.map((key, keyIndex) => {
    const value = Number(item[key.name] || 0);
    const valueHeight = (value / maxValue) * innerHeight;
    const x = padding.left + index * groupWidth + groupWidth * 0.13 + keyIndex * barWidth;
    const y = padding.top + innerHeight - valueHeight;
    return `<rect x="${x}" y="${y}" width="${barWidth - 4}" height="${valueHeight}" rx="6" fill="${key.color}"></rect>`;
  }).join("")).join("");
  const labels = items.map((item, index) => {
    const x = padding.left + index * groupWidth + groupWidth * 0.34;
    return `<text x="${x}" y="${height - 16}" text-anchor="middle" font-size="11" fill="#6f7b7f">${escapeHtml((item.date || "").slice(-5) || item.date || "")}</text>`;
  }).join("");
  const legend = keys.map((key) => `<div class="legend-chip"><span style="background:${key.color}"></span>${escapeHtml(key.label)}</div>`).join("");
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">${bars}${labels}</svg>
    <div class="chart-legend">${legend}</div>
  `;
}

function renderTable(hostId, columns, rows) {
  const host = qs(hostId);
  if (!rows.length) {
    host.innerHTML = `<div class="empty-state">暂无数据</div>`;
    return;
  }
  const table = qs("tableTemplate").content.firstElementChild.cloneNode(true);
  table.querySelector("thead").innerHTML = `<tr>${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}</tr>`;
  table.querySelector("tbody").innerHTML = rows.map((row) => `<tr>${columns.map((column) => `<td>${column.render ? column.render(row) : escapeHtml(row[column.key] ?? "-")}</td>`).join("")}</tr>`).join("");
  host.innerHTML = "";
  host.appendChild(table);
}

function renderConfigSnapshot() {
  var orig = uiState.originalConfig || {};
  var curr = uiState.configPayload?.config || {};
  var hasChanges = JSON.stringify(orig) !== JSON.stringify(curr);
  var diffCount = getConfigDiffInfo(orig, curr).count;

  var MODULE_ORDER = [
    { key: "ver", label: "版本", color: "#78909C" },
    { key: "curDateTime", label: "配置时间", color: "#78909C" },
    { key: "DoubleMode", label: "双模式", color: "#78909C" },
    { key: "DoubleSwitch", label: "双开关", color: "#78909C" },
    { key: "ForceClose", label: "强制关闭", color: "#78909C" },
    { key: "Temperature", label: "温度参数", color: "#1E88E5" },
    { key: "HumidityValue", label: "湿度参数", color: "#43A047" },
    { key: "PressureValue", label: "压力参数", color: "#E53935" },
    { key: "RespiratoryRate", label: "呼吸参数", color: "#00ACC1" },
    { key: "outOnline", label: "联网参数", color: "#FB8C00" },
    { key: "TaskArray", label: "任务列表", color: "#8E24AA" },
  ];

  function hexToRgba(hex, alpha) {
    var r = parseInt(hex.slice(1, 3), 16);
    var g = parseInt(hex.slice(3, 5), 16);
    var b = parseInt(hex.slice(5, 7), 16);
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  }

  function getValue(obj, key) {
    return obj && typeof obj === "object" ? obj[key] : undefined;
  }

  function isSimple(val) {
    return val === null || val === undefined || typeof val !== "object";
  }

  function buildRowHtml(name, oVal, cVal, changed, color, indent) {
    var pad = indent ? ' style="padding-left:' + (24 + indent * 16) + 'px"' : "";
    var bg = changed ? ' style="background:' + hexToRgba(color, 0.07) + '"' : "";
    var nameStyle = changed ? ' style="color:' + color + ';font-weight:700"' : "";
    var origStyle = changed ? ' style="color:#9e9e9e;text-decoration:line-through"' : "";
    var currStyle = changed ? ' style="color:' + color + ';font-weight:700"' : "";
    return '<tr class="config-diff-row' + (changed ? " changed" : "") + '"' + bg + ">" +
      '<td class="config-diff-name"' + pad + nameStyle + ">" + escapeHtml(name) + "</td>" +
      '<td class="config-diff-orig"' + origStyle + ">" + escapeHtml(formatConfigVal(oVal)) + "</td>" +
      '<td class="config-diff-curr"' + currStyle + ">" + escapeHtml(formatConfigVal(cVal)) + "</td>" +
    "</tr>";
  }

  function buildModuleHtml(meta) {
    var key = meta.key;
    var ov = getValue(orig, key);
    var cv = getValue(curr, key);
    var color = meta.color;

    if (ov === undefined && cv === undefined) return "";

    var rowsHtml = "";
    var moduleChanged = false;

    if (key === "TaskArray" && (Array.isArray(ov) || Array.isArray(cv))) {
      var origArr = Array.isArray(ov) ? ov : [];
      var currArr = Array.isArray(cv) ? cv : [];
      var maxLen = Math.max(origArr.length, currArr.length);
      function appendTaskRows(namePrefix, oVal, cVal, indent) {
        if ((oVal && typeof oVal === "object" && !Array.isArray(oVal)) || (cVal && typeof cVal === "object" && !Array.isArray(cVal))) {
          var oObj = oVal && typeof oVal === "object" ? oVal : {};
          var cObj = cVal && typeof cVal === "object" ? cVal : {};
          var subKeys = Object.keys(oObj).concat(Object.keys(cObj).filter(function (k) { return !(k in oObj); })).sort();
          subKeys.forEach(function (subKey) {
            appendTaskRows(namePrefix ? namePrefix + "." + subKey : subKey, oObj[subKey], cObj[subKey], indent + 1);
          });
          return;
        }
        var changed = String(formatConfigVal(oVal)) !== String(formatConfigVal(cVal));
        if (changed) moduleChanged = true;
        taskRows += buildRowHtml(namePrefix, oVal, cVal, changed, color, indent);
        if (changed) taskChanged = true;
      }
      for (var i = 0; i < maxLen; i++) {
        var oItem = origArr[i] || {};
        var cItem = currArr[i] || {};
        var oKeys = Object.keys(oItem);
        var cKeys = Object.keys(cItem);
        var allKeys = oKeys.concat(cKeys.filter(function (k) { return oKeys.indexOf(k) === -1; })).sort();
        var taskRows = "";
        var taskChanged = false;
        allKeys.forEach(function (ik) {
          appendTaskRows(ik, oItem[ik], cItem[ik], 1);
        });
        if (maxLen > 1) {
          rowsHtml += '<tr class="config-diff-task-header"><td colspan="3">' +
            "任务 " + (i + 1) +
            (taskChanged ? ' <span class="config-diff-badge" style="background:' + color + '">已修改</span>' : "") +
          "</td></tr>";
        }
        rowsHtml += taskRows;
        if (taskChanged) moduleChanged = true;
      }
    } else if (!isSimple(ov) || !isSimple(cv)) {
      var oObj = !isSimple(ov) ? ov : {};
      var cObj = !isSimple(cv) ? cv : {};
      var oKeys = Object.keys(oObj);
      var cKeys = Object.keys(cObj);
      var allKeys = oKeys.concat(cKeys.filter(function (k) { return oKeys.indexOf(k) === -1; })).sort();
      allKeys.forEach(function (subKey) {
        var oVal = oObj[subKey];
        var cVal = cObj[subKey];
        var changed = String(formatConfigVal(oVal)) !== String(formatConfigVal(cVal));
        if (changed) moduleChanged = true;
        rowsHtml += buildRowHtml(subKey, oVal, cVal, changed, color, 0);
      });
    } else {
      var changed = String(formatConfigVal(ov)) !== String(formatConfigVal(cv));
      if (changed) moduleChanged = true;
      rowsHtml += buildRowHtml(key, ov, cv, changed, color, 0);
    }

    if (!rowsHtml) return "";

    return '<div class="config-module-card" style="border-left-color:' + color + '">' +
      '<div class="config-module-header">' +
        '<span class="config-module-dot" style="background:' + color + '"></span>' +
        '<span class="config-module-title">' + escapeHtml(meta.label) + "</span>" +
        (moduleChanged ? '<span class="config-diff-badge" style="background:' + color + '">已修改</span>' : "") +
      "</div>" +
      '<table class="config-diff-table">' +
        "<thead><tr><th>参数名</th><th>原始参数（读取）</th><th>修改后参数</th></tr></thead>" +
        "<tbody>" + rowsHtml + "</tbody>" +
      "</table>" +
    "</div>";
  }

  var modulesHtml = MODULE_ORDER.map(buildModuleHtml).filter(Boolean).join("");
  var summaryHtml = hasChanges
    ? '<div class="config-diff-summary">原始参数为打开软件时读取的 config.json，修改后参数为在参数编辑页面保存后的配置，<strong>标色</strong>的项表示已变更。</div>'
    : '<div class="config-diff-summary">当前配置与原始 config.json 一致，未检测到修改。</div>';

  setConfigSnapshotStatus(hasChanges ? "当前相对原始配置已修改 " + diffCount + " 项。可在本页直接导出当前配置。" : "当前配置与原始配置一致。");
  qs("configDiff").innerHTML = summaryHtml +
    '<div class="config-modules-grid" style="padding:16px">' + (modulesHtml || '<div class="empty-state">暂无配置数据</div>') + '</div>';

  var quality = uiState.analysis?.environment?.quality || {};
  qs("qualityPanel").innerHTML =
    '<div class="pill-row">' +
      '<span class="pill">重复时间戳 <strong>' + (quality.duplicates ?? 0) + '</strong></span>' +
      '<span class="pill">时间断档 <strong>' + (quality.gap_count ?? 0) + '</strong></span>' +
      '<span class="pill">最长断档 <strong>' + formatDuration(quality.largest_gap_sec ?? 0) + '</strong></span>' +
      '<span class="pill">平均完整率 <strong>' + formatNumber(quality.avg_daily_completeness_pct ?? 0, 1) + '%</strong></span>' +
    '</div>' +
    '<div class="summary-stack" style="margin-top:12px">' +
      ((quality.anomalies || []).length
        ? quality.anomalies.slice(0, 8).map(function (item) { return item.type === "gap"
          ? '<div class="summary-item">断档 ' + escapeHtml(item.start_at) + ' -> ' + escapeHtml(item.end_at) + '，约 ' + escapeHtml(String(item.gap_minutes)) + ' 分钟</div>'
          : '<div class="summary-item">' + escapeHtml(item.date || "-") + ' 日完整率 ' + escapeHtml(String(item.completeness_pct || "-")) + '%</div>';
        }).join("")
        : '<div class="empty-state">当前未发现明显数据质量异常</div>') +
    '</div>';
}

function flattenConfig(obj, prefix) {
  prefix = prefix || "";
  var result = {};
  if (!obj || typeof obj !== "object") return result;
  Object.keys(obj).forEach(function (key) {
    var val = obj[key];
    var path = prefix ? prefix + "." + key : key;
    if (val && typeof val === "object" && !Array.isArray(val)) {
      var sub = flattenConfig(val, path);
      Object.keys(sub).forEach(function (k) { result[k] = sub[k]; });
    } else if (Array.isArray(val)) {
      val.forEach(function (item, i) {
        if (item && typeof item === "object") {
          var sub = flattenConfig(item, path + "[" + i + "]");
          Object.keys(sub).forEach(function (k) { result[k] = sub[k]; });
        } else {
          result[path + "[" + i + "]"] = item;
        }
      });
    } else {
      result[path] = val;
    }
  });
  return result;
}

function getConfigDiffInfo(orig, curr) {
  var origFlat = flattenConfig(orig || {});
  var currFlat = flattenConfig(curr || {});
  var allPaths = Array.from(new Set(Object.keys(origFlat).concat(Object.keys(currFlat))));
  var count = allPaths.filter(function (path) {
    return String(origFlat[path]) !== String(currFlat[path]);
  }).length;
  return { count: count, origFlat: origFlat, currFlat: currFlat };
}

function formatConfigVal(val) {
  if (val === null || val === undefined) return "-";
  if (typeof val === "boolean") return val ? "true" : "false";
  return String(val);
}

function getConfigValue(config, path) {
  return path.split(".").reduce((current, key) => (current && typeof current === "object" ? current[key] : null), config);
}

function setConfigValue(target, path, value) {
  const keys = path.split(".");
  let current = target;
  keys.slice(0, -1).forEach((key) => {
    if (!current[key] || typeof current[key] !== "object") current[key] = {};
    current = current[key];
  });
  current[keys[keys.length - 1]] = value;
}

function getTaskValue(task, path) {
  return getConfigValue(task, path);
}

function createDefaultTask(index) {
  return {
    name: `AutoParamOverride${index + 1}`,
    StartTime: "",
    delay: 604800,
    HumidityValue: {
      HThreshold: 20,
      LThreshold: 18,
    },
    RespiratoryRate: {
      HeatOnThreshold: -4,
      HeatOffThreshold: 1,
    },
  };
}

function parseFieldInputValue(field, rawValue, tagName) {
  if (field.type === "bool") return rawValue === true || rawValue === "true";
  if (field.type === "int") return Number.parseInt(rawValue, 10);
  if (field.type === "float") return Number.parseFloat(rawValue);
  if (field.type === "select") {
    const sample = field.options?.[0];
    const optionValue = typeof sample === "object" ? sample.value : sample;
    return typeof optionValue === "number" ? Number(rawValue) : rawValue;
  }
  return tagName === "SELECT" ? String(rawValue) : rawValue;
}

function renderTaskArrayEditor(field, tasks, editable) {
  const header = field.item_schema.map((item) => `<th>${escapeHtml(item.label)}</th>`).join("");
  const rows = tasks.length
    ? tasks.map((task, index) => `
      <tr>
        ${field.item_schema.map((item) => {
          const value = getTaskValue(task, item.key);
          if (item.type === "bool") {
            return `<td><select data-task-index="${index}" data-task-key="${escapeHtml(item.key)}" ${!editable ? "disabled" : ""}>
              <option value="true" ${value === true ? "selected" : ""}>是</option>
              <option value="false" ${value === false ? "selected" : ""}>否</option>
            </select></td>`;
          }
          const inputType = item.type === "int" || item.type === "float" ? "number" : "text";
          const step = item.type === "float" ? ` step="${escapeHtml(String(item.step || 0.1))}"` : "";
          return `<td><input type="${inputType}"${step} data-task-index="${index}" data-task-key="${escapeHtml(item.key)}" value="${escapeHtml(value ?? "")}" ${!editable ? "readonly" : ""}></td>`;
        }).join("")}
        <td>${editable ? `<button class="secondary" data-remove-task="${index}">删除</button>` : "-"}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="${field.item_schema.length + 1}" class="empty-state">当前没有任务</td></tr>`;
  return `
    <div class="config-field">
      <div class="config-field-label">
        <span>${escapeHtml(field.label)}</span>
        <span class="config-field-meta">TaskArray</span>
      </div>
      <p class="config-field-desc">${escapeHtml(field.description || "")}</p>
      <table class="task-table">
        <thead><tr>${header}<th>操作</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="task-editor-actions">
        ${editable ? '<button id="addTaskBtn" class="secondary">新增任务</button>' : '<span class="task-note">当前为只读模式</span>'}
        <div class="task-note">开始时间建议格式：YYYY/M/D-HH:mm:ss</div>
      </div>
    </div>
  `;
}

function renderConfigEditor() {
  var payload = uiState.configPayload;
  if (!payload || !payload.schema?.length) {
    qs("configTabs").innerHTML = "";
    qs("configEditor").innerHTML = `<div class="empty-state">当前模式下没有可编辑的配置 schema。导入数据后可以查看配置快照，若要保存请使用运行目录模式。</div>`;
    setConfigEditorStatus("当前模式：只读");
    return;
  }
  var editable = payload.editable && !IS_STATIC_REPORT;
  var recs = uiState.configRecommendations || {};

  // Tab bar
  var tabsHtml = payload.schema.map(function (sec, i) {
    return '<button class="view-tab' + (i === 0 ? ' active' : '') + '" data-view-tab="cfg-' + sec.key + '">' + escapeHtml(sec.title) + '</button>';
  }).join("");
  qs("configTabs").innerHTML = tabsHtml;
  bindViewTabs();

  // Sections
  var host = qs("configEditor");
  host.innerHTML = payload.schema.map(function (sec, i) {
    var fieldsHtml = sec.fields.map(function (field) {
      if (field.type === "task_array") {
        return renderTaskArrayEditor(field, payload.config.TaskArray || [], editable);
      }
      var rec = recs[field.path] || null;
      return renderConfigRow(field, getConfigValue(payload.config, field.path), editable, rec);
    }).join("");
    return '<div class="config-section view-tab-panel' + (i === 0 ? ' active' : '') + '" data-tab="cfg-' + sec.key + '">' +
      '<h3>' + escapeHtml(sec.title) + '</h3>' +
      '<p class="config-field-desc">' + escapeHtml(sec.description || "") + '</p>' +
      '<div class="config-row-list">' + fieldsHtml + '</div>' +
    '</div>';
  }).join("");

  bindConfigEditorEvents(editable);
  bindConfigRecApply();
  bindConfigRecTooltips();
  var diffCount = getConfigDiffInfo(uiState.originalConfig || {}, payload.config || {}).count;
  if (!editable) {
    setConfigEditorStatus("当前模式下配置为只读。");
  } else if (diffCount > 0) {
    setConfigEditorStatus("已修改 " + diffCount + " 项，尚未保存。");
  } else {
    setConfigEditorStatus(uiState.importedLocal ? "配置已加载，可在当前页面内编辑。" : "配置已加载，可编辑并保存到 config.json。");
  }
  if (uiState.activeTab.config) switchViewTab("config", uiState.activeTab.config);
}

function renderConfigRow(field, value, editable, rec) {
  var unit = field.unit ? " " + field.unit : "";
  var secNote = "";
  if (field.unit === "秒" && typeof value === "number" && value > 0) {
    var mins = value / 60;
    var hrs = value / 3600;
    if (hrs >= 1) secNote = " ( " + hrs.toFixed(2) + " 小时 / " + mins.toFixed(1) + " 分钟 )";
    else if (mins >= 1) secNote = " ( " + mins.toFixed(1) + " 分钟 )";
  }
  var range = field.min !== undefined || field.max !== undefined ? " [" + (field.min ?? "-") + " ~ " + (field.max ?? "-") + "]" : "";
  var meta = unit + secNote + range;
  var disabled = !editable || field.readonly;
  var control = "";
  if (field.type === "bool") {
    control = '<label class="config-checkbox-row">' +
      '<input type="checkbox" data-config-path="' + escapeHtml(field.path) + '" ' + (value ? "checked" : "") + (disabled ? " disabled" : "") + '>' +
      '<span>' + (value ? "开启" : "关闭") + '</span></label>';
  } else if (field.type === "select") {
    var opts = field.options.map(function (opt) {
      var v = typeof opt === "object" ? opt.value : opt;
      var l = typeof opt === "object" ? opt.label : opt;
      return '<option value="' + escapeHtml(String(v)) + '"' + (String(value) === String(v) ? " selected" : "") + '>' + escapeHtml(String(l)) + '</option>';
    }).join("");
    control = '<select data-config-path="' + escapeHtml(field.path) + '"' + (disabled ? " disabled" : "") + '>' + opts + '</select>';
  } else {
    var itype = field.type === "int" || field.type === "float" ? "number" : "text";
    var step = field.type === "float" ? ' step="' + (field.step || 0.1) + '"' : "";
    control = '<input type="' + itype + '"' + step + ' data-config-path="' + escapeHtml(field.path) + '" value="' + escapeHtml(value ?? "") + '"' + (disabled ? " readonly" : "") + '>';
  }

  // Recommendation box (shown next to control when recommendation exists)
  var recHtml = "";
  if (rec && editable) {
    var dots = rec.confidence === "high" ? "●●●" : rec.confidence === "medium" ? "●●○" : "●○○";
    var u = field.unit ? " " + field.unit : "";
    var recValue = rec.recommended_value;
    var recText = "";
    if (field.type === "int" || field.type === "float") recText = formatNumber(recValue);
    else if (field.type === "bool") recText = recValue ? "开启" : "关闭";
    else recText = String(recValue ?? "");
    recHtml = '<div class="config-rec-box" data-rec-tip="' + escapeHtml((rec.reason || "") + "\n\n" + (rec.risk_note || "")) + '">' +
      '<div class="config-rec-head">推荐值 <span class="config-rec-conf">' + dots + '</span></div>' +
      '<div class="config-rec-body">' +
        '<strong style="font-size:15px">' + escapeHtml(recText) + escapeHtml(u) + '</strong>' +
        '<button class="config-apply-rec-btn" data-apply-rec="' + escapeHtml(field.path) + '">套用</button>' +
      '</div>' +
    '</div>';
  }

  return '<div class="config-row">' +
    '<div class="config-row-label">' +
      '<strong>' + escapeHtml(field.label) + '</strong>' +
      '<span class="config-field-meta">' + escapeHtml(meta) + '</span>' +
    '</div>' +
    '<div class="config-row-control">' + control + recHtml + '</div>' +
    (field.description ? '<div class="config-row-desc">' + escapeHtml(field.description) + '</div>' : "") +
  '</div>';
}

function bindConfigRecApply() {
  qsa(".config-apply-rec-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var path = btn.dataset.applyRec;
      var rec = (uiState.configRecommendations || {})[path];
      if (!rec) return;
      applySingleRecommendation(path, rec.recommended_value);
    });
  });
}

function bindConfigRecTooltips() {
  var tipEl = document.getElementById("configRecTooltip");
  if (!tipEl) {
    tipEl = document.createElement("div");
    tipEl.id = "configRecTooltip";
    tipEl.className = "config-rec-tooltip hidden";
    document.body.appendChild(tipEl);
  }
  qsa(".config-rec-box").forEach(function (box) {
    box.addEventListener("mouseenter", function (e) {
      var text = box.dataset.recTip;
      if (!text) return;
      tipEl.textContent = text;
      tipEl.classList.remove("hidden");
      positionTooltip(tipEl, e);
    });
    box.addEventListener("mousemove", function (e) {
      positionTooltip(tipEl, e);
    });
    box.addEventListener("mouseleave", function () {
      tipEl.classList.add("hidden");
    });
  });
}

function positionTooltip(tip, e) {
  var x = e.clientX + 16;
  var y = e.clientY - 12;
  if (x + 320 > window.innerWidth) x = e.clientX - 330;
  if (y < 10) y = 10;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}

function applySingleRecommendation(path, value) {
  var el = document.querySelector('[data-config-path="' + escapeSelectorValue(path) + '"]');
  if (!el) return;
  if (el.type === "checkbox") {
    el.checked = Boolean(value);
  } else {
    el.value = value ?? "";
  }
  updateConfigDirtyStatus();
  setConfigEditorStatus("已套用推荐值：" + path + "，变更已加入当前草稿。");
}

// ── Generate recommendations ──

async function generateConfigRecommendations() {
  if (IS_STATIC_REPORT) {
    setConfigEditorStatus("静态报告模式无法生成推荐值。");
    return;
  }
  try {
    setConfigEditorStatus("正在分析历史数据生成推荐参数...");
    var data;
    if (uiState.importedLocal) {
      data = await fetchPreviewConfigRecommendations(
        collectConfigFromEditor(),
        clone(uiState.analysis?.raw_data || {}),
        uiState.configPayload?.schema || []
      );
    } else {
      var resp = await fetch("/api/parameter-recommendations?strategy=balanced&refresh=1");
      if (!resp.ok) {
        var errText = "";
        try { errText = await resp.text(); } catch (e) {}
        throw new Error("HTTP " + resp.status + (errText ? " " + errText.slice(0, 80) : ""));
      }
      data = await resp.json();
    }
    var map = {};
    (data.recommendations || []).forEach(function (rec) {
      map[rec.parameter_path] = rec;
    });
    uiState.configRecommendations = map;
    renderConfigEditor();
    var cnt = Object.keys(map).length;
    setConfigEditorStatus(cnt ? "已生成 " + cnt + " 项推荐参数，可逐项套用或手动修改后保存。" : "分析完成，当前数据暂无需调整的建议参数。");
  } catch (e) {
    setConfigEditorStatus("生成推荐值失败：" + e.message);
  }
}

// ── Keep existing helpers ──

function renderScalarField(field, value, editable) {
  return renderConfigRow(field, value, editable, null);
}

function bindConfigEditorEvents(editable) {
  if (!editable) return;
  const taskField = uiState.configPayload.schema.flatMap((section) => section.fields).find((field) => field.type === "task_array");
  qsa("[data-config-path]").forEach((input) => {
    input.addEventListener("input", updateConfigDirtyStatus);
    input.addEventListener("change", updateConfigDirtyStatus);
  });
  qsa("[data-task-index]").forEach((input) => {
    input.addEventListener("input", updateConfigDirtyStatus);
    input.addEventListener("change", updateConfigDirtyStatus);
  });
  const addTaskBtn = qs("addTaskBtn");
  if (addTaskBtn) {
    addTaskBtn.addEventListener("click", () => {
      uiState.configPayload.config.TaskArray = uiState.configPayload.config.TaskArray || [];
      uiState.activeTab.config = "cfg-tasks";
      uiState.configPayload.config.TaskArray.push(createDefaultTask(uiState.configPayload.config.TaskArray.length));
      renderConfigEditor();
      updateConfigDirtyStatus();
    });
  }
  qsa("[data-remove-task]").forEach((button) => {
    button.addEventListener("click", () => {
      uiState.activeTab.config = "cfg-tasks";
      uiState.configPayload.config.TaskArray.splice(Number(button.dataset.removeTask), 1);
      renderConfigEditor();
      updateConfigDirtyStatus();
    });
  });
}

function collectConfigFromEditor() {
  const config = clone(uiState.configPayload.config);
  const fieldMap = new Map(uiState.configPayload.schema.flatMap((section) => section.fields.filter((field) => field.type !== "task_array").map((field) => [field.path, field])));
  const taskField = uiState.configPayload.schema.flatMap((section) => section.fields).find((field) => field.type === "task_array");
  const taskItemMap = new Map((taskField?.item_schema || []).map((item) => [item.key, item]));
  qsa("[data-config-path]").forEach((input) => {
    const path = input.dataset.configPath;
    const field = fieldMap.get(path);
    if (!field || field.readonly) return;
    let value;
    if (field.type === "bool") value = input.checked;
    else value = parseFieldInputValue(field, input.value, input.tagName);
    setConfigValue(config, path, value);
  });

  const tasks = [];
  qsa("[data-task-index]").forEach((element) => {
    const index = Number(element.dataset.taskIndex);
    const key = element.dataset.taskKey;
    const field = taskItemMap.get(key) || { type: "string" };
    if (!tasks[index]) tasks[index] = {};
    setConfigValue(tasks[index], key, parseFieldInputValue(field, element.value, element.tagName));
  });
  config.TaskArray = tasks.filter(Boolean);
  config.TaskCount = config.TaskArray.length;
  return config;
}

function syncConfigDraftFromEditor() {
  if (!uiState.configPayload?.schema?.length) return;
  if (!qs("configEditor")) return;
  try {
    uiState.configPayload.config = collectConfigFromEditor();
  } catch (error) {
    console.warn(error);
  }
}

function updateConfigDirtyStatus() {
  if (!uiState.configPayload || !uiState.configPayload.schema?.length) return;
  syncConfigDraftFromEditor();
  var current = clone(uiState.configPayload.config);
  var diffInfo = getConfigDiffInfo(uiState.originalConfig || {}, current);
  if (uiState.currentView === "config-snapshot") {
    renderConfigSnapshot();
  }
  if (diffInfo.count > 0) {
    setConfigEditorStatus("已修改 " + diffInfo.count + " 项，尚未保存。");
  } else {
    setConfigEditorStatus(uiState.importedLocal ? "当前配置与导入时一致。" : "当前配置与 config.json 一致。");
  }
}

function updateImportedConfigState(config) {
  uiState.configPayload = {
    config: clone(config || {}),
    schema: uiState.configPayload?.schema || [],
    editable: Boolean(uiState.configPayload?.schema?.length),
  };
  if (uiState.analysis) {
    uiState.analysis.config = clone(uiState.configPayload.config);
  }
  if (uiState.sourceData) {
    uiState.sourceData.config = clone(uiState.configPayload.config);
  }
}

async function reloadConfigEditorState() {
  if (IS_STATIC_REPORT) {
    setConfigEditorStatus("静态报告模式无法重载配置。");
    return;
  }
  if (uiState.importedLocal) {
    uiState.configPayload.config = clone(uiState.originalConfig || {});
    uiState.configRecommendations = {};
    renderConfigEditor();
    if (uiState.currentView === "config-snapshot") renderConfigSnapshot();
    setConfigEditorStatus("已恢复到导入时的配置快照。");
    return;
  }
  if (!uiState.runtimeAvailable) {
    setConfigEditorStatus("当前没有运行目录配置可重载。");
    return;
  }
  uiState.configPayload = await fetchConfigPayload();
  uiState.originalConfig = clone(uiState.configPayload.config);
  renderConfigEditor();
}

async function saveConfigEditorState() {
  if (IS_STATIC_REPORT) {
    setConfigEditorStatus("静态报告模式无法保存配置。");
    return;
  }
  const config = collectConfigFromEditor();
  if (uiState.importedLocal) {
    updateImportedConfigState(config);
    downloadBlob("config.json", JSON.stringify(config, null, 2), "application/json;charset=utf-8");
    if (qs("configDiff")) qs("configDiff").innerHTML = "";
    if (uiState.currentView === "config-snapshot") renderConfigSnapshot();
    renderConfigEditor();
    showView("config-editor");
    setConfigEditorStatus("已导出当前修改后的 config.json，本地导入模式不会回写运行目录。");
    return;
  }
  if (!uiState.runtimeAvailable) {
    setConfigEditorStatus("当前没有运行目录配置可保存。");
    return;
  }
  setConfigEditorStatus("正在保存 config.json ...");
  const result = await saveConfigPayload(config);
  uiState.configPayload = await fetchConfigPayload();
  uiState.originalConfig = clone(uiState.configPayload.config);
  await loadRuntimeData(true);
  setConfigEditorStatus(result.message);
  showView("config-editor");
}

function getEventColor(event) {
  var palette = EVENT_COLORS[event.type] || EVENT_COLORS.valve;
  if (event.type === "valve") {
    return palette[event.channel] || palette.other;
  }
  if (event.type === "alarm") {
    return palette[event.severity] || palette.other;
  }
  if (event.type === "breath") {
    var title = (event.title || "").toLowerCase();
    if (title.includes("告警") || title.includes("alarm")) return palette.alert;
    return palette.normal;
  }
  return palette.other;
}

function classifyRunEvent(row) {
  const message = row.message || "";
  const lower = message.toLowerCase();
  const controlEvent = normalizeRunControlEvent(row);
  if (controlEvent) return controlEvent;
  const openMatch = message.match(/\b(CH1|CH2|CHT|DRAIN|12V|220V|ALARM_OUT)\b.*\b(open|close)\b/i);
  if (openMatch) {
    const channel = openMatch[1].toUpperCase();
    const action = openMatch[2].toLowerCase() === "open" ? "打开" : "关闭";
    return {
      ts: row.timestamp,
      type: "valve",
      severity: row.level === "E" ? "critical" : row.level === "W" ? "warning" : "info",
      title: `${channel} ${action}`,
      detail: message,
      channel,
      source: `${row.source_file}:${row.line_number}`,
      level: row.level,
      valveChannel: channel,
      valveAction: action,
    };
  }
  if (/\(humidity\)|\(exhaletimeout\)|manual heat|config synced|sd card config updated/i.test(lower)) {
    const title = /\(humidity\)/i.test(message)
      ? "湿度控制判定"
      : /\(exhaletimeout\)/i.test(message)
        ? "呼气超时判定"
        : /manual heat/i.test(message)
          ? "手自动模式切换"
          : "配置变更";
    return {
      ts: row.timestamp,
      type: "system",
      severity: row.level === "W" ? "warning" : row.level === "E" ? "critical" : "info",
      title,
      detail: message,
      channel: "",
      source: `${row.source_file}:${row.line_number}`,
      level: row.level,
    };
  }
  if (/alarm|online err|failed|error|fault/i.test(lower) || row.level === "E") {
    return {
      ts: row.timestamp,
      type: "alarm",
      severity: row.level === "E" ? "critical" : "warning",
      title: row.level === "E" ? "错误事件" : "告警事件",
      detail: message,
      channel: "",
      source: `${row.source_file}:${row.line_number}`,
      level: row.level,
    };
  }
  if (/watchdog|i2c|recover|iec61850|lora|flow/i.test(lower)) {
    return {
      ts: row.timestamp,
      type: "system",
      severity: row.level === "W" ? "warning" : "info",
      title: "系统事件",
      detail: message,
      channel: "",
      source: `${row.source_file}:${row.line_number}`,
      level: row.level,
    };
  }
  return null;
}

function findNearestEnvSnapshot(envRows, ts) {
  if (!envRows.length) return null;
  // 二分查找最近的时间点，envRows已按时间排序
  let left = 0;
  let right = envRows.length - 1;
  while (left < right) {
    const mid = (left + right) >> 1;
    if (envRows[mid].timestamp < ts) {
      left = mid + 1;
    } else {
      right = mid;
    }
  }
  let best = envRows[left];
  if (left > 0) {
    const prev = envRows[left - 1];
    if (Math.abs(prev.timestamp - ts) < Math.abs(best.timestamp - ts)) {
      best = prev;
    }
  }
  return {
    pressure: best.pressure,
    temperature: best.temperature,
    flow: best.flow,
    humidity: best.humidity,
  };
}

function buildMasterModel(sourceData) {
  const envRows = sourceData.envRows;
  const breathRows = sourceData.breathRows;
  const runRows = sourceData.runRows;
  const config = sourceData.config || {};
  const events = [];

  breathRows.forEach((row) => {
    if (row.rhythm === 2 || row.rhythm === 3 || row.state === 3 || row.state === 4 || row.rhythm === 1) {
      const title = row.rhythm === 2
        ? "呼吸段开始"
        : row.rhythm === 3
          ? "呼吸段结束"
          : row.state === 3
            ? "低流速告警"
            : row.state === 4
              ? "高流速告警"
              : `状态切换到 ${row.state_name}`;
      events.push({
        ts: row.timestamp,
        type: "breath",
        severity: row.state >= 3 ? "warning" : "info",
        title,
        detail: `状态 ${row.state_name}，流速 ${formatNumber(row.flow_rate)} L/min，已持续 ${formatNumber(row.elapsed_since_change)} 秒`,
        channel: "",
        source: `${row.source_file}:${row.line_number}`,
      });
    }
  });

  runRows.forEach((row) => {
    const event = classifyRunEvent(row);
    if (event) events.push(event);
  });

  events.sort((a, b) => a.ts - b.ts);
  events.forEach((event) => {
    event.snapshot = findNearestEnvSnapshot(envRows, event.ts);
  });

  const humidityHigh = Number(config?.HumidityValue?.HThreshold ?? 0);
  const accumPoints = [];
  const valveState = {
    CH1: false,
    CH2: false,
    CHT: false,
    DRAIN: false,
    "12V": false,
    "220V": false,
    ALARM_OUT: false,
  };
  const valveMinutes = {
    CH1: 0,
    CH2: 0,
    CHT: 0,
    DRAIN: 0,
  };

  let breathIndex = 0;
  let runIndex = 0;
  let inhaleCount = 0;
  let exhaleCount = 0;
  let breathIntegral = 0;
  let humidityIntegral = 0;
  let humidityHighMinutes = 0;
  let prevEnvTs = null;
  let prevBreathTs = null;
  let prevBreathFlow = 0;
  let prevBreathState = null;

  const valveKeys = Object.keys(valveMinutes);
  envRows.forEach((envRow) => {
    while (breathIndex < breathRows.length && breathRows[breathIndex].timestamp <= envRow.timestamp) {
      const b = breathRows[breathIndex];
      if (prevBreathTs) {
        const breathDtMin = (b.timestamp - prevBreathTs) / 60000;
        if (breathDtMin > 0) breathIntegral += Math.abs(prevBreathFlow) * breathDtMin;
      }
      if (prevBreathState !== b.state) {
        if (b.state === 1) inhaleCount += 1;
        if (b.state === 0) exhaleCount += 1;
      }
      prevBreathTs = b.timestamp;
      prevBreathFlow = b.flow_rate;
      prevBreathState = b.state;
      breathIndex += 1;
    }

    while (runIndex < events.length && events[runIndex].ts <= envRow.timestamp) {
      const event = events[runIndex];
      if (event.type === "valve" && event.valveChannel && valveState[event.valveChannel] !== undefined) {
        valveState[event.valveChannel] = event.valveAction === "打开";
      }
      runIndex += 1;
    }

    if (prevEnvTs) {
      const envDtMin = (envRow.timestamp - prevEnvTs) / 60000;
      if (envDtMin > 0) {
        humidityIntegral += envRow.humidity * envDtMin;
        if (humidityHigh && envRow.humidity > humidityHigh) humidityHighMinutes += envDtMin;
        for (let vk = 0; vk < valveKeys.length; vk += 1) {
          const key = valveKeys[vk];
          if (valveState[key]) valveMinutes[key] += envDtMin;
        }
      }
    }
    prevEnvTs = envRow.timestamp;

    accumPoints.push({
      ts: envRow.timestamp,
      inhale_count: inhaleCount,
      exhale_count: exhaleCount,
      breath_integral: Number(breathIntegral.toFixed(2)),
      humidity_integral: Number(humidityIntegral.toFixed(2)),
      humidity_high_minutes: Number(humidityHighMinutes.toFixed(2)),
      valve_minutes: Number((valveMinutes.CH1 + valveMinutes.CH2 + valveMinutes.CHT + valveMinutes.DRAIN).toFixed(2)),
      ch1_minutes: Number(valveMinutes.CH1.toFixed(2)),
      ch2_minutes: Number(valveMinutes.CH2.toFixed(2)),
      cht_minutes: Number(valveMinutes.CHT.toFixed(2)),
      drain_minutes: Number(valveMinutes.DRAIN.toFixed(2)),
    });
  });

  return {
    events,
    accumPoints,
    availableDates: sourceData.availableDates,
    start: envRows[0]?.timestamp || breathRows[0]?.timestamp || runRows[0]?.timestamp || null,
    end: envRows[envRows.length - 1]?.timestamp || breathRows[breathRows.length - 1]?.timestamp || runRows[runRows.length - 1]?.timestamp || null,
  };
}

function sampleEvents(events, maxPoints = 180) {
  if (events.length <= maxPoints) return events;
  const step = Math.ceil(events.length / maxPoints);
  return events.filter((_, index) => index % step === 0);
}

function getMasterFilteredData() {
  if (!uiState.sourceData || !uiState.masterModel) return null;
  const start = uiState.masterFilter.start;
  const end = uiState.masterFilter.end;
  const envRows = uiState.sourceData.envRows.filter((row) => (!start || row.timestamp >= start) && (!end || row.timestamp <= end));
  const breathRows = uiState.sourceData.breathRows.filter((row) => (!start || row.timestamp >= start) && (!end || row.timestamp <= end));
  const events = uiState.masterModel.events.filter((row) => (!start || row.ts >= start) && (!end || row.ts <= end) && uiState.selectedEventTypes.has(row.type));
  const accumPoints = uiState.masterModel.accumPoints.filter((row) => (!start || row.ts >= start) && (!end || row.ts <= end));
  return { envRows, breathRows, events, accumPoints };
}

function renderMasterFilterOptions() {
  const options = ["all", ...(uiState.sourceData?.availableDates || [])];
  qs("datePresetSelect").innerHTML = options.map((item) => `<option value="${escapeHtml(item)}">${item === "all" ? "全部日期" : escapeHtml(item)}</option>`).join("");
  qs("datePresetSelect").value = uiState.masterFilter.selectedDate;

  qs("metricToggleHost").innerHTML = Object.entries(METRICS).map(([key, item]) => `
    <button class="metric-chip ${uiState.selectedMetrics.has(key) ? "active" : ""}" data-toggle-metric="${key}">${escapeHtml(item.label)}</button>
  `).join("");
  qs("eventToggleHost").innerHTML = Object.entries(EVENT_TYPES).map(([key, item]) => `
    <button class="event-chip ${uiState.selectedEventTypes.has(key) ? "active" : ""}" data-toggle-event="${key}">${escapeHtml(item.label)}</button>
  `).join("");

  qsa("[data-toggle-metric]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.toggleMetric;
      if (uiState.selectedMetrics.has(key) && uiState.selectedMetrics.size > 1) uiState.selectedMetrics.delete(key);
      else uiState.selectedMetrics.add(key);
      renderMasterFilterOptions();
      renderMasterView();
    });
  });
  qsa("[data-toggle-event]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.toggleEvent;
      if (uiState.selectedEventTypes.has(key)) uiState.selectedEventTypes.delete(key);
      else uiState.selectedEventTypes.add(key);
      renderMasterFilterOptions();
      renderMasterView();
    });
  });
}

function buildOverallChart(filtered) {
  if (!filtered.envRows.length) return `<div class="empty-state">当前筛选范围内没有环境数据</div>`;
  const width = 1160;
  const height = 410;
  const padding = { top: 24, right: 24, bottom: 40, left: 60 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const selectedMetrics = [...uiState.selectedMetrics];
  const startTs = filtered.envRows[0].timestamp.getTime();
  const endTs = filtered.envRows[filtered.envRows.length - 1].timestamp.getTime();
  const spanTs = Math.max(1, endTs - startTs);
  const xAt = (ts) => padding.left + ((ts - startTs) / spanTs) * innerWidth;
  const scaleCache = {};
  selectedMetrics.forEach((key) => {
    const values = filtered.envRows.map((row) => row[key]);
    const range = minMax(values, 0);
    scaleCache[key] = {
      min: range.min,
      max: range.max,
      span: range.max === range.min ? 1 : range.max - range.min,
    };
  });
  const yAt = (metricKey, value) => {
    const scale = scaleCache[metricKey];
    return padding.top + innerHeight - ((value - scale.min) / scale.span) * innerHeight;
  };
  const grid = [0, 0.25, 0.5, 0.75, 1].map((step) => {
    const y = padding.top + step * innerHeight;
    return `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="rgba(31,42,48,0.10)" stroke-dasharray="4 6"></line>`;
  }).join("");
  const paths = selectedMetrics.map((metricKey) => {
    const path = downsample(filtered.envRows, 1200).map((row, index) => `${index === 0 ? "M" : "L"}${xAt(row.timestamp.getTime())},${yAt(metricKey, row[metricKey])}`).join(" ");
    return `<path d="${path}" fill="none" stroke="${METRICS[metricKey].color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"></path>`;
  }).join("");

  const anchorMetric = selectedMetrics[0];
  const sampledEvents = sampleEvents(filtered.events, 160);
  const circles = sampledEvents.map((event, index) => {
    const x = xAt(event.ts.getTime());
    const y = event.snapshot && anchorMetric && event.snapshot[anchorMetric] !== undefined
      ? yAt(anchorMetric, event.snapshot[anchorMetric])
      : padding.top + innerHeight / 2;
    return `<circle cx="${x}" cy="${y}" r="5.5" fill="${getEventColor(event)}" stroke="#fff" stroke-width="2" data-event-index="${index}"></circle>`;
  }).join("");

  const sampledRows = downsample(filtered.envRows, 1200);
  const seriesRows = sampledRows.map((row) => {
    const entry = { x: Math.round(xAt(row.timestamp.getTime())) };
    selectedMetrics.forEach((key) => {
      entry[key] = Math.round(yAt(key, row[key]));
      entry[`${key}_v`] = Number(row[key]);
    });
    entry.ts = row.timestamp.getTime();
    return entry;
  });
  const seriesMetrics = selectedMetrics.map((key) => ({
    key,
    label: METRICS[key].label,
    unit: METRICS[key].unit,
    color: METRICS[key].color,
  }));

  const axisLabels = [
    `<text x="${padding.left}" y="${height - 14}" font-size="11" fill="#6f7b7f">${escapeHtml(formatDateTime(filtered.envRows[0].timestamp).slice(5, 16))}</text>`,
    `<text x="${width - padding.right}" y="${height - 14}" text-anchor="end" font-size="11" fill="#6f7b7f">${escapeHtml(formatDateTime(filtered.envRows[filtered.envRows.length - 1].timestamp).slice(5, 16))}</text>`,
  ].join("");

  const legend = selectedMetrics.map((metricKey) => {
    const scale = scaleCache[metricKey];
    return `<div class="legend-chip"><span style="background:${METRICS[metricKey].color}"></span>${METRICS[metricKey].label} (${METRICS[metricKey].unit}) ${formatNumber(scale.min)} ~ ${formatNumber(scale.max)}</div>`;
  }).join("");

  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" data-series='${JSON.stringify(seriesRows)}' data-series-meta='${JSON.stringify(seriesMetrics)}'>
      ${grid}
      ${paths}
      ${circles}
      ${axisLabels}
    </svg>
    <div class="chart-legend">${legend}</div>
  `;
}

function buildAccumulationChart(filtered) {
  if (!filtered.accumPoints.length) return `<div class="empty-state">当前筛选范围内没有累计数据</div>`;
  const points = downsample(filtered.accumPoints, 1000);
  const series = [
    { key: "inhale_count", label: "吸气累计次数", color: "#2c6d76" },
    { key: "exhale_count", label: "呼气累计次数", color: "#b14d2d" },
    { key: "humidity_high_minutes", label: "湿度超阈值累计分钟", color: "#4f7c55" },
    { key: "valve_minutes", label: "阀门开启累计分钟", color: "#8a6b3d" },
  ];
  const width = 1000;
  const height = 320;
  const padding = { top: 24, right: 24, bottom: 36, left: 52 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const startTs = points[0].ts.getTime();
  const endTs = points[points.length - 1].ts.getTime();
  const spanTs = Math.max(1, endTs - startTs);
  let maxValue = 1;
  for (let i = 0; i < series.length; i += 1) {
    const key = series[i].key;
    for (let j = 0; j < points.length; j += 1) {
      const value = Number(points[j][key] || 0);
      if (value > maxValue) maxValue = value;
    }
  }
  const xAt = (ts) => padding.left + ((ts - startTs) / spanTs) * innerWidth;
  const yAt = (value) => padding.top + innerHeight - (value / maxValue) * innerHeight;
  const grid = [0, 0.25, 0.5, 0.75, 1].map((step) => {
    const y = padding.top + innerHeight - step * innerHeight;
    const value = step * maxValue;
    return `
      <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="rgba(31,42,48,0.10)" stroke-dasharray="4 6"></line>
      <text x="${padding.left - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#6f7b7f">${formatNumber(value, 0)}</text>
    `;
  }).join("");
  const paths = series.map((item) => {
    const path = points.map((row, index) => `${index === 0 ? "M" : "L"}${xAt(row.ts.getTime())},${yAt(row[item.key])}`).join(" ");
    return `<path d="${path}" fill="none" stroke="${item.color}" stroke-width="2.4" stroke-linecap="round"></path>`;
  }).join("");
  const seriesRows = points.map((row) => {
    const entry = { x: Math.round(xAt(row.ts.getTime())) };
    series.forEach((item) => {
      entry[item.key] = Math.round(yAt(row[item.key]));
      entry[`${item.key}_v`] = Number(row[item.key]);
    });
    entry.ts = row.ts.getTime();
    return entry;
  });
  const seriesMeta = series.map((item) => ({
    key: item.key,
    label: item.label,
    color: item.color,
  }));
  const legend = series.map((item) => `<div class="legend-chip"><span style="background:${item.color}"></span>${item.label}</div>`).join("");
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" data-series='${JSON.stringify(seriesRows)}' data-series-meta='${JSON.stringify(seriesMeta)}'>
      ${grid}
      ${paths}
    </svg>
    <div class="chart-legend">${legend}</div>
  `;
}

function renderMasterSummary(filtered) {
  const host = qs("masterSummary");
  const eventCounts = Object.keys(EVENT_TYPES).map((key) => ({
    key,
    count: filtered.events.filter((item) => item.type === key).length,
  }));
  const lastAcc = filtered.accumPoints[filtered.accumPoints.length - 1];
  host.innerHTML = [
    `<div class="summary-item">环境点数：${filtered.envRows.length.toLocaleString()}</div>`,
    `<div class="summary-item">呼吸点数：${filtered.breathRows.length.toLocaleString()}</div>`,
    `<div class="summary-item">事件点数：${filtered.events.length.toLocaleString()}</div>`,
    ...eventCounts.map((item) => `<div class="summary-item">${EVENT_TYPES[item.key].label}：${item.count}</div>`),
    lastAcc ? `<div class="summary-item">吸气累计 ${lastAcc.inhale_count} 次，呼气累计 ${lastAcc.exhale_count} 次</div>` : "",
    lastAcc ? `<div class="summary-item">湿度超阈值累计 ${formatNumber(lastAcc.humidity_high_minutes, 1)} 分钟</div>` : "",
    lastAcc ? `<div class="summary-item">阀门开启累计 ${formatNumber(lastAcc.valve_minutes, 1)} 分钟</div>` : "",
  ].filter(Boolean).join("");
}

function renderMasterEventList(filtered) {
  const host = qs("masterEventList");
  const items = filtered.events.slice().reverse().slice(0, 180);
  host.innerHTML = items.length
    ? items.map((item) => `
      <article class="timeline-item">
        <div class="timeline-time">${escapeHtml(formatDateTime(item.ts).slice(0, 16))}</div>
        <div><span class="badge badge-${item.severity === "critical" ? "E" : item.severity === "warning" ? "W" : "I"}">${escapeHtml(EVENT_TYPES[item.type]?.label || item.type)}</span></div>
        <div>
          <div><strong>${escapeHtml(item.title)}</strong></div>
          <div>${escapeHtml(item.detail)}</div>
          <div class="muted">${escapeHtml(item.source || "")}</div>
        </div>
      </article>
    `).join("")
    : `<div class="empty-state">当前筛选条件下没有事件</div>`;
}

function bindMasterChartTooltip(filtered) {
  const tooltip = qs("chartTooltip");
  const chartHost = qs("overallChartHost");
  const sampledEvents = sampleEvents(filtered.events, 160);
  qsa("#overallChartHost [data-event-index]").forEach((node) => {
    node.addEventListener("mousemove", (event) => {
      const item = sampledEvents[Number(node.dataset.eventIndex)];
      if (!item) return;
      // 隐藏十字光标弹窗，避免重叠
      var ct = document.querySelector(".chart-crosshair-tooltip");
      if (ct) ct.classList.add("hidden");
      const snapshot = item.snapshot || {};
      tooltip.innerHTML = `
        <div><strong>${escapeHtml(item.title)}</strong></div>
        <div>${escapeHtml(formatDateTime(item.ts))}</div>
        <div>${escapeHtml(item.detail)}</div>
        <div>来源：${escapeHtml(item.source || "-")}</div>
        <div>温度 ${formatNumber(snapshot.temperature)} °C | 湿度 ${formatNumber(snapshot.humidity)} %</div>
        <div>压力 ${formatNumber(snapshot.pressure)} kPa | 流速 ${formatNumber(snapshot.flow)} L/min</div>
      `;
      tooltip.classList.remove("hidden");
      var rect = chartHost.getBoundingClientRect();
      var left = event.clientX - rect.left;
      var top = event.clientY - rect.top - tooltip.offsetHeight - 8;
      if (top < 4) top = event.clientY - rect.top + 14;
      if (left + 280 > rect.width) left = rect.width - 280;
      if (top + 100 > rect.height) top = rect.height - 100;
      if (left < 2) left = 2;
      tooltip.style.left = left + "px";
      tooltip.style.top = top + "px";
    });
    node.addEventListener("mouseleave", () => {
      tooltip.classList.add("hidden");
    });
  });
}

function renderImportRecognition(summary) {
  const host = qs("importRecognition");
  if (!summary) {
    host.innerHTML = `<div class="empty-state">导入后将在这里列出识别到的文件类型和数量。</div>`;
    return;
  }
  host.innerHTML = `
    <div class="recognition-item">配置文件：${summary.config} 个</div>
    <div class="recognition-item">环境日志：${summary.environment} 个</div>
    <div class="recognition-item">呼吸日志：${summary.breath} 个</div>
    <div class="recognition-item">运行日志：${summary.run} 个</div>
    <div class="recognition-item">其他文件：${summary.other} 个</div>
  `;
}

function applyDataSet(sourceData, meta, options = {}) {
  uiState.sourceData = sourceData;
  uiState.analysis = buildAnalysisFromSource(sourceData, meta);
  uiState.masterModel = buildMasterModel(sourceData);
  uiState.runtimeAvailable = Boolean(options.runtimeAvailable);
  uiState.importedLocal = Boolean(options.importedLocal);
  const start = uiState.masterModel.start;
  const end = uiState.masterModel.end;
  uiState.masterFilter = {
    selectedDate: "all",
    start,
    end,
  };
  qs("rangeStartInput").value = toDateInputValue(start);
  qs("rangeEndInput").value = toDateInputValue(end);
  renderAll();
}

async function parseImportedFiles(fileList) {
  const files = Array.from(fileList || []);
  const summary = { config: 0, environment: 0, breath: 0, run: 0, other: 0 };
  const configFiles = [];
  const envRows = [];
  const breathRows = [];
  let runRows = [];

  for (const file of files) {
    const path = (file.webkitRelativePath || file.name).replace(/\\/g, "/");
    const text = await file.text();

    if (/config\.json$/i.test(file.name)) {
      summary.config += 1;
      try {
        configFiles.push(JSON.parse(text));
      } catch (error) {
        throw new Error(`config.json 解析失败: ${error.message}`);
      }
      continue;
    }

    if (/log_.*\.csv$/i.test(file.name) || /data_0\//i.test(path)) {
      let matched = 0;
      text.split(/\r?\n/).forEach((line, index) => {
        const match = ENV_ROW_RE.exec(line.trim());
        if (!match) return;
        matched += 1;
        envRows.push({
          timestamp: toDate(match.groups.ts),
          pressure: Number(match.groups.pressure),
          temperature: Number(match.groups.temperature),
          flow: Number(match.groups.flow),
          humidity: Number(match.groups.humidity),
          source_file: file.name,
          line_number: index + 1,
        });
      });
      if (matched > 0) {
        summary.environment += 1;
        continue;
      }
    }

    if (/breath_.*\.csv$/i.test(file.name) || /breath_data\//i.test(path)) {
      let matched = 0;
      text.split(/\r?\n/).forEach((line, index) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) return;
        const parts = trimmed.split(",").map((item) => item.trim());
        if (parts.length !== 5) return;
        const state = Number(parts[1]);
        const rhythm = Number(parts[4]);
        if (Number.isNaN(state) || Number.isNaN(rhythm)) return;
        matched += 1;
        breathRows.push({
          timestamp: toDate(parts[0]),
          state,
          state_name: STATE_LABELS[state] || `状态 ${state}`,
          flow_rate: Number(parts[2]),
          elapsed_since_change: Number(parts[3]),
          rhythm,
          rhythm_name: RHYTHM_LABELS[rhythm] || `节律 ${rhythm}`,
          source_file: file.name,
          line_number: index + 1,
        });
      });
      if (matched > 0) {
        summary.breath += 1;
        continue;
      }
    }

    if (/\.csv$/i.test(file.name) || /run\//i.test(path)) {
      let matched = 0;
      text.split(/\r?\n/).forEach((line, index) => {
        const match = RUN_ROW_RE.exec(line.replace(/\s+$/, ''));
        if (!match) return;
        matched += 1;
        runRows.push({
          timestamp: toDate(match.groups.ts),
          level: match.groups.level,
          message: match.groups.message,
          source_file: file.name,
          line_number: index + 1,
        });
      });
      if (matched > 0) {
        summary.run += 1;
        continue;
      }
    }

    summary.other += 1;
  }

  envRows.sort((a, b) => a.timestamp - b.timestamp);
  breathRows.sort((a, b) => a.timestamp - b.timestamp);
  runRows.sort((a, b) => a.timestamp - b.timestamp);
  // 运行日志数据量通常最大，截断保留最近条目以控制内存和渲染开销
  const MAX_RUN_ROWS = 2000;
  const runTruncated = runRows.length > MAX_RUN_ROWS;
  if (runTruncated) {
    runRows = runRows.slice(-MAX_RUN_ROWS);
  }
  const config = configFiles[0] || {};
  return {
    config,
    envRows,
    breathRows,
    runRows,
    availableDates: buildAvailableDates(envRows, breathRows, runRows),
    fileCount: files.length,
    summary,
    runTruncated,
    runTotal: runRows.length,
  };
}

async function loadRuntimeData(forceRefresh = false) {
  if (IS_STATIC_REPORT) {
    if (!EMBEDDED_ANALYSIS) throw new Error("静态报告中没有内嵌数据");
    const sourceData = normalizeAnalysisPayload(EMBEDDED_ANALYSIS);
    applyDataSet(sourceData, {
      generated_at: EMBEDDED_ANALYSIS.meta?.generated_at || formatDateTime(new Date()),
      data_root: EMBEDDED_ANALYSIS.meta?.data_root || "静态报告",
    }, { runtimeAvailable: false, importedLocal: false });
    uiState.configPayload = { config: sourceData.config, schema: [], editable: false };
    uiState.originalConfig = clone(sourceData.config);
    setStatus(`静态报告已加载，生成于 ${formatDateTime(EMBEDDED_ANALYSIS.meta?.generated_at)}`);
    setImportSummary("当前为静态报告模式，页面已直接加载内嵌分析结果。");
    renderImportRecognition({
      config: sourceData.config && Object.keys(sourceData.config).length ? 1 : 0,
      environment: sourceData.envRows.length ? 1 : 0,
      breath: sourceData.breathRows.length ? 1 : 0,
      run: sourceData.runRows.length ? 1 : 0,
      other: 0,
    });
    showView("master");
    return;
  }
  const analysis = await fetchAnalysis(forceRefresh);
  const sourceData = normalizeAnalysisPayload(analysis);
  applyDataSet(sourceData, {
    generated_at: analysis.meta?.generated_at,
    data_root: analysis.meta?.data_root || "运行目录",
  }, { runtimeAvailable: true, importedLocal: false });
  try {
    uiState.configPayload = await fetchConfigPayload();
    uiState.originalConfig = clone(uiState.configPayload.config);
  } catch {
    uiState.configPayload = { config: sourceData.config, schema: [], editable: false };
  }
  renderConfigEditor();
  setStatus(`已加载运行目录数据，生成于 ${formatDateTime(analysis.meta?.generated_at)}`);
  setImportSummary("已读取当前运行目录数据。若要切换到其他批次，请回到“导入数据”页重新导入。");
  renderImportRecognition({
    config: sourceData.config && Object.keys(sourceData.config).length ? 1 : 0,
    environment: uiState.analysis.environment.files,
    breath: uiState.analysis.breath.files,
    run: uiState.analysis.run_log.files,
    other: 0,
  });
  showView("master");
}

async function handleImportedFiles(fileList) {
  try {
    resetLoadedData("正在清空当前数据并导入新文件...");
    const imported = await parseImportedFiles(fileList);
    applyDataSet({
      config: imported.config,
      envRows: imported.envRows,
      breathRows: imported.breathRows,
      runRows: imported.runRows,
      availableDates: imported.availableDates,
    }, {
      generated_at: formatDateTime(new Date()),
      data_root: `导入文件，共 ${imported.fileCount} 个`,
    }, { runtimeAvailable: false, importedLocal: true });
    uiState.configPayload = { config: imported.config, schema: [], editable: false };
    uiState.originalConfig = clone(imported.config);
    try {
      const serverPayload = await fetchConfigPayload();
      if (serverPayload?.schema?.length) {
        uiState.configPayload.schema = serverPayload.schema;
        uiState.configPayload.editable = true;
      }
    } catch (schemaError) {
      console.warn(schemaError);
    }
    renderConfigEditor();
    renderImportRecognition(imported.summary);
    setImportSummary(`导入完成：识别到 ${imported.fileCount} 个文件，环境 ${uiState.analysis.environment.total_rows} 条，呼吸 ${uiState.analysis.breath.total_rows} 条，运行日志 ${uiState.analysis.run_log.total_rows} 条。`);
    setStatus("本地导入已完成，可切换到不同功能页查看。");
    showView("master");
  } catch (error) {
    console.error(error);
    setImportSummary(`导入失败：${error.message}`);
    setStatus(`导入失败：${error.message}`);
  }
}

function pushMasterFilterState() {
  const f = uiState.masterFilter;
  uiState.masterFilterHistory.push({
    selectedDate: f.selectedDate,
    start: f.start,
    end: f.end,
  });
}

function undoMasterFilter() {
  if (!uiState.masterModel) return;
  var prev = uiState.masterFilterHistory.pop();
  if (!prev) {
    uiState.masterFilter.selectedDate = "all";
    uiState.masterFilter.start = uiState.masterModel.start;
    uiState.masterFilter.end = uiState.masterModel.end;
    qs("datePresetSelect").value = "all";
    qs("rangeStartInput").value = toDateInputValue(uiState.masterModel.start);
    qs("rangeEndInput").value = toDateInputValue(uiState.masterModel.end);
    setStatus("已回到初始范围");
  } else {
    uiState.masterFilter.selectedDate = prev.selectedDate;
    uiState.masterFilter.start = prev.start;
    uiState.masterFilter.end = prev.end;
    qs("datePresetSelect").value = prev.selectedDate || "all";
    qs("rangeStartInput").value = toDateInputValue(prev.start);
    qs("rangeEndInput").value = toDateInputValue(prev.end);
    setStatus("已返回上一级区间 (" + (uiState.masterFilterHistory.length) + " 步可撤回)");
  }
  renderMasterView();
}

window.__undoMasterFilter__ = function () {
  if (!uiState.masterModel) { setStatus("暂无可撤回，请先加载数据。"); return; }
  undoMasterFilter();
};

window.__forceFullReset__ = function () {
  if (!uiState.masterModel) return;
  uiState.masterFilterHistory = [];
  uiState.masterFilter.selectedDate = "all";
  uiState.masterFilter.start = uiState.masterModel.start;
  uiState.masterFilter.end = uiState.masterModel.end;
  if (qs("datePresetSelect")) qs("datePresetSelect").value = "all";
  if (qs("rangeStartInput")) qs("rangeStartInput").value = toDateInputValue(uiState.masterModel.start);
  if (qs("rangeEndInput")) qs("rangeEndInput").value = toDateInputValue(uiState.masterModel.end);
  setStatus("已重置为全部数据范围");
  renderMasterView();
};

function applyQuickRange(mode) {
  if (!uiState.masterModel?.end) return;
  pushMasterFilterState();
  const end = uiState.masterModel.end;
  let start = uiState.masterModel.start;
  if (mode === "1d") start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  if (mode === "3d") start = new Date(end.getTime() - 3 * 24 * 60 * 60 * 1000);
  if (mode === "7d") start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
  if (mode === "all") start = uiState.masterModel.start;
  uiState.masterFilter.selectedDate = "all";
  uiState.masterFilter.start = start;
  uiState.masterFilter.end = end;
  qs("datePresetSelect").value = "all";
  qs("rangeStartInput").value = toDateInputValue(start);
  qs("rangeEndInput").value = toDateInputValue(end);
  renderMasterView();
}

function applyMasterFiltersFromInputs() {
  pushMasterFilterState();
  const selectedDate = qs("datePresetSelect").value;
  let start = qs("rangeStartInput").value ? new Date(qs("rangeStartInput").value) : uiState.masterModel.start;
  let end = qs("rangeEndInput").value ? new Date(qs("rangeEndInput").value) : uiState.masterModel.end;
  if (selectedDate !== "all") {
    start = new Date(`${selectedDate}T00:00:00`);
    end = new Date(`${selectedDate}T23:59:59`);
    qs("rangeStartInput").value = toDateInputValue(start);
    qs("rangeEndInput").value = toDateInputValue(end);
  }
  uiState.masterFilter.selectedDate = selectedDate;
  uiState.masterFilter.start = start;
  uiState.masterFilter.end = end;
  renderMasterView();
}

Object.assign(uiState, {
  overviewTab: "summary",
  pageTitles: {
    import: "导入数据",
    overview: "首页概览",
    master: "总体曲线",
    environment: "环境数据",
    breath: "呼吸事件",
    run: "运行日志",
    "config-snapshot": "配置快照",
    "config-editor": "参数编辑",
  },
  envFilter: {
    search: "",
    start: null,
    end: null,
  },
  breathFilter: {
    search: "",
    state: "all",
    rhythm: "all",
    start: null,
    end: null,
    page: 1,
    pageSize: 40,
  },
  breathFilterHistory: [],
  runQueryFilter: {
    search: "",
    level: "all",
    start: null,
    end: null,
    page: 1,
    pageSize: 40,
  },
});

function showView(view) {
  if (uiState.currentView === "config-editor" && view !== "config-editor") {
    syncConfigDraftFromEditor();
  }
  uiState.currentView = view;
  setSidebarOpen(false);
  qsa(".page").forEach((node) => node.classList.toggle("active", node.dataset.view === view));
  qsa(".nav-tab").forEach((node) => node.classList.toggle("active", node.dataset.viewTarget === view));
  if (view === "live") {
    renderLiveView();
    return;
  }
  if (!uiState.analysis) return;
  if (view === "master") renderMasterView();
  if (view === "environment") renderEnvironment();
  if (view === "breath") renderBreath();
  if (view === "run") renderRunLog();
  if (view === "simulation") renderSimulationView();
  if (view === "config-snapshot") renderConfigSnapshot();
  if (view === "config-editor") renderConfigEditor();
}

function setSidebarOpen(open) {
  document.body.classList.toggle("sidebar-open", Boolean(open));
  const sidebar = qs("appSidebar");
  const toggle = qs("sidebarToggle");
  if (sidebar) sidebar.setAttribute("aria-hidden", open ? "false" : "true");
  if (toggle) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.title = open ? "关闭导航" : "打开导航";
  }
}

// ── View-internal tab switching ──

function switchViewTab(viewId, tabName) {
  uiState.activeTab[viewId] = tabName;
  var tabs = document.querySelectorAll("#" + viewId + "Tabs .view-tab");
  var panels = document.querySelectorAll("#" + viewId + "Panels .view-tab-panel");
  if (!panels.length) panels = document.querySelectorAll("#" + viewId + "Editor .view-tab-panel");
  if (!panels.length) panels = document.querySelectorAll("#configEditor .view-tab-panel[data-tab]");
  tabs.forEach(function (t) { t.classList.toggle("active", t.dataset.viewTab === tabName); });
  panels.forEach(function (p) { p.classList.toggle("active", p.dataset.tab === tabName); });
  if (viewId === "live" && tabName === "live-curves") {
    window.requestAnimationFrame(() => {
      renderLiveCurveChart();
      window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    });
  }
}

function bindViewTabs() {
  document.querySelectorAll(".view-tabs").forEach(function (tabBar) {
    tabBar.querySelectorAll(".view-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var viewId = tabBar.id.replace("Tabs", "");
        switchViewTab(viewId, btn.dataset.viewTab);
      });
    });
  });
}

function translateRunMessage(message) {
  let text = String(message || "");
  const rules = [
    [/watchdog/gi, "看门狗"],
    [/ONLINE ERR/gi, "在线检测错误"],
    [/ONLINE\s*(open|close)/gi, function (_, action) { return action.toLowerCase() === "open" ? "在线检测打开" : "在线检测关闭"; }],
    [/HeatChannel1/gi, "通道一加热"],
    [/HeatChannel2/gi, "通道二加热"],
    [/ANTIFREEZE/gi, "防冻"],
    [/VALVE PULSE/gi, "阀门脉冲"],
    [/VALVE FAN/gi, "阀门风扇"],
    [/\bVALVE\b/gi, "阀门"],
    [/MANUAL HEAT:ON \/ AUTO:OFF/gi, "手动加热开启/自动关闭"],
    [/MANUAL HEAT:OFF \/ AUTO:ON/gi, "手动加热关闭/自动开启"],
    [/\(Humidity\)/gi, "湿度控制判定"],
    [/\(ExhaleTimeout\)/gi, "呼气超时判定"],
    [/SD card config updated/gi, "SD卡配置已更新"],
    [/Config synced to Flash/gi, "配置已同步到Flash"],
    [/ALARM_OUT/gi, "报警输出"],
    [/bus recovery/gi, "总线恢复"],
    [/I2C/gi, "I2C"],
    [/GetFlow/gi, "读取流速"],
    [/ForceCloseTask/gi, "强制关闭任务"],
    [/Failed/gi, "失败"],
    [/recover/gi, "恢复"],
    [/\bopen\b/gi, "打开"],
    [/\bclose\b/gi, "关闭"],
    [/\bCH1\b/g, "CH1"],
    [/\bCH2\b/g, "CH2"],
    [/\bCHT\b/g, "CHT"],
    [/\bDRAIN\b/g, "DRAIN"],
    [/\b12V\b/g, "12V"],
    [/\b220V\b/g, "220V"],
    [/temperature/gi, "温度"],
    [/humidity/gi, "湿度"],
    [/pressure/gi, "压力"],
    [/flow/gi, "流速"],
    [/warning/gi, "警告"],
    [/error/gi, "错误"],
  ];
  rules.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  const valveMatch = text.match(/(CH1|CH2|CHT|DRAIN|12V|220V|报警输出|通道一加热|通道二加热|防冻|阀门).*(打开|关闭|开启|关闭)/);
  if (valveMatch) {
    return `${valveMatch[1]} ${valveMatch[2]}事件`;
  }
  if (/湿度控制判定/.test(text)) return `湿度控制判定：${text}`;
  if (/呼气超时判定/.test(text)) return `呼气超时判定：${text}`;
  if (/配置已/.test(text) || /SD卡配置已更新/.test(text)) return `配置事件：${text}`;
  if (/在线检测错误/.test(text)) return `在线检测告警：${text}`;
  if (/看门狗/.test(text)) return `看门狗事件：${text}`;
  if (/I2C/.test(text)) return `I2C 通讯事件：${text}`;
  return text;
}

const SIMULATION_PARAM_FIELDS = [
  { key: "humidity_enabled", label: "湿度参与", type: "checkbox" },
  { key: "humidity_high_threshold", label: "湿度高阈值", unit: "%" },
  { key: "humidity_low_threshold", label: "湿度低阈值", unit: "%" },
  { key: "humidity_evidence_interval_sec", label: "湿度证据间隔", unit: "秒" },
  { key: "humidity_evidence_count", label: "湿度证据次数" },
  { key: "breath_enabled", label: "呼吸参与", type: "checkbox" },
  { key: "heat_on_threshold", label: "开热流量阈值", unit: "L/min" },
  { key: "heat_off_threshold", label: "关热流量阈值", unit: "L/min" },
  { key: "derange_lt", label: "有效出气阈值", unit: "L/min" },
  { key: "derange_ht", label: "有效吸气阈值", unit: "L/min" },
  { key: "breath_evidence_interval_sec", label: "呼吸证据间隔", unit: "秒" },
  { key: "breath_evidence_count", label: "呼吸证据次数" },
  { key: "exhale_timeout_min_sec", label: "出气预测下限", unit: "秒" },
  { key: "exhale_timeout_sec", label: "出气预测上限", unit: "秒" },
  { key: "temperature_low_threshold", label: "开热温度下限", unit: "°C" },
  { key: "no_record_gap_sec", label: "无记录段识别", unit: "秒" },
];

function cloneSimulationParams(params) {
  return clone(params || {});
}

function simulationBool(value, fallback = true) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const text = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(text)) return true;
    if (["0", "false", "no", "off"].includes(text)) return false;
  }
  return fallback;
}

function buildSimulationParamsFromConfig(config = {}) {
  const humidity = config.HumidityValue || {};
  const respiratory = config.RespiratoryRate || {};
  const respiratoryInfo = respiratory.infor || {};
  const temperature = config.Temperature || {};
  return {
    humidity_enabled: simulationBool(humidity.Priority ?? humidity.VSW, true),
    humidity_high_threshold: Number(humidity.HThreshold ?? 40),
    humidity_low_threshold: Number(humidity.LThreshold ?? 37),
    humidity_evidence_interval_sec: Number(humidity.HeatEvidenceIntervalSec ?? 600),
    humidity_evidence_count: Number(humidity.HeatEvidenceCount ?? 3),
    breath_enabled: simulationBool(respiratoryInfo.Priority ?? respiratory.VSW, true),
    heat_on_threshold: Number(respiratory.HeatOnThreshold ?? -4),
    heat_off_threshold: Number(respiratory.HeatOffThreshold ?? 1),
    derange_lt: Number(respiratory.DERangeLT ?? -3),
    derange_ht: Number(respiratory.DERangeHT ?? 3),
    breath_evidence_interval_sec: Number(respiratory.HeatEvidenceIntervalSec ?? 60),
    breath_evidence_count: Number(respiratory.HeatEvidenceCount ?? 3),
    exhale_timeout_min_sec: Number(respiratory.ExhaleTimeoutMinSec ?? 300),
    exhale_timeout_sec: Number(respiratory.ExhaleTimeoutSec ?? 1000),
    temperature_low_threshold: Number(temperature.LThreshold ?? -5),
    no_record_gap_sec: 60,
  };
}

function buildSimulationPresetsFromCurrentData(serverPresets = []) {
  const current = buildSimulationParamsFromConfig(uiState.sourceData?.config || uiState.analysis?.config || {});
  const recommended = {
    ...current,
    heat_on_threshold: -4,
    heat_off_threshold: 1,
    derange_lt: -3,
    derange_ht: 3,
    breath_evidence_interval_sec: 60,
    breath_evidence_count: 3,
    exhale_timeout_min_sec: 300,
    exhale_timeout_sec: 1000,
  };
  const count5 = { ...recommended, breath_evidence_count: 5 };
  if (!uiState.sourceData && serverPresets.length) return serverPresets;
  return [
    { id: "current", name: "当前配置", params: current },
    { id: "recommended", name: "推荐参数", params: recommended },
    { id: "count5", name: "累计5次验证", params: count5 },
  ];
}

function setSimulationStatus(text, tone = "") {
  const node = qs("simulationStatus");
  if (!node) return;
  node.textContent = text;
  node.className = `notice ${tone}`.trim();
}

function renderSimulationPresetList() {
  const host = qs("simulationPresetList");
  if (!host) return;
  const presets = uiState.simulation.presets || [];
  host.innerHTML = presets.length ? presets.map((preset) => `
    <button class="simulation-preset ${uiState.simulation.selectedPreset === preset.id ? "active" : ""}" data-simulation-preset="${escapeHtml(preset.id)}">
      <strong>${escapeHtml(preset.name)}</strong>
      <span>开 ${formatNumber(preset.params?.heat_on_threshold)} / 关 ${formatNumber(preset.params?.heat_off_threshold)}，呼吸证据 ${preset.params?.breath_evidence_count ?? "-"}</span>
    </button>
  `).join("") : `<div class="empty-state">暂无参数方案</div>`;
  host.querySelectorAll("[data-simulation-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const preset = presets.find((item) => item.id === btn.dataset.simulationPreset);
      if (!preset) return;
      uiState.simulation.selectedPreset = preset.id;
      uiState.simulation.params = cloneSimulationParams(preset.params);
      renderSimulationPresetList();
      renderSimulationParamEditor();
    });
  });
}

function renderSimulationParamEditor() {
  const host = qs("simulationParamEditor");
  if (!host) return;
  const params = uiState.simulation.params || {};
  host.innerHTML = SIMULATION_PARAM_FIELDS.map((field) => {
    const value = params[field.key];
    if (field.type === "checkbox") {
      return `
        <label class="simulation-param-row simulation-param-toggle">
          <span>${escapeHtml(field.label)}</span>
          <input data-simulation-param="${escapeHtml(field.key)}" type="checkbox" ${value ? "checked" : ""}>
        </label>
      `;
    }
    return `
      <label class="simulation-param-row">
        <span>${escapeHtml(field.label)}${field.unit ? `<small>${escapeHtml(field.unit)}</small>` : ""}</span>
        <input data-simulation-param="${escapeHtml(field.key)}" type="number" step="0.1" value="${escapeHtml(value ?? "")}">
      </label>
    `;
  }).join("");
  host.querySelectorAll("[data-simulation-param]").forEach((input) => {
    input.addEventListener("change", () => {
      const key = input.dataset.simulationParam;
      if (!key) return;
      if (input.type === "checkbox") {
        uiState.simulation.params[key] = input.checked;
      } else {
        const value = Number(input.value);
        uiState.simulation.params[key] = Number.isFinite(value) ? value : null;
      }
      uiState.simulation.selectedPreset = "custom";
      renderSimulationPresetList();
    });
  });
}

function renderSimulationSummary() {
  const host = qs("simulationSummary");
  if (!host) return;
  const result = uiState.simulation.result;
  if (!result) {
    host.innerHTML = `<div class="empty-state">运行模拟后显示统计结果</div>`;
    return;
  }
  const summary = result.summary || {};
  const reasonCounts = summary.off_reason_counts || {};
  host.innerHTML = [
    { label: "加热次数", value: `${summary.segments || 0} 次`, detail: `动作 ${summary.actions || 0} 个` },
    { label: "总加热时长", value: formatDuration(summary.heating_total_sec || 0), detail: `平均 ${formatDuration(summary.heating_avg_sec || 0)}` },
    { label: "最短/最长", value: `${formatDuration(summary.heating_min_sec || 0)} / ${formatDuration(summary.heating_max_sec || 0)}`, detail: "按模拟加热段统计" },
    { label: "关闭原因", value: Object.keys(reasonCounts).length ? Object.entries(reasonCounts).map(([key, value]) => `${key} ${value}`).join("，") : "-", detail: `无记录稳定段 ${summary.no_record_gap_count || 0} 个` },
  ].map((item) => `
    <div class="summary-item">
      <div class="metric-label">${escapeHtml(item.label)}</div>
      <strong>${escapeHtml(item.value)}</strong>
      <span>${escapeHtml(item.detail)}</span>
    </div>
  `).join("");
}

function simulationDayOf(ts) {
  return String(ts || "").slice(0, 10);
}

function simulationDayRange(day) {
  const start = new Date(`${day}T00:00:00`);
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  return { start, end };
}

function simulationOverlapsDay(startText, endText, day) {
  const range = simulationDayRange(day);
  const start = new Date(startText);
  const end = new Date(endText);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return false;
  return start < range.end && end > range.start;
}

function renderSimulationCharts() {
  const host = qs("simulationCharts");
  if (!host) return;
  const result = uiState.simulation.result;
  if (!result) {
    host.innerHTML = `<div class="empty-state">暂无模拟曲线</div>`;
    return;
  }
  const envRows = result.series?.environment || [];
  const breathRows = result.series?.breath || [];
  const days = Array.from(new Set([
    ...envRows.map((row) => simulationDayOf(row.ts)),
    ...breathRows.map((row) => simulationDayOf(row.ts)),
    ...((result.actions || []).map((item) => simulationDayOf(item.ts))),
  ].filter(Boolean))).sort();
  host.innerHTML = days.length ? days.map((day) => `
    <div class="chart-panel simulation-chart-panel">
      <div class="card-title">${escapeHtml(day)} 联合控制模拟</div>
      <div class="chart-legend simulation-legend">
        <div class="legend-chip"><span style="background:rgba(245,158,11,0.60)"></span>加热段</div>
        <div class="legend-chip"><span style="background:rgba(148,163,184,0.60)"></span>无记录-无呼吸</div>
        <div class="legend-chip"><span style="background:rgba(22,163,74,0.50)"></span>无记录-出气</div>
        <div class="legend-chip"><span style="background:rgba(37,99,235,0.50)"></span>无记录-吸气</div>
        <div class="legend-chip"><span style="background:#16a34a"></span>开热</div>
        <div class="legend-chip"><span style="background:#2563eb"></span>吸气关闭</div>
        <div class="legend-chip"><span style="background:#0891b2"></span>湿度低关闭</div>
        <div class="legend-chip"><span style="background:#dc2626"></span>预测超时关闭</div>
      </div>
      <div class="simulation-chart" id="simulationChart_${escapeHtml(day.replaceAll("-", ""))}"></div>
    </div>
  `).join("") : `<div class="empty-state">当前数据没有可绘制的日期</div>`;
  days.forEach((day) => renderSimulationDayChart(day, result));
}

function renderSimulationDayChart(day, result) {
  if (!window.echarts) return;
  const dom = qs(`simulationChart_${day.replaceAll("-", "")}`);
  if (!dom) return;
  const chart = echarts.init(dom);
  const params = result.params || {};
  const envRows = (result.series?.environment || []).filter((row) => simulationDayOf(row.ts) === day);
  const breathRows = (result.series?.breath || []).filter((row) => simulationDayOf(row.ts) === day);
  const actions = (result.actions || []).filter((row) => simulationDayOf(row.ts) === day);
  const segments = (result.segments || []).filter((item) => item.start && item.end && simulationOverlapsDay(item.start, item.end, day));
  const gaps = (result.no_record_gaps || []).filter((item) => item.start && item.end && simulationOverlapsDay(item.start, item.end, day));
  const actionColor = {
    heat_on: "#16a34a",
    heat_off: "#dc2626",
  };
  const actionShape = {
    heat_on: "triangle",
    heat_off: "diamond",
  };
  const markAreas = segments.map((segment) => [
    { xAxis: segment.start, itemStyle: { color: "rgba(245, 158, 11, 0.16)" } },
    { xAxis: segment.end },
  ]);
  const gapColor = (gap) => {
    if (gap.inferred_family === "exhale") return "rgba(22, 163, 74, 0.12)";
    if (gap.inferred_family === "inhale") return "rgba(37, 99, 235, 0.12)";
    return "rgba(148, 163, 184, 0.16)";
  };
  const gapAreas = gaps.map((gap) => [
    { xAxis: gap.start, itemStyle: { color: gapColor(gap) } },
    { xAxis: gap.end },
  ]);
  chart.setOption({
    color: ["#4f7c55", "#2c6d76", "#b07a24"],
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      confine: true,
    },
    toolbox: {
      right: 8,
      feature: {
        dataZoom: { yAxisIndex: "none" },
        restore: {},
        saveAsImage: {},
      },
    },
    legend: { top: 4, data: ["湿度", "温度", "呼吸流量", "动作点"] },
    grid: [
      { left: 56, right: 28, top: 42, height: 150 },
      { left: 56, right: 28, top: 238, height: 170 },
    ],
    xAxis: [
      { type: "time", gridIndex: 0, axisLabel: { show: false } },
      { type: "time", gridIndex: 1 },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, name: "湿度/温度" },
      { type: "value", gridIndex: 1, name: "流量" },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1] },
      { type: "slider", xAxisIndex: [0, 1], bottom: 4, height: 18 },
    ],
    series: [
      {
        name: "湿度",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        data: envRows.map((row) => [row.ts, row.humidity]),
        markLine: {
          symbol: "none",
          data: [
            { yAxis: params.humidity_high_threshold, lineStyle: { color: "#16a34a", type: "dashed" }, label: { formatter: "湿度高" } },
            { yAxis: params.humidity_low_threshold, lineStyle: { color: "#0ea5e9", type: "dashed" }, label: { formatter: "湿度低" } },
          ],
        },
      },
      {
        name: "温度",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        data: envRows.map((row) => [row.ts, row.temperature]),
        markLine: {
          symbol: "none",
          data: [
            { yAxis: params.temperature_low_threshold, lineStyle: { color: "#64748b", type: "dotted" }, label: { formatter: "温度下限" } },
          ],
        },
      },
      {
        name: "呼吸流量",
        type: "line",
        xAxisIndex: 1,
        yAxisIndex: 1,
        showSymbol: false,
        data: breathRows.map((row) => [row.ts, row.flow_rate]),
        markArea: { silent: true, data: [...markAreas, ...gapAreas] },
        markLine: {
          symbol: "none",
          data: [
            { yAxis: params.heat_on_threshold, lineStyle: { color: "#16a34a", type: "dashed" }, label: { formatter: "开热" } },
            { yAxis: params.heat_off_threshold, lineStyle: { color: "#2563eb", type: "dashed" }, label: { formatter: "关热" } },
          ],
        },
      },
      {
        name: "动作点",
        type: "scatter",
        xAxisIndex: 1,
        yAxisIndex: 1,
        symbolSize: 13,
        data: actions.map((action) => ({
          value: [action.ts, Number(action.flow_rate ?? 0)],
          symbol: actionShape[action.type] || "circle",
          itemStyle: { color: action.reason === "湿度低关闭" ? "#0891b2" : action.reason === "吸气确认关闭" ? "#2563eb" : action.type === "heat_on" ? "#16a34a" : "#dc2626" },
          name: action.reason,
          action,
        })),
        tooltip: {
          formatter: (params) => {
            const action = params.data?.action || {};
            return [
              `<strong>${escapeHtml(action.reason || "-")}</strong>`,
              escapeHtml(action.ts || ""),
              `湿度 ${formatNumber(action.humidity)}%，温度 ${formatNumber(action.temperature)}°C`,
              `流量 ${formatNumber(action.flow_rate)} L/min`,
              `湿度证据 高${action.humidity_high_count ?? 0}/低${action.humidity_low_count ?? 0}`,
              `呼吸证据 出${action.breath_exhale_count ?? 0}/吸${action.breath_inhale_count ?? 0}`,
              `预测间隔 ${formatDuration(action.predicted_interval_sec || 0)}，超时 ${formatDuration(action.timeout_sec || 0)}`,
            ].join("<br>");
          },
        },
      },
    ],
  });
  window.addEventListener("resize", () => chart.resize(), { passive: true });
}

async function renderSimulationView() {
  if (!qs("simulationParamEditor")) return;
  try {
    if (!uiState.simulation.defaults) {
      setSimulationStatus("正在加载默认参数...");
      let payload = { params: {}, presets: [] };
      try {
        payload = await fetchSimulationDefaults();
      } catch (error) {
        payload = { params: {}, presets: [] };
      }
      uiState.simulation.presets = buildSimulationPresetsFromCurrentData(payload.presets || []);
      uiState.simulation.defaults = uiState.simulation.presets[0]?.params || payload.params || {};
      const recommended = uiState.simulation.presets.find((item) => item.id === uiState.simulation.selectedPreset) || uiState.simulation.presets[0];
      uiState.simulation.params = cloneSimulationParams(recommended?.params || payload.params || {});
      renderSimulationPresetList();
      renderSimulationParamEditor();
    }
    renderSimulationSummary();
    renderSimulationCharts();
    setSimulationStatus("参数模拟使用湿度、温度和呼吸数据联合回放。");
  } catch (error) {
    setSimulationStatus(error.message || String(error), "error");
  }
}

async function runSimulationFromEditor() {
  if (uiState.simulation.running) return;
  uiState.simulation.running = true;
  setSimulationStatus("正在运行联合控制模拟...");
  try {
    const payload = await runSimulationScenario(uiState.simulation.params || {});
    uiState.simulation.result = payload.results?.[0] || null;
    renderSimulationSummary();
    renderSimulationCharts();
    setSimulationStatus("模拟完成。图中橙色为加热段，灰色为无记录稳定段。");
  } catch (error) {
    setSimulationStatus(error.message || String(error), "error");
  } finally {
    uiState.simulation.running = false;
  }
}

function buildOverlayTimelineChart(envRows, events, metricKeys, options = {}) {
  if (!envRows.length) {
    return { html: `<div class="empty-state">当前筛选范围内没有环境数据</div>`, sampledEvents: [] };
  }
  const width = 1160;
  const height = options.height || 380;
  const padding = { top: 24, right: 24, bottom: 40, left: 58 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const selectedMetrics = metricKeys.length ? metricKeys : ["temperature"];
  const startTs = envRows[0].timestamp.getTime();
  const endTs = envRows[envRows.length - 1].timestamp.getTime();
  const spanTs = Math.max(1, endTs - startTs);
  const xAt = (ts) => padding.left + ((ts - startTs) / spanTs) * innerWidth;
  const scaleCache = {};
  selectedMetrics.forEach((key) => {
    const values = envRows.map((row) => Number(row[key]));
    const range = minMax(values, 0);
    scaleCache[key] = { min: range.min, max: range.max, span: range.max === range.min ? 1 : range.max - range.min };
  });
  const yAt = (metricKey, value) => {
    const scale = scaleCache[metricKey];
    return padding.top + innerHeight - ((Number(value) - scale.min) / scale.span) * innerHeight;
  };
  const grid = [0, 0.25, 0.5, 0.75, 1].map((step) => {
    const y = padding.top + step * innerHeight;
    return `<line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="rgba(31,42,48,0.10)" stroke-dasharray="4 6"></line>`;
  }).join("");
  const paths = selectedMetrics.map((metricKey) => {
    const sampledRows = downsample(envRows, 1200);
    const path = sampledRows.map((row, index) => `${index === 0 ? "M" : "L"}${xAt(row.timestamp.getTime())},${yAt(metricKey, row[metricKey])}`).join(" ");
    return `<path d="${path}" fill="none" stroke="${METRICS[metricKey].color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></path>`;
  }).join("");
  const sampledEvents = sampleEvents(events, 180);
  const anchorMetric = selectedMetrics[0];
  const dots = sampledEvents.map((event, index) => {
    const x = xAt(event.ts.getTime());
    const y = event.snapshot && event.snapshot[anchorMetric] !== undefined
      ? yAt(anchorMetric, event.snapshot[anchorMetric])
      : padding.top + innerHeight / 2;
    return `<circle cx="${x}" cy="${y}" r="5.5" fill="${getEventColor(event)}" stroke="#fff" stroke-width="2" data-event-index="${index}"></circle>`;
  }).join("");
  const sampledRows = downsample(envRows, 1200);
  const seriesRows = sampledRows.map((row) => {
    const entry = { x: Math.round(xAt(row.timestamp.getTime())) };
    selectedMetrics.forEach((key) => {
      entry[key] = Math.round(yAt(key, row[key]));
      entry[`${key}_v`] = Number(row[key]);
    });
    entry.ts = row.timestamp.getTime();
    return entry;
  });
  const seriesMetrics = selectedMetrics.map((key) => ({
    key,
    label: METRICS[key].label,
    unit: METRICS[key].unit,
    color: METRICS[key].color,
  }));
  const legend = selectedMetrics.map((metricKey) => `<div class="legend-chip"><span style="background:${METRICS[metricKey].color}"></span>${METRICS[metricKey].label} (${METRICS[metricKey].unit})</div>`).join("");
  return {
    html: `
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" data-series='${JSON.stringify(seriesRows)}' data-series-meta='${JSON.stringify(seriesMetrics)}'>
        ${grid}
        ${paths}
        ${dots}
      </svg>
      <div class="chart-legend">${legend}</div>
    `,
    sampledEvents,
  };
}

function ensureEventTooltip(container, tooltipId) {
  let tooltip = qs(tooltipId);
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = tooltipId;
    tooltip.className = "chart-tooltip hidden";
  }
  if (container && tooltip.parentElement !== container) {
    container.appendChild(tooltip);
  }
  return tooltip;
}

function bindTimelineTooltip(containerSelector, tooltipId, sampledEvents) {
  const container = document.querySelector(containerSelector);
  const tooltip = ensureEventTooltip(container, tooltipId);
  if (!tooltip || !container) return;
  qsa(`${containerSelector} [data-event-index]`).forEach((node) => {
    node.addEventListener("mousemove", (event) => {
      const item = sampledEvents[Number(node.dataset.eventIndex)];
      if (!item) return;
      var ct = document.querySelector(".chart-crosshair-tooltip");
      if (ct) ct.classList.add("hidden");
      const snapshot = item.snapshot || {};
      tooltip.innerHTML = `
        <div><strong>${escapeHtml(item.title)}</strong></div>
        <div>${escapeHtml(formatDateTime(item.ts))}</div>
        <div>${escapeHtml(item.detail)}</div>
        <div>来源：${escapeHtml(item.source || "-")}</div>
        <div>温度 ${formatNumber(snapshot.temperature)} °C | 湿度 ${formatNumber(snapshot.humidity)} %</div>
        <div>压力 ${formatNumber(snapshot.pressure)} kPa | 流速 ${formatNumber(snapshot.flow)} L/min</div>
      `;
      tooltip.classList.remove("hidden");
      var rect = container.getBoundingClientRect();
      var left = event.clientX - rect.left;
      var top = event.clientY - rect.top - tooltip.offsetHeight - 8;
      if (top < 4) top = event.clientY - rect.top + 14;
      if (left + 280 > rect.width) left = rect.width - 280;
      if (top + 100 > rect.height) top = rect.height - 100;
      if (left < 2) left = 2;
      tooltip.style.left = left + "px";
      tooltip.style.top = top + "px";
    });
    node.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
  });
}

function renderOverviewSummaryBoard() {
  const host = qs("overviewSummaryBoard");
  if (!host || !uiState.analysis) return;
  const env = uiState.analysis.environment;
  const breath = uiState.analysis.breath;
  const run = uiState.analysis.run_log;
  host.innerHTML = [
    `<div class="summary-item">环境日志 ${env.total_rows.toLocaleString()} 条，平均完整率 ${formatNumber(env.quality?.avg_daily_completeness_pct ?? 0, 1)}%</div>`,
    `<div class="summary-item">呼吸事件 ${breath.total_rows.toLocaleString()} 条，呼吸片段 ${breath.session_summary?.segments ?? 0} 个</div>`,
    `<div class="summary-item">运行日志 ${run.total_rows.toLocaleString()} 条，其中错误 ${run.levels?.error ?? 0} 条、告警 ${run.levels?.warn ?? 0} 条</div>`,
    `<div class="summary-item">时间范围 ${escapeHtml(uiState.analysis.overview.start_at || "-")} -> ${escapeHtml(uiState.analysis.overview.end_at || "-")}</div>`,
  ].join("");
}

function renderOverviewMetrics() {
  if (!uiState.analysis) return;
  var env = uiState.analysis.environment;
  var latest = uiState.analysis.overview.latest_environment_sample;

  var metricCards = [
    { label: "温度", value: latest ? formatNumber(latest.temperature) + " °C" : "-", color: "#2c6d76", detail: latest ? "区间 " + formatNumber(env.metrics.temperature?.stats?.min) + " ~ " + formatNumber(env.metrics.temperature?.stats?.max) + " °C" : "" },
    { label: "湿度", value: latest ? formatNumber(latest.humidity) + " %" : "-", color: "#4f7c55", detail: latest ? "区间 " + formatNumber(env.metrics.humidity?.stats?.min) + " ~ " + formatNumber(env.metrics.humidity?.stats?.max) + " %" : "" },
    { label: "压力", value: latest ? formatNumber(latest.pressure) + " kPa" : "-", color: "#b14d2d", detail: latest ? "区间 " + formatNumber(env.metrics.pressure?.stats?.min) + " ~ " + formatNumber(env.metrics.pressure?.stats?.max) + " kPa" : "" },
    { label: "流速", value: latest ? formatNumber(latest.flow) + " L/min" : "-", color: "#b07a24", detail: latest ? "区间 " + formatNumber(env.metrics.flow?.stats?.min) + " ~ " + formatNumber(env.metrics.flow?.stats?.max) + " L/min" : "" },
    { label: "完整率", value: env.quality ? formatNumber(env.quality.avg_daily_completeness_pct, 1) + "%" : "-", color: "#2d6f77", detail: env.quality ? "断档 " + (env.quality.gap_count || 0) + " 个 | 重复 " + (env.quality.duplicates || 0) + " 条" : "" },
  ];

  var gridHost = qs("overviewMetricsGrid");
  if (gridHost) {
    gridHost.innerHTML = metricCards.map(function (item) {
      return '<article class="overview-card">' +
        '<div class="overview-label" style="display:flex;align-items:center;gap:6px"><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + item.color + '"></span>' + escapeHtml(item.label) + '</div>' +
        '<div class="overview-value">' + escapeHtml(item.value) + '</div>' +
        '<div class="overview-detail">' + escapeHtml(item.detail) + '</div>' +
        '</article>';
    }).join("");
  }

  var latestHost = qs("overviewLatestEnv");
  if (latestHost && latest) {
    latestHost.innerHTML =
      '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">' +
        '<div class="summary-item"><strong>温度</strong><br>' + formatNumber(latest.temperature) + ' °C</div>' +
        '<div class="summary-item"><strong>湿度</strong><br>' + formatNumber(latest.humidity) + ' %</div>' +
        '<div class="summary-item"><strong>压力</strong><br>' + formatNumber(latest.pressure) + ' kPa</div>' +
        '<div class="summary-item"><strong>流速</strong><br>' + formatNumber(latest.flow) + ' L/min</div>' +
      '</div>' +
      '<div class="muted" style="margin-top:6px">采样时间：' + escapeHtml(latest.ts) + '</div>';
  }
}

function renderInsights(analysis) {
  const host = qs("insightsList");
  if (!host) return;
  const items = analysis?.insights || [];
  host.innerHTML = items.length
    ? items.slice(0, 6).map((item) => `
      <article class="insight-card" data-level="${escapeHtml(item.level)}">
        <h3 class="insight-title">${escapeHtml(item.title)}</h3>
        <p class="insight-detail">${escapeHtml(item.detail)}</p>
      </article>
    `).join("")
    : `<div class="empty-state">暂无诊断结果</div>`;
}

function renderMetricTabs() {
  const host = qs("envMetricTabs");
  if (!host) return;
  host.innerHTML = Object.entries(METRICS).map(([key, meta]) => `
    <button class="filter-chip ${uiState.selectedMetrics.has(key) ? "active" : ""}" data-env-metric="${key}">${meta.label}</button>
  `).join("");
  qsa("[data-env-metric]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.envMetric;
      if (uiState.selectedMetrics.has(key) && uiState.selectedMetrics.size > 1) {
        uiState.selectedMetrics.delete(key);
      } else {
        uiState.selectedMetrics.add(key);
        uiState.envMetric = key;
      }
      renderMetricTabs();
      renderEnvironment();
    });
  });
}

function getFilteredEnvironmentView() {
  if (!uiState.sourceData || !uiState.masterModel) return null;
  const search = (uiState.envFilter.search || "").toLowerCase();
  const start = uiState.envFilter.start;
  const end = uiState.envFilter.end;
  const envRows = uiState.sourceData.envRows.filter((row) => (!start || row.timestamp >= start) && (!end || row.timestamp <= end));
  const events = uiState.masterModel.events.filter((item) => {
    if (start && item.ts < start) return false;
    if (end && item.ts > end) return false;
    if (search && !`${item.title} ${item.detail} ${item.source}`.toLowerCase().includes(search)) return false;
    return true;
  });
  return { envRows, events };
}

function renderEnvironment() {
  const filtered = getFilteredEnvironmentView();
  if (!filtered) return;
  const envAnalysis = analyzeEnvironment(filtered.envRows, uiState.sourceData.config);
  const firstKey = Object.keys(envAnalysis.metrics)[0];
  if (!firstKey || !envAnalysis.metrics[firstKey]) {
    ["envChart","envTempChart","envHumidityChart","envPressureChart","envFlowChart","completenessChart","thresholdChart","envDailyTable"].forEach(function(id) {
      if (qs(id)) qs(id).innerHTML = `<div class="empty-state">当前没有环境数据</div>`;
    });
    return;
  }

  // ── Tab: 叠加曲线 ──
  var overlayChart = buildOverlayTimelineChart(filtered.envRows, filtered.events, [...uiState.selectedMetrics], { height: 500 });
  qs("envChart").innerHTML = overlayChart.html;
  bindTimelineTooltip("#envChart", "chartTooltip", overlayChart.sampledEvents);

  // ── Tab: 单指标曲线 (温度/湿度/压力/流速) ──
  var metricKeys = ["temperature", "humidity", "pressure", "flow"];
  var chartIds = { temperature: "envTempChart", humidity: "envHumidityChart", pressure: "envPressureChart", flow: "envFlowChart" };
  metricKeys.forEach(function (key) {
    var meta = envAnalysis.metrics[key];
    var hostId = chartIds[key];
    if (!meta || !qs(hostId)) return;
    var points = envAnalysis.series.map(function (item) {
      return {
        label: item.ts.slice(5, 16),
        value: Number(item[key]),
        ts: new Date(item.ts).getTime(),
      };
    });
    qs(hostId).innerHTML = buildSvgLineChart(points, {
      color: METRICS[key].color,
      legend: METRICS[key].label + " (" + METRICS[key].unit + ")",
      thresholdHigh: meta.thresholds.high,
      thresholdLow: meta.thresholds.low,
      height: 500,
    });
  });

  // ── Tab: 统计 ──
  qs("completenessChart").innerHTML = buildSvgBarChart(envAnalysis.daily.map((item) => ({
    label: item.date.slice(5),
    value: Number(item.completeness_pct || 0),
    color: item.completeness_pct < 85 ? "#c87c1c" : "#2c6d76",
  })), { digits: 1 });
  qs("thresholdChart").innerHTML = buildSvgGroupedBarChart(Object.entries(envAnalysis.threshold_breaches).map(([key, value]) => ({
    date: METRICS[key].label,
    high: value.high,
    low: value.low,
  })), [
    { name: "high", label: "高阈值越界", color: "#b93030" },
    { name: "low", label: "低阈值越界", color: "#2c6d76" },
  ]);

  // ── Tab: 日报 ──
  var primaryMetric = uiState.envMetric || [...uiState.selectedMetrics][0] || "temperature";
  var primMeta = envAnalysis.metrics[primaryMetric];
  renderTable("envDailyTable", [
    { label: "日期", key: "date" },
    { label: "条数", render: (row) => row.count.toLocaleString() },
    { label: "完整率", render: (row) => `${formatNumber(row.completeness_pct, 1)}%` },
    { label: `${primMeta.label} 平均`, render: (row) => formatNumber(row[`${primaryMetric}_avg`]) },
    { label: `${primMeta.label} 最低`, render: (row) => formatNumber(row[`${primaryMetric}_min`]) },
    { label: `${primMeta.label} 最高`, render: (row) => formatNumber(row[`${primaryMetric}_max`]) },
  ], envAnalysis.daily);

  // Restore active tab
  if (uiState.activeTab.environment) switchViewTab("env", uiState.activeTab.environment);
}

function getFilteredBreathRows() {
  if (!uiState.sourceData) return [];
  const { state, rhythm, start, end } = uiState.breathFilter;
  return uiState.sourceData.breathRows.filter((row) => {
    if (start && row.timestamp < start) return false;
    if (end && row.timestamp > end) return false;
    if (state !== "all" && String(row.state) !== state) return false;
    if (rhythm !== "all" && String(row.rhythm) !== rhythm) return false;
    return true;
  });
}

function renderBreathFilters() {
  var rhythmFilter = qs("breathRhythmFilter");
  if (!rhythmFilter) return;
  rhythmFilter.innerHTML = [`<option value="all">全部节律</option>`, ...Object.entries(RHYTHM_LABELS).map(([key, label]) => `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`)].join("");
  rhythmFilter.value = uiState.breathFilter.rhythm;
}

function pushBreathFilterState() {
  const f = uiState.breathFilter;
  uiState.breathFilterHistory.push({
    state: f.state,
    rhythm: f.rhythm,
    start: f.start,
    end: f.end,
    page: f.page,
  });
}

function syncBreathFilterInputs() {
  const quickFilter = qs("breathQuickFilter");
  const rhythmFilter = qs("breathRhythmFilter");
  const startInput = qs("breathRangeStartInput");
  const endInput = qs("breathRangeEndInput");
  const quickMap = {
    "1": "inhale",
    "0": "exhale",
    "2": "no_breath",
    "3": "low_alarm",
    "4": "high_alarm",
  };
  if (quickFilter) quickFilter.value = quickMap[uiState.breathFilter.state] || "all";
  if (rhythmFilter) rhythmFilter.value = uiState.breathFilter.rhythm || "all";
  if (startInput) startInput.value = toDateInputValue(uiState.breathFilter.start);
  if (endInput) endInput.value = toDateInputValue(uiState.breathFilter.end);
}

function undoBreathFilter() {
  if (!uiState.masterModel) return;
  const prev = uiState.breathFilterHistory.pop();
  if (!prev) {
    uiState.breathFilter = {
      ...uiState.breathFilter,
      state: "all",
      rhythm: "all",
      start: uiState.masterModel.start,
      end: uiState.masterModel.end,
      page: 1,
    };
    syncBreathFilterInputs();
    setStatus("呼吸事件已回到初始范围");
  } else {
    uiState.breathFilter = {
      ...uiState.breathFilter,
      state: prev.state,
      rhythm: prev.rhythm,
      start: prev.start,
      end: prev.end,
      page: prev.page || 1,
    };
    syncBreathFilterInputs();
    setStatus(`呼吸事件已返回上一级区间 (${uiState.breathFilterHistory.length} 步可撤回)`);
  }
  renderBreath();
}

function mountBreathUndoToolbarButton() {
  const legacyUndoBtn = qs("undoBreathFilterBtn");
  if (legacyUndoBtn) legacyUndoBtn.style.display = "none";
  const host = qs("breathFlowChart");
  if (!host) return;
  const toolbar = host.querySelector(".chart-interaction-toolbar");
  const fullscreenBtn = toolbar?.querySelector(".ci-fullscreen");
  if (!toolbar || !fullscreenBtn) return;

  let undoBtn = toolbar.querySelector('[data-role="breath-undo-filter"]');
  if (!undoBtn) {
    undoBtn = document.createElement("button");
    undoBtn.type = "button";
    undoBtn.className = "ci-btn";
    undoBtn.dataset.role = "breath-undo-filter";
    undoBtn.title = "返回上一级筛选";
    undoBtn.innerHTML = "&#8630; 返回上一级";
    undoBtn.addEventListener("click", () => {
      if (!uiState.masterModel) {
        setStatus("暂无可撤回，请先加载数据。");
        return;
      }
      undoBreathFilter();
    });
  }
  undoBtn.disabled = !uiState.masterModel || uiState.breathFilterHistory.length === 0;
  fullscreenBtn.insertAdjacentElement("beforebegin", undoBtn);
}

window.__undoBreathFilter__ = function () {
  if (!uiState.masterModel) { setStatus("暂无可撤回，请先加载数据。"); return; }
  undoBreathFilter();
};

function renderBreath() {
  const filteredRows = getFilteredBreathRows();
  const breath = analyzeBreath(filteredRows, uiState.sourceData?.config || {});
  const respiratoryConfig = uiState.sourceData?.config?.RespiratoryRate || {};
  const stateCountMap = new Map(breath.state_counts.map((item) => [item.state, item.count]));
  const noBreathCount = stateCountMap.get(2) || 0;
  const inhaleCount = stateCountMap.get(1) || 0;
  const exhaleCount = stateCountMap.get(0) || 0;
  const lowAlarmCount = stateCountMap.get(3) || 0;
  const highAlarmCount = stateCountMap.get(4) || 0;
  const thresholdText = (value) => (Number.isFinite(Number(value)) ? `${formatNumber(Number(value))} L/min` : "未配置");

  qs("breathFocusMeta").innerHTML = [
    `<div class="breath-metric-card"><div class="breath-metric-label">flow window</div><strong>${filteredRows.length.toLocaleString()} 条采样</strong><span>仅在状态变化窗口内按秒记录</span></div>`,
    `<div class="breath-metric-card"><div class="breath-metric-label">segments</div><strong>${breath.session_summary?.segments ?? 0} 个片段</strong><span>最长 ${formatDuration(breath.session_summary?.longest_duration_sec ?? 0)}</span></div>`,
    `<div class="breath-metric-card"><div class="breath-metric-label">breathing</div><strong>吸气 ${inhaleCount} / 呼气 ${exhaleCount}</strong><span>蓝色=吸气，绿色=呼气</span></div>`,
    `<div class="breath-metric-card"><div class="breath-metric-label">silent & alarm</div><strong>无呼吸 ${noBreathCount}</strong><span>橙 ${lowAlarmCount} / 红 ${highAlarmCount}</span></div>`,
  ].join("");

  qs("breathLegendBoard").innerHTML = Object.entries(BREATH_STATE_META)
    .filter(([key]) => key !== "-1")
    .map(([key, meta]) => `
      <div class="breath-legend-item breath-legend-inline">
        <span class="breath-legend-swatch breath-legend-dot" style="background:${meta.color}"></span>
        <div>
          <div class="breath-legend-title">${escapeHtml(meta.label)}</div>
          <div class="breath-legend-detail">${escapeHtml(
            key === "0" ? `flow < DERangeLT (${thresholdText(respiratoryConfig.DERangeLT)})，且未低于 HeatOnThreshold (${thresholdText(respiratoryConfig.HeatOnThreshold)})`
              : key === "1" ? `flow > DERangeHT (${thresholdText(respiratoryConfig.DERangeHT)})，且未高于 HeatOffThreshold (${thresholdText(respiratoryConfig.HeatOffThreshold)})`
                : key === "2" ? `DERangeLT (${thresholdText(respiratoryConfig.DERangeLT)}) ~ DERangeHT (${thresholdText(respiratoryConfig.DERangeHT)})`
                  : key === "3" ? `flow < HeatOnThreshold (${thresholdText(respiratoryConfig.HeatOnThreshold)})`
                    : `flow > HeatOffThreshold (${thresholdText(respiratoryConfig.HeatOffThreshold)})`
          )}</div>
        </div>
      </div>
    `).join("");

  qs("breathFlowChart").innerHTML = buildBreathFocusChart(breath.series.map((item) => ({
    ...item,
    rhythm_name: RHYTHM_LABELS[item.rhythm] || item.rhythm_name || "",
  })), respiratoryConfig);
  mountBreathUndoToolbarButton();
  setTimeout(mountBreathUndoToolbarButton, 0);
  qs("breathStateChart").innerHTML = buildSvgBarChart(breath.state_counts.map((item) => ({
    label: item.state_name,
    value: item.count,
    color: (BREATH_STATE_META[item.state] || BREATH_STATE_META["-1"]).color,
  })));
  qs("breathRhythmChart").innerHTML = buildSvgBarChart(breath.rhythm_counts.map((item) => ({
    label: item.rhythm_name,
    value: item.count,
    color: item.rhythm === 2 ? "#16a34a" : item.rhythm === 3 ? "#7c3aed" : item.rhythm === 1 ? "#2563eb" : "#94a3b8",
  })));
  let segStartCount = 0;
  let segEndCount = 0;
  for (let i = 0; i < filteredRows.length; i += 1) {
    const row = filteredRows[i];
    if (row.rhythm === 2) segStartCount += 1;
    if (row.rhythm === 3) segEndCount += 1;
  }
  qs("breathSummaryBoard").innerHTML = [
    `<div class="summary-item">筛选后事件 ${filteredRows.length.toLocaleString()} 条</div>`,
    `<div class="summary-item">吸气 ${inhaleCount} 条，呼气 ${exhaleCount} 条，无呼吸 ${noBreathCount} 条</div>`,
    `<div class="summary-item">低流速告警 ${lowAlarmCount} 条，高流速告警 ${highAlarmCount} 条</div>`,
    `<div class="summary-item">片段开始 ${segStartCount} 条，片段结束 ${segEndCount} 条</div>`,
  ].join("");
  const pageSize = uiState.breathFilter.pageSize;
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  uiState.breathFilter.page = Math.min(uiState.breathFilter.page, totalPages);
  const pageStart = (uiState.breathFilter.page - 1) * pageSize;
  const pageRows = filteredRows.slice(pageStart, pageStart + pageSize);
  qs("breathEventList").innerHTML = pageRows.length
    ? pageRows.map((row) => `
      <article class="timeline-item">
        <div class="timeline-time">${escapeHtml(formatDateTime(row.timestamp).slice(0, 19))}</div>
        <div><span class="badge badge-${row.state >= 3 ? "W" : row.state === 2 ? "N" : "I"}">${escapeHtml(row.state_name)}</span></div>
        <div>
          <div>${escapeHtml(row.rhythm_name)}</div>
          <div>流速 ${formatNumber(row.flow_rate)} L/min，已持续 ${formatNumber(row.elapsed_since_change)} 秒</div>
          <div class="muted">${escapeHtml(`${row.source_file}:${row.line_number}`)}</div>
        </div>
      </article>
    `).join("")
    : `<div class="empty-state">当前筛选条件下没有呼吸事件</div>`;
  qs("breathPageInfo").textContent = `第 ${uiState.breathFilter.page} / ${totalPages} 页`;

  if (uiState.activeTab.breath) switchViewTab("breath", uiState.activeTab.breath);
}

function getFilteredRunRows() {
  if (!uiState.sourceData) return [];
  const { search, level, start, end } = uiState.runQueryFilter;
  var kwMap = {
    watchdog: ["watchdog", "看门狗"],
    alarm: ["ALARM", "报警"],
    valve: ["CH1", "CH2", "CHT", "DRAIN", "HTC1", "HTC2", "HeatChannel", "Valve", "Antifreeze", "ONLINEopen", "ONLINEclose", "open", "close", "打开", "关闭", "阀门", "防冻", "加热"],
    i2c: ["I2C"],
    flow: ["GetFlow", "流速"],
    online: ["ONLINE", "在线检测"],
    bus: ["bus recovery", "总线恢复"],
    error: ["Failed", "失败", "error", "错误"],
  };
  var keywords = kwMap[search] || null;
  return uiState.sourceData.runRows.filter((row) => {
    if (start && row.timestamp < start) return false;
    if (end && row.timestamp > end) return false;
    if (level !== "all" && row.level !== level) return false;
    if (keywords) {
      var haystack = (row.message + " " + translateRunMessage(row.message)).toLowerCase();
      var match = keywords.some(function (kw) { return haystack.includes(kw.toLowerCase()); });
      if (!match) return false;
    }
    return true;
  });
}

function renderRunTimeline() {
  const runLog = uiState.analysis?.run_log;
  if (!runLog) return;
  const items = runLog.important_events.filter((item) => uiState.runFilter === "all" || item.level === uiState.runFilter);
  qs("runTimeline").innerHTML = items.length
    ? items.slice().reverse().slice(0, 80).map((item) => `
      <article class="timeline-item">
        <div class="timeline-time">${escapeHtml(item.ts.slice(0, 16))}</div>
        <div><span class="badge badge-${escapeHtml(item.level)}">${escapeHtml(item.level)}</span></div>
        <div>${escapeHtml(translateRunMessage(item.message))}</div>
      </article>
    `).join("")
    : `<div class="empty-state">当前筛选条件下没有事件</div>`;
}

function renderRunLogTable(rows) {
  renderTable("runLogTable", [
    { label: "时间", render: (row) => `<span class="mono">${escapeHtml(formatDateTime(row.timestamp))}</span>` },
    { label: "级别", render: (row) => `<span class="badge badge-${escapeHtml(row.level)}">${escapeHtml(row.level)}</span>` },
    { label: "原始日志", render: (row) => escapeHtml(row.message) },
    { label: "中文解释", render: (row) => escapeHtml(translateRunMessage(row.message)) },
    { label: "来源", render: (row) => escapeHtml(`${row.source_file}:${row.line_number}`) },
  ], rows);
}

function renderRunLog() {
  const filteredRows = getFilteredRunRows();
  const runLog = analyzeRun(filteredRows);
  qs("runDailyChart").innerHTML = buildSvgGroupedBarChart(runLog.daily, [
    { name: "info", label: "信息", color: "#2c6d76" },
    { name: "warn", label: "告警", color: "#c87c1c" },
    { name: "error", label: "错误", color: "#b93030" },
  ]);
  qs("runKeywordChart").innerHTML = buildSvgBarChart(runLog.keyword_counts.slice(0, 8).map((item) => ({
    label: item.keyword,
    value: item.count,
    color: "#b14d2d",
  })));
  const filters = [
    { key: "all", label: "全部" },
    { key: "E", label: "错误" },
    { key: "W", label: "告警" },
    { key: "I", label: "信息" },
  ];
  qs("runFilters").innerHTML = filters.map((item) => `
    <button class="filter-chip ${uiState.runFilter === item.key ? "active" : ""}" data-run-filter="${item.key}">${item.label}</button>
  `).join("");
  qsa("[data-run-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      uiState.runFilter = button.dataset.runFilter;
      renderRunLog();
    });
  });
  renderRunTimeline();
  const pageSize = uiState.runQueryFilter.pageSize;
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  uiState.runQueryFilter.page = Math.min(uiState.runQueryFilter.page, totalPages);
  const startIndex = (uiState.runQueryFilter.page - 1) * pageSize;
  const pageRows = filteredRows.slice(startIndex, startIndex + pageSize);
  renderRunLogTable(pageRows);
  qs("runPageInfo").textContent = `第 ${uiState.runQueryFilter.page} / ${totalPages} 页`;

  if (uiState.activeTab.run) switchViewTab("run", uiState.activeTab.run);
}

function renderMasterView() {
  if (!uiState.sourceData || !uiState.masterModel) {
    qs("overallChartHost").innerHTML = `<div class="empty-state">请先导入数据</div>`;
    qs("accumulationChartHost").innerHTML = "";
    qs("masterSummary").innerHTML = "";
    qs("masterEventList").innerHTML = "";
    return;
  }
  renderMasterFilterOptions();
  const filtered = getMasterFilteredData();

  // Tab: 叠加曲线
  var overlayChart = buildOverlayTimelineChart(filtered.envRows, filtered.events, [...uiState.selectedMetrics], { height: 500 });
  qs("overallChartHost").innerHTML = overlayChart.html;
  bindTimelineTooltip("#overallChartHost", "chartTooltip", overlayChart.sampledEvents);
  renderMasterSummary(filtered);

  // Tab: 累计量
  qs("accumulationChartHost").innerHTML = buildAccumulationChart(filtered);

  // Tab: 事件清单
  renderMasterEventList(filtered);

  // Restore active tab
  if (uiState.activeTab.master) switchViewTab("master", uiState.activeTab.master);
}

function applyDataSet(sourceData, meta, options = {}) {
  uiState.sourceData = sourceData;
  uiState.analysis = buildAnalysisFromSource(sourceData, meta);
  uiState.masterModel = buildMasterModel(sourceData);
  uiState.runtimeAvailable = Boolean(options.runtimeAvailable);
  uiState.importedLocal = Boolean(options.importedLocal);
  uiState.masterFilterHistory = [];
  uiState.breathFilterHistory = [];
  uiState.simulation.defaults = null;
  uiState.simulation.presets = [];
  uiState.simulation.params = null;
  uiState.simulation.result = null;
  uiState.simulation.selectedPreset = "recommended";
  const start = uiState.masterModel.start;
  const end = uiState.masterModel.end;
  uiState.masterFilter = { selectedDate: "all", start, end };
  uiState.envFilter = { search: "", start, end };
  uiState.breathFilter = { ...uiState.breathFilter, search: "", state: "all", rhythm: "all", start, end, page: 1 };
  uiState.runQueryFilter = { ...uiState.runQueryFilter, search: "", level: "all", start, end, page: 1 };
  ["rangeStartInput", "envRangeStartInput", "breathRangeStartInput", "runRangeStartInput"].forEach((id) => { if (qs(id)) qs(id).value = toDateInputValue(start); });
  ["rangeEndInput", "envRangeEndInput", "breathRangeEndInput", "runRangeEndInput"].forEach((id) => { if (qs(id)) qs(id).value = toDateInputValue(end); });
  renderAll();
}

function renderAll() {
  if (!uiState.analysis) return;
  qs("overviewCards").innerHTML = makeOverviewCards(uiState.analysis);
  renderOverviewSummaryBoard();
  renderOverviewMetrics();
  renderInsights(uiState.analysis);
  renderBreathFilters();
  renderMetricTabs();
  // 按需渲染：只渲染当前可见或可能需要预加载的视图
  const view = uiState.currentView;
  if (view === "environment" || view === "master") renderEnvironment();
  if (view === "breath" || view === "master") renderBreath();
  if (view === "run" || view === "master") renderRunLog();
  if (view === "simulation") renderSimulationView();
  if (view === "config-snapshot") renderConfigSnapshot();
  if (view === "config-editor") renderConfigEditor();
  if (view === "master") renderMasterView();
}

function bindStaticEvents() {
  const sidebarToggle = qs("sidebarToggle");
  const sidebarBackdrop = qs("sidebarBackdrop");
  if (sidebarToggle) {
    sidebarToggle.addEventListener("click", () => {
      const nextOpen = !document.body.classList.contains("sidebar-open");
      setSidebarOpen(nextOpen);
    });
  }
  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false));
  }
  qsa(".nav-tab").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.viewTarget));
  });
  const simulationRunBtn = qs("simulationRunBtn");
  if (simulationRunBtn) {
    simulationRunBtn.addEventListener("click", () => runSimulationFromEditor());
  }
  const simulationResetBtn = qs("simulationResetBtn");
  if (simulationResetBtn) {
    simulationResetBtn.addEventListener("click", () => {
      const preset = (uiState.simulation.presets || []).find((item) => item.id === "recommended")
        || (uiState.simulation.presets || [])[0];
      uiState.simulation.selectedPreset = preset?.id || "recommended";
      uiState.simulation.params = cloneSimulationParams(preset?.params || uiState.simulation.defaults || {});
      renderSimulationPresetList();
      renderSimulationParamEditor();
      setSimulationStatus("已恢复参数方案。");
    });
  }
  qsa("[data-overview-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      uiState.overviewTab = button.dataset.overviewTab;
      qsa("[data-overview-tab]").forEach((node) => node.classList.toggle("active", node.dataset.overviewTab === uiState.overviewTab));
      qsa("[data-overview-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.overviewPanel === uiState.overviewTab));
    });
  });

  qs("liveNewDeviceBtn").addEventListener("click", () => {
    uiState.live.selectedDeviceId = null;
    uiState.live.selectedDeviceDraft = buildLiveNewDeviceDraft();
    resetLiveProjection(null);
    uiState.activeTab.live = "device-settings";
    renderLiveView();
    setLiveStatusNotice("已按当前设备配置创建新设备草稿。");
  });

  qs("liveSaveDeviceBtn").addEventListener("click", async () => {
    try {
      const draft = collectLiveDeviceDraft();
      if (!String(draft.name || "").trim()) {
        setLiveStatusNotice("设备名称不能为空。");
        return;
      }
      if (draft.id) {
        await updateLiveDevice(draft.id, draft);
        setLiveStatusNotice(`设备已保存：${draft.name}`);
      } else {
        await createLiveDevice(draft);
        setLiveStatusNotice(`设备已新增：${draft.name}`);
      }
      await refreshLiveModule();
    } catch (error) {
      setLiveStatusNotice(`保存设备失败：${error.message}`);
    }
  });

  qs("liveDeleteDeviceBtn").addEventListener("click", async () => {
    const device = getSelectedLiveDevice();
    if (!device) {
      setLiveStatusNotice("当前没有可删除的设备。");
      return;
    }
    try {
      await deleteLiveDevice(device.id);
      await refreshLiveModule();
      setLiveStatusNotice(`设备已删除：${device.name}`);
    } catch (error) {
      setLiveStatusNotice(`删除设备失败：${error.message}`);
    }
  });

  const exitBtn = qs("appExitBtn");
  if (exitBtn) {
    exitBtn.addEventListener("click", async () => {
      if (!confirm("确定要退出程序吗？\n\n将停止所有采集服务、落盘数据，然后关闭程序。")) return;
      try {
        setLiveStatusNotice("正在停止服务并退出...");
        await stopLiveSession();
      } catch (e) { /* ignore, may not be running */ }
      try {
        await shutdownSystem();
      } catch (e) {
        alert("退出失败：" + e.message);
      }
    });
  }

  qs("liveStartBtn").addEventListener("click", async () => {
    try {
      if (uiState.live.selectedDeviceDraft) {
        const draft = collectLiveDeviceDraft();
        if (!String(draft.name || "").trim()) {
          setLiveStatusNotice("设备名称不能为空。");
          return;
        }
        if (draft.id) await updateLiveDevice(draft.id, draft);
        else await createLiveDevice(draft);
        await refreshLiveModule();
      }
      const response = await startLiveSession();
      uiState.live.sessionStatus = response;
      await refreshLiveRuntimeData();
      uiState.activeTab.live = "live-overview";
      renderLiveView();
      setLiveStatusNotice(response.message || `已启动 ${response.state?.device_count || 0} 台设备采集`);
    } catch (error) {
      setLiveStatusNotice(`启动采集失败：${error.message}`);
    }
  });

  qs("liveStopBtn").addEventListener("click", async () => {
    try {
      const response = await stopLiveSession();
      uiState.live.sessionStatus = response;
      await refreshLiveRuntimeData();
      renderLiveView();
      setLiveStatusNotice(response.message || "已停止全部采集");
    } catch (error) {
      setLiveStatusNotice(`停止采集失败：${error.message}`);
    }
  });

  qs("importFolderBtn").addEventListener("click", () => qs("folderInput").click());
  qs("importFilesBtn").addEventListener("click", () => qs("filesInput").click());
  qs("folderInput").addEventListener("change", (event) => handleImportedFiles(event.target.files));
  qs("filesInput").addEventListener("change", (event) => handleImportedFiles(event.target.files));
  qs("clearCurrentDataBtn").addEventListener("click", () => {
    resetLoadedData("当前数据已清空。你可以重新导入文件夹、单个文件，或读取运行目录。");
    showView("import");
  });

  qs("loadRuntimeBtn").addEventListener("click", async () => {
    if (IS_STATIC_REPORT) {
      setImportSummary("当前是静态报告模式，不能读取运行目录。请直接查看页面结果，或手动导入新的文件夹/文件。");
      return;
    }
    try {
      setImportSummary("正在读取当前运行目录...");
      await loadRuntimeData(true);
    } catch (error) {
      setImportSummary(`读取运行目录失败：${error.message}`);
    }
  });

  qs("refreshBtn").addEventListener("click", async () => {
    if (uiState.importedLocal) {
      setStatus("当前结果来自手动导入。若要刷新，请重新导入文件夹或文件。");
      showView("import");
      return;
    }
    try {
      await loadRuntimeData(true);
    } catch (error) {
      setStatus(`刷新失败：${error.message}`);
    }
  });

  qs("exportJsonBtn").addEventListener("click", () => {
    if (!uiState.analysis) { setStatus("暂无可导出数据，请先导入或读取运行目录。"); return; }
    downloadBlob("yldq_analysis.json", JSON.stringify(uiState.analysis, null, 2), "application/json;charset=utf-8");
  });

  qs("exportSummaryBtn").addEventListener("click", () => {
    if (!uiState.analysis) { setStatus("暂无可导出数据，请先导入或读取运行目录。"); return; }
    downloadBlob("yldq_summary.txt", uiState.analysis.summary_text || buildSummaryText(uiState.analysis), "text/plain;charset=utf-8");
  });

  qs("exportConfigDraftBtn").addEventListener("click", () => {
    if (!uiState.configPayload?.config) { setConfigSnapshotStatus("暂无可导出配置，请先加载数据后再试。"); return; }
    syncConfigDraftFromEditor();
    downloadBlob("config.json", JSON.stringify(uiState.configPayload.config, null, 2), "application/json;charset=utf-8");
    var diffCount = getConfigDiffInfo(uiState.originalConfig || {}, uiState.configPayload.config || {}).count;
    setConfigSnapshotStatus(diffCount > 0 ? "已导出 config.json，共 " + diffCount + " 项变更。" : "已导出 config.json，当前与原始配置一致。");
  });

  qs("printBtn").addEventListener("click", () => window.print());
  qsa("[data-quick-range]").forEach((button) => button.addEventListener("click", () => applyQuickRange(button.dataset.quickRange)));
  qs("applyMasterFilterBtn").addEventListener("click", applyMasterFiltersFromInputs);
  qs("datePresetSelect").addEventListener("change", () => {
    if (qs("datePresetSelect").value !== "all") applyMasterFiltersFromInputs();
  });

  qs("applyEnvFilterBtn").addEventListener("click", () => {
    uiState.envFilter.start = qs("envRangeStartInput").value ? new Date(qs("envRangeStartInput").value) : null;
    uiState.envFilter.end = qs("envRangeEndInput").value ? new Date(qs("envRangeEndInput").value) : null;
    renderEnvironment();
  });
  qs("resetEnvFilterBtn").addEventListener("click", () => {
    uiState.envFilter.start = uiState.masterModel?.start || null;
    uiState.envFilter.end = uiState.masterModel?.end || null;
    qs("envRangeStartInput").value = toDateInputValue(uiState.envFilter.start);
    qs("envRangeEndInput").value = toDateInputValue(uiState.envFilter.end);
    renderEnvironment();
  });

  qs("applyBreathFilterBtn").addEventListener("click", () => {
    pushBreathFilterState();
    var quickVal = qs("breathQuickFilter").value;
    var stateMap = { inhale: "1", exhale: "0", no_breath: "2", low_alarm: "3", high_alarm: "4" };
    uiState.breathFilter.state = stateMap[quickVal] || "all";
    uiState.breathFilter.rhythm = qs("breathRhythmFilter").value;
    uiState.breathFilter.start = qs("breathRangeStartInput").value ? new Date(qs("breathRangeStartInput").value) : null;
    uiState.breathFilter.end = qs("breathRangeEndInput").value ? new Date(qs("breathRangeEndInput").value) : null;
    uiState.breathFilter.page = 1;
    renderBreath();
  });
  const undoBreathFilterBtn = qs("undoBreathFilterBtn");
  if (undoBreathFilterBtn) {
    undoBreathFilterBtn.addEventListener("click", () => {
      undoBreathFilter();
    });
  }
  qs("resetBreathFilterBtn").addEventListener("click", () => {
    uiState.breathFilterHistory = [];
    uiState.breathFilter = { ...uiState.breathFilter, state: "all", rhythm: "all", start: uiState.masterModel?.start || null, end: uiState.masterModel?.end || null, page: 1 };
    qs("breathQuickFilter").value = "all";
    qs("breathRhythmFilter").value = "all";
    qs("breathRangeStartInput").value = toDateInputValue(uiState.breathFilter.start);
    qs("breathRangeEndInput").value = toDateInputValue(uiState.breathFilter.end);
    renderBreath();
  });
  qs("breathPrevPageBtn").addEventListener("click", () => {
    uiState.breathFilter.page = Math.max(1, uiState.breathFilter.page - 1);
    renderBreath();
  });
  qs("breathNextPageBtn").addEventListener("click", () => {
    uiState.breathFilter.page += 1;
    renderBreath();
  });

  qs("applyRunFilterBtn").addEventListener("click", () => {
    uiState.runQueryFilter.search = qs("runQuickFilter").value;
    uiState.runQueryFilter.level = qs("runLevelFilter").value;
    uiState.runQueryFilter.start = qs("runRangeStartInput").value ? new Date(qs("runRangeStartInput").value) : null;
    uiState.runQueryFilter.end = qs("runRangeEndInput").value ? new Date(qs("runRangeEndInput").value) : null;
    uiState.runQueryFilter.page = 1;
    renderRunLog();
  });
  qs("resetRunFilterBtn").addEventListener("click", () => {
    uiState.runQueryFilter = { ...uiState.runQueryFilter, search: "all", level: "all", start: uiState.masterModel?.start || null, end: uiState.masterModel?.end || null, page: 1 };
    qs("runQuickFilter").value = "all";
    qs("runLevelFilter").value = "all";
    qs("runRangeStartInput").value = toDateInputValue(uiState.runQueryFilter.start);
    qs("runRangeEndInput").value = toDateInputValue(uiState.runQueryFilter.end);
    renderRunLog();
  });
  qs("runPrevPageBtn").addEventListener("click", () => {
    uiState.runQueryFilter.page = Math.max(1, uiState.runQueryFilter.page - 1);
    renderRunLog();
  });
  qs("runNextPageBtn").addEventListener("click", () => {
    uiState.runQueryFilter.page += 1;
    renderRunLog();
  });

  qs("genRecBtn").addEventListener("click", generateConfigRecommendations);

  qs("reloadConfigBtn").addEventListener("click", async () => {
    try {
      await reloadConfigEditorState();
    } catch (error) {
      setConfigEditorStatus(`重载失败：${error.message}`);
    }
  });

  qs("saveConfigBtn").addEventListener("click", async () => {
    try {
      await saveConfigEditorState();
    } catch (error) {
      setConfigEditorStatus(`保存失败：${error.message}`);
    }
  });

  // ── Chart brush-select: filter data by time range ──
  document.addEventListener("chart:apply-filter", function (e) {
    var detail = e.detail;
    if (!detail || !detail.startTs || !detail.endTs) return;
    var startDate = new Date(detail.startTs);
    var endDate = new Date(detail.endTs);
    var startStr = toDateInputValue(startDate);
    var endStr = toDateInputValue(endDate);

    switch (uiState.currentView) {
      case "master":
        pushMasterFilterState();
        uiState.masterFilter.selectedDate = "custom";
        uiState.masterFilter.start = startDate;
        uiState.masterFilter.end = endDate;
        if (qs("datePresetSelect")) qs("datePresetSelect").value = "custom";
        if (qs("rangeStartInput")) qs("rangeStartInput").value = startStr;
        if (qs("rangeEndInput")) qs("rangeEndInput").value = endStr;
        renderMasterView();
        break;
      case "environment":
        uiState.envFilter.start = startDate;
        uiState.envFilter.end = endDate;
        if (qs("envRangeStartInput")) qs("envRangeStartInput").value = startStr;
        if (qs("envRangeEndInput")) qs("envRangeEndInput").value = endStr;
        renderEnvironment();
        break;
      case "breath":
        pushBreathFilterState();
        uiState.breathFilter.start = startDate;
        uiState.breathFilter.end = endDate;
        uiState.breathFilter.page = 1;
        if (qs("breathRangeStartInput")) qs("breathRangeStartInput").value = startStr;
        if (qs("breathRangeEndInput")) qs("breathRangeEndInput").value = endStr;
        renderBreath();
        break;
    }
  });
}

function downloadBlob(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function init() {
  bindStaticEvents();
  bindViewTabs();
  renderImportRecognition(null);
  try {
    await refreshLiveModule();
  } catch (error) {
    setLiveStatusNotice(`实时模块初始化失败：${error.message}`);
  }
  showView("import");
  if (IS_STATIC_REPORT) {
    await loadRuntimeData(false);
    return;
  }
  try {
    await loadRuntimeData(false);
  } catch (error) {
    console.warn(error);
    setStatus("未能自动读取运行目录，请在“导入数据”页手动导入。");
    setImportSummary("自动读取运行目录失败。你可以导入整个数据文件夹，也可以只导入某几个文件。");
    uiState.configPayload = { config: {}, schema: [], editable: false };
    renderConfigEditor();
  }
}

window.__PARAMETER_EDITOR_API__ = {
  get uiState() {
    return uiState;
  },
  qs,
  qsa,
  clone,
  escapeHtml,
  setConfigEditorStatus,
  fetchConfigPayload,
  saveConfigPayload,
  collectConfigFromEditor,
  loadRuntimeData,
  showView,
  get isStaticReport() {
    return IS_STATIC_REPORT;
  },
};

(function loadWorkbenchModules() {
  // parameter_settings.js 已整合入 app.js 的 config editor 推荐功能
})();

window.addEventListener("DOMContentLoaded", init);
