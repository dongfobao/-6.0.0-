"use strict";
(() => {
  // ============================ 数据格式（与 live_session_recorder 落盘格式一致） ============================
  // 下位机 SensorLogger: [time],/* 压力,温度1,流量,湿度1,温度2,湿度2,温度3,湿度3 */
  // 旧版上位机会话仅保存前四列，并可在尾部追加 JSON 扩展字段。
  const ENV_ROW_RE = /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*,?\/\*\s*(.*?)\s*\*\/(?:\s*\|\s*(\{.*\}))?\s*$/;
  const RUN_ROW_RE = /^([AIDEWV])\/([^\s\[]+)\s+\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(?:\([^)]*\)\s*)?(.*)$/;

  const METRICS = [
    { key: "pressure", name: "压力", unit: "kPa", color: "#a78bfa" },
    { key: "flow", name: "流量", unit: "L/min", color: "#2dd4bf" },
    { key: "sensor_1.temperature", name: "温度 1", unit: "°C", color: "#fb923c" },
    { key: "sensor_2.temperature", name: "温度 2", unit: "°C", color: "#facc15" },
    { key: "sensor_3.temperature", name: "温度 3", unit: "°C", color: "#f87171" },
    { key: "sensor_1.humidity", name: "湿度 1", unit: "%RH", color: "#38bdf8" },
    { key: "sensor_2.humidity", name: "湿度 2", unit: "%RH", color: "#818cf8" },
    { key: "sensor_3.humidity", name: "湿度 3", unit: "%RH", color: "#a78bfa" },
  ];

  const EVENT_TYPES = {
    valve: { name: "阀门", color: "#38bdf8" },
    heat: { name: "加热", color: "#fb923c" },
    humidity: { name: "湿度会话", color: "#818cf8" },
    breath: { name: "呼吸", color: "#2dd4bf" },
    sensor: { name: "传感器", color: "#60a5fa" },
    alarm: { name: "告警/错误", color: "#f87171" },
    communication: { name: "通信异常", color: "#facc15" },
    config: { name: "配置", color: "#a78bfa" },
    storage: { name: "存储/日志", color: "#34d399" },
    safety: { name: "安全/看门狗", color: "#fb7185" },
    system: { name: "系统", color: "#a78bfa" },
  };

  const LOG_LEVELS = {
    A: { name: "断言", color: "#dc2626" }, E: { name: "错误", color: "#f87171" },
    W: { name: "警告", color: "#facc15" }, I: { name: "信息", color: "#38bdf8" },
    D: { name: "调试", color: "#94a3b8" }, V: { name: "详细", color: "#64748b" },
    U: { name: "未分级", color: "#94a3b8" },
  };

  const VALVE_NAMES = { 1: "上阀", 2: "左阀", 3: "右阀" };
  const VALVE_ACTIONS = { 0: "释放", 1: "回原位", 2: "到工作位", 3: "回原点校准" };
  const HEAT_NAMES = { htc1_mode: "加热通道1", htc2_mode: "加热通道2", antifreeze_mode: "防冻加热" };
  const HEAT_MODES = { 0: "自动", 1: "强制关闭", 2: "强制开启" };
  const BREATH_STATES = { 0: "呼气开始", 1: "吸气开始", 2: "呼吸停止", 3: "低流速告警", 4: "高流速告警" };

  const $ = (id) => document.getElementById(id);
  const source = { envRows: [], breathRows: [], runRows: [], firmwareRows: [], heatRows: [], trafficRows: [], config: null, meta: null, checkpoint: null };
  const ui = {
    imported: false,
    activeMetrics: new Set(METRICS.map((metric) => metric.key)),
    events: [],
    typeFilter: new Set(Object.keys(EVENT_TYPES)),
    levelFilter: new Set(Object.keys(LOG_LEVELS)),
    showEvents: true,
    logOpen: false,
    view: { start: 0, end: 0 },
    viewHistory: [],
    bounds: { start: 0, end: 0 },
    yScale: 1,
    showLabels: false,
    showKeyPoints: true,
    hoverX: null,
    selectedEvent: null,
    drag: null,
  };

  const parseTs = (text) => new Date(text.replace(" ", "T")).getTime();
  const pad2 = (n) => String(n).padStart(2, "0");
  const fmtTime = (ts) => {
    const d = new Date(ts);
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  };
  const fmtShort = (ts) => {
    const d = new Date(ts);
    return `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  };
  const toDateTimeLocal = (ts) => {
    const d = new Date(ts);
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ============================ 文件导入与解析 ============================
  function classifyFile(file) {
    const path = (file.webkitRelativePath || file.name).replace(/\\/g, "/");
    const name = file.name;
    if (/session_meta\.json$/i.test(name)) return "meta";
    if (/checkpoint\.json$/i.test(name)) return "checkpoint";
    if (/^config(?:_v\d+)?\.json$/i.test(name)) return "config";
    if (/^heat_.*\.csv$/i.test(name) || /(^|\/)heat_events\//i.test(path)) return "heat";
    if (/^traffic_.*\.csv$/i.test(name) || /(^|\/)traffic\//i.test(path)) return "traffic";
    // 下位机导出的 run/log_N.csv 是 EasyLogger 原始运行日志；不能按文件名误判为环境 CSV。
    if (/(^|\/)run\//i.test(path) && /^log_\d+\.csv$/i.test(name)) return "firmware";
    if (/(^|\/)run\//i.test(path)) return "run";
    if (/^log_\d+\.csv$/i.test(name)) return "firmware";
    if (/^log_.*\.csv$/i.test(name) || /(^|\/)data_\d+\//i.test(path)) return "env";
    if (/^breath_.*\.csv$/i.test(name) || /(^|\/)breath_data\//i.test(path)) return "breath";
    if (/^serial_output\.log(?:\.\d+)?$/i.test(name) || /(^|\/)logs?\//i.test(path) || /\.log(?:\.\d+)?$/i.test(name)) return "firmware";
    if (/\.csv$/i.test(name)) return "run";
    return "other";
  }

  function parseEnvText(text) {
    const rows = [];
    for (const line of text.split(/\r?\n/)) {
      const m = ENV_ROW_RE.exec(line.trim());
      if (!m) continue;
      const ts = parseTs(m[1]);
      if (!Number.isFinite(ts)) continue;
      const values = m[2].split(",").map((value) => Number(value.trim()));
      if (values.length < 4 || values.slice(0, 4).some((value) => !Number.isFinite(value))) continue;
      const row = {
        ts,
        pressure: values[0],
        "sensor_1.temperature": values[1],
        flow: values[2],
        "sensor_1.humidity": values[3],
      };
      // 固件 v6 当前完整格式有 10 项：第 5、6 项是第一路的兼容副本，
      // 第二、三路分别位于第 7、8 项和第 9、10 项；8 项旧格式则连续存放三路。
      const optionalIndex = values.length >= 10
        ? [["sensor_2.temperature", 6], ["sensor_2.humidity", 7], ["sensor_3.temperature", 8], ["sensor_3.humidity", 9]]
        : [["sensor_2.temperature", 4], ["sensor_2.humidity", 5], ["sensor_3.temperature", 6], ["sensor_3.humidity", 7]];
      optionalIndex.forEach(([field, index]) => {
        if (Number.isFinite(values[index])) row[field] = values[index];
      });
      if (m[3]) {
        try { Object.assign(row, JSON.parse(m[3])); } catch (_) { /* 损坏的扩展字段不影响基础曲线 */ }
      }
      rows.push(row);
    }
    return rows;
  }

  function parseBreathText(text) {
    const rows = [];
    for (const line of text.split(/\r?\n/)) {
      const parts = line.trim().split(",");
      if (parts.length < 5) continue;
      const ts = parseTs(parts[0]);
      if (!Number.isFinite(ts)) continue;
      rows.push({ ts, state: +parts[1], flow: +parts[2], elapsed: +parts[3], rhythm: +parts[4] });
    }
    return rows;
  }

  function parseRunText(text) {
    const rows = [];
    for (const line of text.split(/\r?\n/)) {
      const m = RUN_ROW_RE.exec(line.trim().replace(/\x1b\[[0-9;]*m/g, ""));
      if (!m) continue;
      rows.push({ ts: parseTs(m[3]), level: m[1], tag: m[2], message: m[4] });
    }
    return rows;
  }

  function parseFirmwareText(text) {
    const rows = [];
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim().replace(/\x1b\[[0-9;]*m/g, "");
      if (!line || line.startsWith("#") || /^={5,}$/.test(line)) continue;
      const parsed = parseRunText(line);
      if (parsed.length) { rows.push(...parsed); continue; }
      rows.push({ ts: NaN, level: "U", tag: "SERIAL", message: line });
    }
    return rows;
  }

  function parseHeatText(text) {
    const rows = [];
    for (const line of text.split(/\r?\n/)) {
      const parts = line.trim().split(",", 4);
      if (parts.length < 3) continue;
      const ts = parseTs(parts[0]);
      if (!Number.isFinite(ts)) continue;
      rows.push({ ts, channel: parts[1], event: parts[2], detail: parts[3] || "" });
    }
    return rows;
  }

  function parseTrafficText(text) {
    const rows = [];
    for (const line of text.split(/\r?\n/)) {
      try {
        const entry = JSON.parse(line);
        const ts = parseTs(entry.replyAt || entry.sentAt || "");
        if (Number.isFinite(ts)) rows.push({ ...entry, ts });
      } catch (_) { /* 跳过损坏的诊断记录 */ }
    }
    return rows;
  }

  async function handleImportedFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    resetData();
    const counts = { env: 0, breath: 0, run: 0, firmware: 0, heat: 0, traffic: 0, config: 0, meta: 0, checkpoint: 0, other: 0 };
    for (const file of files) {
      const kind = classifyFile(file);
      counts[kind] += 1;
      try {
        const text = await file.text();
        if (kind === "env") source.envRows.push(...parseEnvText(text));
        else if (kind === "breath") source.breathRows.push(...parseBreathText(text));
        else if (kind === "run") source.runRows.push(...parseRunText(text));
        else if (kind === "firmware") source.firmwareRows.push(...parseFirmwareText(text));
        else if (kind === "heat") source.heatRows.push(...parseHeatText(text));
        else if (kind === "traffic") source.trafficRows.push(...parseTrafficText(text));
        else if (kind === "config") source.config = JSON.parse(text);
        else if (kind === "meta") source.meta = JSON.parse(text);
        else if (kind === "checkpoint") source.checkpoint = JSON.parse(text);
      } catch (err) {
        console.warn("解析文件失败", file.name, err);
      }
    }
    source.envRows.sort((a, b) => a.ts - b.ts);
    source.breathRows.sort((a, b) => a.ts - b.ts);
    source.runRows.sort((a, b) => a.ts - b.ts);
    source.firmwareRows.sort((a, b) => (Number.isFinite(a.ts) ? a.ts : Infinity) - (Number.isFinite(b.ts) ? b.ts : Infinity));
    source.heatRows.sort((a, b) => a.ts - b.ts);
    source.trafficRows.sort((a, b) => a.ts - b.ts);
    ui.events = buildEvents();
    const bounds = computeBounds();
    ui.imported = Number.isFinite(bounds.start);
    if (ui.imported) {
      ui.bounds = bounds;
      ui.view = { start: bounds.start, end: bounds.end };
      ui.viewHistory = [];
      ui.yScale = 1;
      ui.selectedEvent = null;
    }
    renderImportSummary(counts);
    renderDatePresets();
    renderDateInputs();
    renderToggles();
    renderEventFilters();
    renderLogPanel();
    if (ui.events.length) {
      ui.logOpen = true;
      $("analysisLogPanel").classList.remove("hidden");
      $("analysisLogBtn").classList.add("active");
    }
    renderStats();
    draw();
  }

  function resetData() {
    source.envRows = [];
    source.breathRows = [];
    source.runRows = [];
    source.firmwareRows = [];
    source.heatRows = [];
    source.trafficRows = [];
    source.config = null;
    source.meta = null;
    source.checkpoint = null;
    ui.events = [];
    ui.imported = false;
    ui.logOpen = false;
    ui.selectedEvent = null;
    ui.hoverX = null;
    ui.viewHistory = [];
    ui.yScale = 1;
  }

  function computeBounds() {
    let start = Infinity, end = -Infinity;
    const feed = (rows) => {
      if (!rows.length) return;
      start = Math.min(start, rows[0].ts);
      end = Math.max(end, rows[rows.length - 1].ts);
    };
    feed(source.envRows); feed(source.breathRows); feed(source.runRows); feed(source.firmwareRows.filter((row) => Number.isFinite(row.ts))); feed(source.heatRows); feed(source.trafficRows);
    [source.meta?.started_at, source.meta?.ended_at, source.checkpoint?.updated_at].forEach((text) => {
      const ts = parseTs(text || "");
      if (Number.isFinite(ts)) { start = Math.min(start, ts); end = Math.max(end, ts); }
    });
    if (!Number.isFinite(start)) return { start: NaN, end: NaN };
    if (end - start < 60000) end = start + 60000;
    return { start, end: end + 1000 };
  }

  // ============================ 关键节点提取（V9 日志语义） ============================
  function classifyRunRow(row) {
    const msg = row.message;
    let m = msg.match(/^write\s+holding\.runtime\.valve_(\d)\s*=\s*(\d+)/);
    if (m) {
      const valve = VALVE_NAMES[m[1]] || `阀门${m[1]}`;
      const action = VALVE_ACTIONS[m[2]] || `命令${m[2]}`;
      return { type: "valve", title: `${valve} ${action}`, detail: msg, level: row.level, module: row.tag || "YLDQ" };
    }
    m = msg.match(/^write\s+holding\.runtime\.(htc1_mode|htc2_mode|antifreeze_mode)\s*=\s*(\d+)/);
    if (m) {
      const name = HEAT_NAMES[m[1]] || m[1];
      const mode = HEAT_MODES[m[2]] || `模式${m[2]}`;
      return { type: "heat", title: `${name} ${mode}`, detail: msg, level: row.level, module: row.tag || "YLDQ" };
    }
    m = msg.match(/^write\s+holding\.runtime\.remote_heat\s*=\s*(\w+)/);
    if (m) {
      const on = /^(true|1)$/i.test(m[1]);
      return { type: "heat", title: `远程加热${on ? "启用" : "关闭"}`, detail: msg, level: row.level, module: row.tag || "YLDQ" };
    }
    m = msg.match(/^write\s+holding\.runtime\.reset\s*=\s*(\d+)/);
    if (m) return { type: "system", title: `阀门故障复位（${m[1]}）`, detail: msg, level: row.level, module: row.tag || "YLDQ" };
    m = msg.match(/^write\s+(\S+)\s*=\s*(\S+)/);
    if (m) {
      const runtime = m[1].startsWith("holding.runtime.");
      return { type: runtime ? "system" : "config", title: `${runtime ? "运行控制" : "参数暂存"} ${m[1]} = ${m[2]}`, detail: msg, level: row.level, module: row.tag || "YLDQ" };
    }
    const lower = `${row.tag || ""} ${msg}`.toLowerCase();
    let type = "system";
    if (/valve|阀门|阀位/.test(lower)) type = "valve";
    else if (/heat|heating|htc|加热|防冻/.test(lower)) type = "heat";
    else if (/humid|sht|湿度/.test(lower)) type = "humidity";
    else if (/breath|呼吸/.test(lower)) type = "breath";
    else if (/pressure|flow|sensor|i2c|adc|crc|压力|流量|传感器/.test(lower)) type = "sensor";
    else if (/modbus|uart|rs485|tcp|network|lwip|lte|wapi|iec\d*|通信|网络|远程/.test(lower)) type = "communication";
    else if (/config|json|参数|配置/.test(lower)) type = "config";
    else if (/fatfs|sd.?card|storage|file|日志|存储|文件/.test(lower)) type = "storage";
    else if (/watchdog|wdg|stack|fatal|assert|reset|hardfault|cfsr|hfsr|看门狗|堆栈|致命|复位/.test(lower)) type = "safety";
    else if (row.level === "A" || row.level === "E" || /failed|error|timeout|失败|错误|超时/.test(lower)) type = "alarm";
    const title = msg.length > 70 ? `${msg.slice(0, 70)}…` : msg;
    return { type, title, detail: msg, level: row.level || "U", module: row.tag || "SERIAL" };
  }

  function buildEvents() {
    const events = [];
    const meta = source.meta || {};
    const deviceName = meta.device?.name || meta.device?.id || "设备";
    const startedAt = parseTs(meta.started_at || "");
    if (Number.isFinite(startedAt)) events.push({ id: "session-start", ts: startedAt, type: "system", title: "采集会话开始", detail: `${deviceName} 开始记录`, level: "I", module: "会话", sourceType: "meta" });
    const endedAt = parseTs(meta.ended_at || "");
    if (Number.isFinite(endedAt)) events.push({ id: "session-stop", ts: endedAt, type: "system", title: "采集会话结束", detail: `${deviceName} 会话状态：${meta.status || "unknown"}`, level: "I", module: "会话", sourceType: "meta" });
    source.runRows.forEach((row, index) => {
      const info = classifyRunRow(row);
      events.push({ id: `run-${index}`, ts: row.ts, type: info.type, title: info.title, detail: info.detail, level: info.level, module: info.module, sourceType: "run" });
    });
    source.firmwareRows.forEach((row, index) => {
      const info = classifyRunRow(row);
      events.push({ id: `firmware-${index}`, ts: row.ts, type: info.type, title: info.title, detail: info.detail, level: info.level, module: info.module, sourceType: "firmware" });
    });
    source.heatRows.forEach((row, index) => {
      const event = row.event || "事件";
      const type = /阀门/.test(event) ? "valve" : /湿度会话/.test(event) ? "humidity" : /加热/.test(event) ? "heat" : "system";
      events.push({ id: `heat-${index}`, ts: row.ts, type, title: `${row.channel} ${event}`, detail: row.detail, level: "I", module: "上位机", sourceType: "heat" });
    });
    source.trafficRows.forEach((row, index) => {
      const detail = [row.requestSummary, row.responseSummary, row.error].filter(Boolean).join(" · ");
      events.push({ id: `traffic-${index}`, ts: row.ts, type: "communication", title: `通信${row.status === "no_response" ? "无响应" : "异常"}`, detail: detail || `状态 ${row.status || "unknown"}`, level: "W", module: "上位机", sourceType: "traffic" });
    });
    source.breathRows.forEach((row, index) => {
      if (row.rhythm !== 1 && row.state !== 3 && row.state !== 4) return;
      const title = BREATH_STATES[row.state] || `呼吸状态${row.state}`;
      const type = row.state >= 3 ? "alarm" : "breath";
      events.push({ id: `breath-${index}`, ts: row.ts, type, title, detail: `流量 ${row.flow.toFixed(2)} L/min`, level: row.state >= 3 ? "W" : "I", module: "上位机", sourceType: "breath" });
    });
    events.sort((a, b) => (Number.isFinite(a.ts) ? a.ts : Infinity) - (Number.isFinite(b.ts) ? b.ts : Infinity));
    return events;
  }

  // ============================ 界面渲染 ============================
  function renderImportSummary(counts) {
    const summaryEl = $("analysisImportSummary");
    if (!ui.imported) {
      summaryEl.textContent = "未识别到有效数据，请确认选择的是会话文件夹或数据 CSV 文件。";
    } else {
      const device = source.meta && source.meta.device && source.meta.device.name ? `设备 ${source.meta.device.name} · ` : "";
      const untimed = source.firmwareRows.filter((row) => !Number.isFinite(row.ts)).length;
      summaryEl.innerHTML = `已导入：${device}时间范围 <strong>${esc(fmtTime(ui.bounds.start))} ~ ${esc(fmtTime(ui.bounds.end))}</strong> · 下位机日志 ${source.firmwareRows.length} 行 · 上位机运行日志 ${source.runRows.length} 行 · 环境 ${source.envRows.length} 行 · 热事件 ${source.heatRows.length} 条 · 通信异常 ${source.trafficRows.length} 条 · 分类事件 <strong>${ui.events.length}</strong> 个${untimed ? ` · 无设备时间 ${untimed} 行（仅列表统计）` : ""}`;
      $("analysisRangeText").textContent = `${fmtShort(ui.bounds.start)} ~ ${fmtShort(ui.bounds.end)}`;
    }
    const chips = [];
    const push = (label, count, warn) => chips.push(`<span class="analysis-chip${warn ? " warn" : ""}">${label}<strong>${count}</strong></span>`);
    push("环境文件", counts.env); push("呼吸文件", counts.breath); push("下位机日志", counts.firmware); push("上位机运行日志", counts.run); push("热事件", counts.heat); push("通信诊断", counts.traffic);
    push("配置快照", counts.config); push("会话元数据", counts.meta); push("采集检查点", counts.checkpoint);
    if (counts.other) push("忽略文件", counts.other, true);
    $("analysisRecognition").innerHTML = chips.join("");
  }

  function renderToggles() {
    $("analysisToggles").innerHTML = METRICS.map((m) => {
      const checked = ui.activeMetrics.has(m.key) ? "checked" : "";
      const available = !ui.imported || seriesRows(m.key).length > 0;
      return `<label class="trend-toggle${available ? "" : " unavailable"}" title="${available ? "" : "当前导入会话未记录该测点"}"><input type="checkbox" data-metric="${m.key}" ${checked} ${available ? "" : "disabled"}><i style="width:10px;height:10px;border-radius:3px;background:${m.color};display:inline-block"></i>${m.name} (${m.unit})</label>`;
    }).join("");
    $("analysisToggles").querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) ui.activeMetrics.add(input.dataset.metric);
        else ui.activeMetrics.delete(input.dataset.metric);
        draw();
        renderStats();
      });
    });
  }

  function renderDatePresets() {
    const select = $("analysisDatePreset");
    if (!ui.imported) { select.innerHTML = '<option value="">全部已导入日期</option>'; return; }
    const days = new Map();
    const lifecycleRows = [source.meta?.started_at, source.meta?.ended_at, source.checkpoint?.updated_at]
      .map((text) => ({ ts: parseTs(text || "") }))
      .filter((row) => Number.isFinite(row.ts));
    [source.envRows, source.breathRows, source.runRows, source.firmwareRows, source.heatRows, source.trafficRows, lifecycleRows].flat().forEach((row) => {
      if (!Number.isFinite(row.ts)) return;
      const key = fmtTime(row.ts).slice(0, 10);
      if (!days.has(key)) days.set(key, row.ts);
    });
    select.innerHTML = '<option value="">全部已导入日期</option>' + [...days.keys()].sort().map((day) => `<option value="${day}">${day}</option>`).join("");
  }

  function renderDateInputs() {
    if (!ui.imported) return;
    $("analysisStart").value = toDateTimeLocal(ui.view.start);
    $("analysisEnd").value = toDateTimeLocal(ui.view.end);
    $("analysisRangeText").textContent = `${fmtShort(ui.view.start)} ~ ${fmtShort(ui.view.end)}`;
  }

  function rememberView() {
    if (!ui.imported) return;
    ui.viewHistory.push({ ...ui.view });
    if (ui.viewHistory.length > 30) ui.viewHistory.shift();
  }

  function setView(start, end, remember = true) {
    if (!ui.imported || end <= start) return;
    if (remember) rememberView();
    ui.view = clampView(start, end);
    renderDateInputs();
    renderStats();
    draw();
  }

  function renderEventFilters() {
    $("analysisEventFilters").innerHTML = Object.entries(EVENT_TYPES).map(([key, meta]) => {
      const checked = ui.typeFilter.has(key) ? "checked" : "";
      return `<label class="trend-toggle"><input type="checkbox" data-event-type="${key}" ${checked}><i style="width:10px;height:10px;border-radius:50%;background:${meta.color};display:inline-block"></i>${meta.name}</label>`;
    }).join("");
    $("analysisEventFilters").querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) ui.typeFilter.add(input.dataset.eventType);
        else ui.typeFilter.delete(input.dataset.eventType);
        renderLogPanel();
        renderStats();
        draw();
      });
    });
    $("analysisLevelFilters").innerHTML = Object.entries(LOG_LEVELS).map(([key, meta]) => {
      const checked = ui.levelFilter.has(key) ? "checked" : "";
      return `<label class="trend-toggle"><input type="checkbox" data-log-level="${key}" ${checked}><i style="width:10px;height:10px;border-radius:3px;background:${meta.color};display:inline-block"></i>${meta.name}</label>`;
    }).join("");
    $("analysisLevelFilters").querySelectorAll("input").forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) ui.levelFilter.add(input.dataset.logLevel);
        else ui.levelFilter.delete(input.dataset.logLevel);
        renderLogPanel(); renderStats(); draw();
      });
    });
  }

  function filteredEvents() {
    return ui.events.filter((e) => ui.typeFilter.has(e.type) && ui.levelFilter.has(e.level || "U"));
  }

  function renderLogPanel() {
    const events = filteredEvents();
    const counts = {};
    const levelCounts = {};
    const moduleCounts = {};
    ui.events.forEach((e) => { counts[e.type] = (counts[e.type] || 0) + 1; });
    ui.events.forEach((e) => {
      const level = e.level || "U";
      levelCounts[level] = (levelCounts[level] || 0) + 1;
      const module = e.module || "未知";
      moduleCounts[module] = (moduleCounts[module] || 0) + 1;
    });
    $("analysisEventSummary").innerHTML = Object.entries(EVENT_TYPES).map(([key, meta]) =>
      `<span class="analysis-event-chip"><i style="background:${meta.color}"></i>${meta.name}<strong>${counts[key] || 0}</strong></span>`
    ).join("") + Object.entries(LOG_LEVELS).map(([key, meta]) =>
      `<span class="analysis-event-chip"><i style="background:${meta.color}"></i>${meta.name}<strong>${levelCounts[key] || 0}</strong></span>`
    ).join("") + Object.entries(moduleCounts).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([module, count]) =>
      `<span class="analysis-event-chip">${esc(module)}<strong>${count}</strong></span>`
    ).join("") + `<span class="analysis-event-chip">合计<strong>${ui.events.length}</strong></span>`;
    const list = events.slice(-400).reverse();
    $("analysisLogList").innerHTML = list.length
      ? list.map((e) => {
        const meta = EVENT_TYPES[e.type] || EVENT_TYPES.system;
        const selected = ui.selectedEvent && ui.selectedEvent.id === e.id ? " selected" : "";
        const level = LOG_LEVELS[e.level || "U"] || LOG_LEVELS.U;
        const time = Number.isFinite(e.ts) ? fmtTime(e.ts) : "无设备时间";
        return `<div class="event-item analysis-log-item${selected}" data-event-id="${e.id}"><time>${time}</time><span class="event-tag"><i style="background:${meta.color}"></i>${meta.name}</span><div><span class="event-title">[${esc(e.module || "未知")}/${level.name}] ${esc(e.title)}</span><span class="event-detail">${esc(e.detail)}</span></div></div>`;
      }).join("")
      : `<div class="empty-state">没有匹配的事件，请调整上方类型筛选或先导入数据。</div>`;
    $("analysisLogList").querySelectorAll(".analysis-log-item").forEach((item) => {
      item.addEventListener("click", () => locateEvent(item.dataset.eventId));
    });
  }

  function locateEvent(eventId) {
    const event = ui.events.find((e) => e.id === eventId);
    if (!event) return;
    ui.selectedEvent = event;
    if (!Number.isFinite(event.ts)) { renderLogPanel(); return; }
    const span = ui.view.end - ui.view.start;
    const inView = event.ts >= ui.view.start && event.ts <= ui.view.end;
    if (!inView) {
      const newSpan = Math.min(span, 30 * 60000);
      ui.view = clampView(event.ts - newSpan / 2, event.ts + newSpan / 2);
    }
    if (!ui.showEvents) {
      ui.showEvents = true;
      $("analysisToggleEventsBtn").classList.add("active");
    }
    renderLogPanel();
    renderStats();
    draw();
    $("analysisChartPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderStats() {
    const host = $("analysisStats");
    if (!ui.imported) {
      host.innerHTML = `<div class="empty-state" style="grid-column:1/-1">导入数据后显示统计信息</div>`;
      return;
    }
    const items = [];
    METRICS.filter((m) => ui.activeMetrics.has(m.key)).forEach((m) => {
      const rows = seriesRows(m.key).filter((r) => r.ts >= ui.view.start && r.ts <= ui.view.end);
      if (!rows.length) return;
      let min = Infinity, max = -Infinity, sum = 0;
      rows.forEach((r) => { const v = r[m.key]; if (v < min) min = v; if (v > max) max = v; sum += v; });
      const latest = rows[rows.length - 1][m.key];
      items.push(`<div class="latest-item"><span style="color:${m.color}">${m.name} (${m.unit})</span><strong>${latest.toFixed(2)}</strong><small>最小 ${min.toFixed(2)} · 最大 ${max.toFixed(2)} · 平均 ${(sum / rows.length).toFixed(2)}</small></div>`);
    });
    const inView = filteredEvents().filter((e) => e.ts >= ui.view.start && e.ts <= ui.view.end);
    const keyCount = inView.filter((e) => e.type === "valve" || e.type === "heat").length;
    const warningCount = inView.filter((e) => e.level === "W").length;
    const errorCount = inView.filter((e) => e.level === "E" || e.level === "A").length;
    items.push(`<div class="latest-item"><span>当前视图分类事件</span><strong>${inView.length}</strong><small>阀门/加热 ${keyCount} · 警告 ${warningCount} · 错误/断言 ${errorCount}</small></div>`);
    host.innerHTML = items.join("") || `<div class="empty-state" style="grid-column:1/-1">当前视图范围内没有数据</div>`;
  }

  // ============================ 曲线绘制（Canvas 2D，与实时曲线同风格） ============================
  function seriesRows(key) {
    if (source.envRows.length) return source.envRows.filter((row) => Number.isFinite(row[key]));
    if (key === "flow" && source.breathRows.length) {
      return source.breathRows.map((r) => ({ ts: r.ts, flow: r.flow }));
    }
    return [];
  }

  function lowerBound(rows, ts) {
    let lo = 0, hi = rows.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (rows[mid].ts < ts) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  function clampView(start, end) {
    const span = end - start;
    const { start: b0, end: b1 } = ui.bounds;
    if (start < b0) { start = b0; end = start + span; }
    if (end > b1) { end = b1; start = end - span; }
    return { start, end };
  }

  function draw() {
    const canvas = $("analysisCanvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const hasData = ui.imported && METRICS.some((m) => ui.activeMetrics.has(m.key) && seriesRows(m.key).length);
    $("analysisChartEmpty").classList.toggle("hidden", !!hasData);
    if (!hasData) return;

    const padL = 12, padR = 12, padT = 52, padB = 26;
    const plotW = w - padL - padR, plotH = h - padT - padB;
    const t0 = ui.view.start, t1 = ui.view.end;
    const xOf = (ts) => padL + ((ts - t0) / (t1 - t0)) * plotW;

    ctx.strokeStyle = "rgba(33,54,77,.65)";
    ctx.fillStyle = "#8ca2b7";
    ctx.font = "10px 'Segoe UI',sans-serif";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const y = padT + (plotH * i) / 4;
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
    }
    const tickCount = Math.max(2, Math.min(8, Math.floor(plotW / 110)));
    for (let i = 0; i <= tickCount; i += 1) {
      const ts = t0 + ((t1 - t0) * i) / tickCount;
      const x = xOf(ts);
      ctx.fillText(fmtShort(ts), Math.min(Math.max(x - 28, 2), w - 62), h - 8);
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + 4); ctx.stroke();
    }

    const active = METRICS.filter((m) => ui.activeMetrics.has(m.key));
    const scales = {};
    active.forEach((m, idx) => {
      const rows = seriesRows(m.key);
      if (!rows.length) return;
      const from = Math.max(0, lowerBound(rows, t0) - 1);
      const to = Math.min(rows.length, lowerBound(rows, t1) + 2);
      let min = Infinity, max = -Infinity;
      for (let i = from; i < to; i += 1) {
        const v = rows[i][m.key];
        if (v < min) min = v;
        if (v > max) max = v;
      }
      if (!Number.isFinite(min)) return;
      if (max - min < 1e-6) { min -= 1; max += 1; }
      const pad = (max - min) * 0.08;
      min -= pad; max += pad;
      const middle = (min + max) / 2;
      const halfRange = ((max - min) / 2) * ui.yScale;
      min = middle - halfRange; max = middle + halfRange;
      scales[m.key] = { min, max };
      const yOf = (v) => padT + plotH - ((v - min) / (max - min)) * plotH;
      const stride = Math.max(1, Math.ceil((to - from) / (plotW * 2)));
      ctx.strokeStyle = m.color;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      for (let i = from; i < to; i += stride) {
        const x = xOf(rows[i].ts), y = yOf(rows[i][m.key]);
        if (i === from) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.fillStyle = m.color;
      ctx.fillText(`${m.name} ${min.toFixed(1)}~${max.toFixed(1)} ${m.unit}`, padL + 6, 12 + idx * 11);
      if (ui.showKeyPoints) drawSeriesKeyPoints(ctx, rows, from, to, xOf, yOf, m.color, m.key);
      if (ui.showLabels) {
        const latest = rows[Math.max(from, to - 1)];
        if (latest) ctx.fillText(`${m.name} ${latest[m.key].toFixed(2)} ${m.unit}`, Math.max(padL + 4, xOf(latest.ts) - 112), Math.max(padT + 12, yOf(latest[m.key]) - 8));
      }
    });

    if (ui.showEvents) {
      drawEventTimeline(ctx, xOf, padT, w);
      drawEventMarkers(ctx, xOf, padT, plotH, scales, active);
    }

    if (ui.hoverX != null && ui.hoverX >= padL && ui.hoverX <= w - padR) {
      const ts = t0 + ((ui.hoverX - padL) / plotW) * (t1 - t0);
      ctx.strokeStyle = "rgba(232,241,248,.35)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(ui.hoverX, padT); ctx.lineTo(ui.hoverX, padT + plotH); ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  function drawSeriesKeyPoints(ctx, rows, from, to, xOf, yOf, color, valueKey) {
    if (to <= from) return;
    let minRow = rows[from], maxRow = rows[from];
    for (let i = from + 1; i < to; i += 1) {
      if (rows[i] && rows[i][valueKey] < minRow[valueKey]) minRow = rows[i];
      if (rows[i] && rows[i][valueKey] > maxRow[valueKey]) maxRow = rows[i];
    }
    [minRow, maxRow, rows[to - 1]].filter(Boolean).forEach((row) => {
      ctx.fillStyle = "#07111f"; ctx.strokeStyle = color; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.arc(xOf(row.ts), yOf(row[valueKey]), 3.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    });
  }

  function drawEventTimeline(ctx, xOf, padT, width) {
    const events = filteredEvents().filter((event) => event.ts >= ui.view.start && event.ts <= ui.view.end);
    const y = padT - 15;
    ctx.strokeStyle = "rgba(140,162,183,.48)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(12, y); ctx.lineTo(width - 12, y); ctx.stroke();
    ctx.fillStyle = "#8ca2b7"; ctx.font = "10px 'Segoe UI',sans-serif"; ctx.fillText(`日志时间线 ${events.length} 条`, 16, y - 5);
    sampleEventsForCanvas(events, 260).forEach((event) => {
      const meta = EVENT_TYPES[event.type] || EVENT_TYPES.system;
      const x = xOf(event.ts);
      ctx.fillStyle = meta.color;
      ctx.beginPath(); ctx.arc(x, y, event.type === "alarm" ? 3.5 : 2.5, 0, Math.PI * 2); ctx.fill();
    });
  }

  function drawEventMarkers(ctx, xOf, padT, plotH, scales, active) {
    const t0 = ui.view.start, t1 = ui.view.end;
    const visible = filteredEvents().filter((e) => e.ts >= t0 && e.ts <= t1);
    const major = visible.filter((e) => e.type !== "breath");
    const breath = visible.filter((e) => e.type === "breath");
    const flowMetric = active.find((m) => m.key === "flow");
    const flowRows = flowMetric ? seriesRows("flow") : [];
    const anchorY = (ts) => {
      if (!flowMetric || !flowRows.length || !scales.flow) return padT + 6;
      const idx = Math.min(flowRows.length - 1, lowerBound(flowRows, ts));
      const v = flowRows[idx].flow;
      const { min, max } = scales.flow;
      return padT + plotH - ((v - min) / (max - min)) * plotH;
    };
    const labelLimit = 24;
    sampleEventsForCanvas(breath, 400).forEach((e) => {
      const x = xOf(e.ts);
      ctx.fillStyle = EVENT_TYPES.breath.color;
      ctx.globalAlpha = 0.5;
      ctx.beginPath(); ctx.arc(x, padT + plotH - 3, 2.4, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
    });
    const drawnMajor = sampleEventsForCanvas(major, 300);
    if (ui.selectedEvent) {
      const selected = major.find((event) => event.id === ui.selectedEvent.id);
      if (selected && !drawnMajor.some((drawn) => drawn.id === selected.id)) drawnMajor.push(selected);
    }
    drawnMajor.forEach((e, i) => {
      const x = xOf(e.ts);
      const meta = EVENT_TYPES[e.type] || EVENT_TYPES.system;
      const selected = ui.selectedEvent && ui.selectedEvent.id === e.id;
      ctx.strokeStyle = meta.color;
      ctx.globalAlpha = selected ? 0.95 : 0.4;
      ctx.lineWidth = selected ? 1.8 : 1;
      ctx.setLineDash(selected ? [] : [5, 4]);
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      const y = anchorY(e.ts);
      ctx.fillStyle = meta.color;
      ctx.beginPath(); ctx.arc(x, y, selected ? 6 : 4, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#07111f";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      if (drawnMajor.length <= labelLimit) {
        ctx.fillStyle = meta.color;
        ctx.font = "10px 'Segoe UI',sans-serif";
        const label = e.title.length > 14 ? `${e.title.slice(0, 14)}…` : e.title;
        const ly = padT + 8 + (i % 2) * 11;
        ctx.fillText(label, Math.min(x + 5, innerWidthOfChart() - 90), ly);
      }
    });
  }

  function sampleEventsForCanvas(events, limit) {
    if (events.length <= limit) return events;
    const step = Math.ceil(events.length / limit);
    return events.filter((_, index) => index % step === 0);
  }

  function innerWidthOfChart() {
    return $("analysisCanvas").clientWidth;
  }

  // ============================ 交互 ============================
  function zoomAt(fraction, factor) {
    if (!ui.imported) return;
    const { start, end } = ui.view;
    const span = end - start;
    const minSpan = 10000, maxSpan = (ui.bounds.end - ui.bounds.start) * 1.2;
    let newSpan = Math.min(maxSpan, Math.max(minSpan, span * factor));
    const anchor = start + span * fraction;
    ui.view = clampView(anchor - newSpan * fraction, anchor + newSpan * (1 - fraction));
    renderStats();
    draw();
  }

  function panBy(fraction) {
    if (!ui.imported) return;
    const span = ui.view.end - ui.view.start;
    ui.view = clampView(ui.view.start + span * fraction, ui.view.end + span * fraction);
    renderStats();
    draw();
  }

  function canvasTs(clientX) {
    const canvas = $("analysisCanvas");
    const rect = canvas.getBoundingClientRect();
    const padL = 12, padR = 12;
    const x = clientX - rect.left;
    const plotW = rect.width - padL - padR;
    return { x, ts: ui.view.start + ((x - padL) / plotW) * (ui.view.end - ui.view.start) };
  }

  function showTooltip(clientX, clientY) {
    const tip = $("analysisTooltip");
    if (!ui.imported) return;
    const { ts } = canvasTs(clientX);
    const rows = [];
    const values = METRICS.filter((m) => ui.activeMetrics.has(m.key)).map((m) => {
      const data = seriesRows(m.key);
      if (!data.length) return null;
      const idx = Math.min(data.length - 1, lowerBound(data, ts));
      return { m, v: data[idx][m.key] };
    }).filter(Boolean);
    const nearEvents = ui.events.filter((e) => Math.abs(e.ts - ts) < Math.max(15000, (ui.view.end - ui.view.start) / 200)).slice(0, 3);
    let html = `<time>${fmtTime(ts)}</time>`;
    values.forEach(({ m, v }) => {
      html += `<div class="tt-row"><span style="color:${m.color}">${m.name}</span><strong>${v.toFixed(2)} ${m.unit}</strong></div>`;
    });
    nearEvents.forEach((e) => {
      html += `<div class="tt-event">${esc(e.title)}<br><small>${esc(fmtTime(e.ts))}</small></div>`;
    });
    tip.innerHTML = html;
    tip.classList.remove("hidden");
    const panelRect = $("analysisChartPanel").getBoundingClientRect();
    const x = clientX - panelRect.left + 14;
    const y = clientY - panelRect.top + 14;
    tip.style.left = `${Math.min(x, panelRect.width - 240)}px`;
    tip.style.top = `${Math.min(y, panelRect.height - 120)}px`;
    void rows;
  }

  function bindInteractions() {
    const canvas = $("analysisCanvas");
    canvas.addEventListener("wheel", (e) => {
      if (!ui.imported) return;
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const fraction = Math.min(1, Math.max(0, (e.clientX - rect.left - 12) / (rect.width - 24)));
      zoomAt(fraction, e.deltaY > 0 ? 1.25 : 0.8);
    }, { passive: false });
    canvas.addEventListener("mousedown", (e) => {
      if (!ui.imported) return;
      ui.drag = { x: e.clientX, start: ui.view.start, end: ui.view.end };
      canvas.style.cursor = "grabbing";
    });
    window.addEventListener("mousemove", (e) => {
      if (ui.drag) {
        const rect = canvas.getBoundingClientRect();
        const span = ui.drag.end - ui.drag.start;
        const dt = -((e.clientX - ui.drag.x) / (rect.width - 24)) * span;
        ui.view = clampView(ui.drag.start + dt, ui.drag.end + dt);
        renderStats();
        draw();
        return;
      }
      const rect = canvas.getBoundingClientRect();
      if (e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom) {
        ui.hoverX = e.clientX - rect.left;
        showTooltip(e.clientX, e.clientY);
        draw();
      } else {
        ui.hoverX = null;
        $("analysisTooltip").classList.add("hidden");
      }
    });
    window.addEventListener("mouseup", () => {
      if (ui.drag) {
        ui.drag = null;
        canvas.style.cursor = "";
      }
    });
    canvas.addEventListener("mouseleave", () => {
      ui.hoverX = null;
      $("analysisTooltip").classList.add("hidden");
      draw();
    });
    document.addEventListener("keydown", (e) => {
      const pageActive = document.querySelector('[data-page-view="analysis"].active');
      if (!pageActive || !ui.imported || e.target.matches("input,textarea,select")) return;
      if (e.key === "r" || e.key === "R") { ui.view = { ...ui.bounds }; ui.yScale = 1; renderDateInputs(); renderStats(); draw(); }
      else if (e.key === "+" || e.key === "=") zoomAt(0.5, 0.7);
      else if (e.key === "-") zoomAt(0.5, 1.4);
      else if (e.key === "ArrowLeft") panBy(-0.2);
      else if (e.key === "ArrowRight") panBy(0.2);
      else if (e.key === "f" || e.key === "F") $("analysisFullscreenBtn").click();
      else if (e.key === "Escape" && $("analysisChartPanel").classList.contains("chart-fullscreen")) $("analysisFullscreenBtn").click();
    });
    window.addEventListener("resize", () => {
      if (document.querySelector('[data-page-view="analysis"].active')) draw();
    });
  }

  function bindToolbar() {
    $("analysisUndoBtn").addEventListener("click", () => {
      const previous = ui.viewHistory.pop();
      if (!previous) return;
      ui.view = previous;
      renderDateInputs(); renderStats(); draw();
    });
    $("analysisResetBtn").addEventListener("click", () => {
      if (!ui.imported) return;
      ui.yScale = 1;
      setView(ui.bounds.start, ui.bounds.end);
    });
    $("analysisPanLeftBtn").addEventListener("click", () => panBy(-0.25));
    $("analysisPanRightBtn").addEventListener("click", () => panBy(0.25));
    $("analysisZoomInBtn").addEventListener("click", () => zoomAt(0.5, 0.6));
    $("analysisZoomOutBtn").addEventListener("click", () => zoomAt(0.5, 1.6));
    $("analysisTightenYBtn").addEventListener("click", () => { ui.yScale = Math.max(0.2, ui.yScale * 0.8); draw(); });
    $("analysisRelaxYBtn").addEventListener("click", () => { ui.yScale = Math.min(5, ui.yScale * 1.25); draw(); });
    $("analysisToggleLabelsBtn").addEventListener("click", (e) => {
      ui.showLabels = !ui.showLabels; e.currentTarget.classList.toggle("active", ui.showLabels); draw();
    });
    $("analysisToggleKeyPointsBtn").addEventListener("click", (e) => {
      ui.showKeyPoints = !ui.showKeyPoints; e.currentTarget.classList.toggle("active", ui.showKeyPoints); draw();
    });
    $("analysisToggleEventsBtn").addEventListener("click", (e) => {
      ui.showEvents = !ui.showEvents;
      e.currentTarget.classList.toggle("active", ui.showEvents);
      draw();
    });
    $("analysisLogBtn").addEventListener("click", (e) => {
      ui.logOpen = !ui.logOpen;
      $("analysisLogPanel").classList.toggle("hidden", !ui.logOpen);
      e.currentTarget.classList.toggle("active", ui.logOpen);
      if (ui.logOpen) {
        renderLogPanel();
        $("analysisLogPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
    $("analysisLogCloseBtn").addEventListener("click", () => {
      ui.logOpen = false;
      $("analysisLogPanel").classList.add("hidden");
      $("analysisLogBtn").classList.remove("active");
    });
    $("analysisExportBtn").addEventListener("click", exportCsv);
    $("analysisExportPngBtn").addEventListener("click", () => {
      if (!ui.imported) return;
      const link = document.createElement("a");
      link.href = $("analysisCanvas").toDataURL("image/png");
      link.download = `YLDQ_数据分析_${fmtTime(ui.view.start).replace(/[-: ]/g, "")}.png`;
      link.click();
    });
    $("analysisFullscreenBtn").addEventListener("click", () => {
      const panel = $("analysisChartPanel");
      const active = panel.classList.toggle("chart-fullscreen");
      document.body.classList.toggle("analysis-fullscreen-active", active);
      $("analysisFullscreenBtn").textContent = active ? "退出全屏" : "全屏";
      setTimeout(draw, 80);
    });
    $("analysisApplyRangeBtn").addEventListener("click", () => {
      const start = new Date($("analysisStart").value).getTime();
      const end = new Date($("analysisEnd").value).getTime();
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
      setView(start, end);
    });
    $("analysisDatePreset").addEventListener("change", (e) => {
      if (!ui.imported) return;
      if (!e.target.value) { setView(ui.bounds.start, ui.bounds.end); return; }
      const start = new Date(`${e.target.value}T00:00:00`).getTime();
      setView(start, start + 24 * 60 * 60 * 1000);
    });
    document.querySelectorAll("[data-analysis-window]").forEach((button) => button.addEventListener("click", () => {
      if (!ui.imported) return;
      const end = ui.bounds.end, start = Math.max(ui.bounds.start, end - Number(button.dataset.analysisWindow));
      setView(start, end);
    }));
  }

  function exportCsv() {
    if (!ui.imported) return;
    const rows = source.envRows.filter((r) => r.ts >= ui.view.start && r.ts <= ui.view.end);
    const metrics = METRICS.filter((metric) => ui.activeMetrics.has(metric.key));
    const lines = [["time", ...metrics.map((metric) => `${metric.name}(${metric.unit})`)].join(",")];
    rows.forEach((row) => lines.push([fmtTime(row.ts), ...metrics.map((metric) => row[metric.key] ?? "")].join(",")));
    lines.push("");
    lines.push("event_time,event_type,event_title,event_detail");
    filteredEvents().filter((e) => e.ts >= ui.view.start && e.ts <= ui.view.end)
      .forEach((e) => lines.push(`${fmtTime(e.ts)},${EVENT_TYPES[e.type].name},"${e.title.replace(/"/g, '""')}","${e.detail.replace(/"/g, '""')}"`));
    const blob = new Blob(["\uFEFF" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `analysis_${fmtTime(ui.view.start).replace(/[-: ]/g, "")}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function bindImport() {
    $("analysisImportFolderBtn").addEventListener("click", () => $("analysisFolderInput").click());
    $("analysisImportFilesBtn").addEventListener("click", () => $("analysisFilesInput").click());
    $("analysisFolderInput").addEventListener("change", (e) => {
      handleImportedFiles(e.target.files);
      e.target.value = "";
    });
    $("analysisFilesInput").addEventListener("change", (e) => {
      handleImportedFiles(e.target.files);
      e.target.value = "";
    });
    $("analysisClearBtn").addEventListener("click", () => {
      resetData();
      $("analysisImportSummary").textContent = "尚未导入数据";
      $("analysisRecognition").innerHTML = "";
      $("analysisRangeText").textContent = "未导入数据";
      $("analysisLogList").innerHTML = "";
      $("analysisEventSummary").innerHTML = "";
      $("analysisLogPanel").classList.add("hidden");
      $("analysisLogBtn").classList.remove("active");
      renderDatePresets();
      renderToggles();
      renderStats();
      draw();
    });
    document.querySelectorAll(".nav-item").forEach((n) => {
      n.addEventListener("click", () => {
        if (n.dataset.page === "analysis") requestAnimationFrame(() => { renderStats(); draw(); });
      });
    });
  }

  function init() {
    bindImport();
    bindToolbar();
    bindInteractions();
    renderToggles();
    renderEventFilters();
    renderStats();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
