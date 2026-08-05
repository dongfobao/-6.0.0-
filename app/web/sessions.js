"use strict";

const sessionArchive = {
  list: [],
  selectedName: null,
  detail: null,
  loading: false,
};

function sessionStatusBadge(status) {
  const map = { recording: ["记录中", "recording"], stopped: ["已停止", "stopped"], completed: ["已完成", "stopped"] };
  const [text, cls] = map[status] || [status || "未知", "unknown"];
  return `<span class="session-status ${cls}">${esc(text)}</span>`;
}

async function sessionArchiveRefresh() {
  if (sessionArchive.loading) return;
  sessionArchive.loading = true;
  try {
    const deviceParam = state.selectedDeviceId ? `?deviceId=${encodeURIComponent(state.selectedDeviceId)}` : "";
    const payload = await api(`/api/sessions/list${deviceParam}`);
    sessionArchive.list = payload.items || [];
    renderSessionList();
    if (sessionArchive.selectedName && sessionArchive.list.some((item) => item.name === sessionArchive.selectedName)) {
      await loadSessionDetail(sessionArchive.selectedName, true);
    }
  } catch (error) {
    showNotice(`会话列表加载失败：${error.message}`, "error");
  } finally {
    sessionArchive.loading = false;
  }
}

function renderSessionList() {
  const body = $("sessionsTableBody");
  $("sessionsSummaryText").textContent = sessionArchive.list.length ? `共 ${sessionArchive.list.length} 个会话` : "暂无会话记录";
  if (!sessionArchive.list.length) {
    body.innerHTML = `<tr><td colspan="6" class="sessions-empty">暂无历史会话，启动监控后自动生成</td></tr>`;
    return;
  }
  body.innerHTML = sessionArchive.list.map((item) => `
    <tr class="session-row ${item.name === sessionArchive.selectedName ? "selected" : ""}" data-session="${esc(item.name)}">
      <td>${esc(item.startedAt || "--")}</td>
      <td>${esc(item.deviceName || item.deviceId || "--")}</td>
      <td>${esc(item.endedAt || (item.status === "recording" ? "记录中" : "--"))}</td>
      <td>${sessionStatusBadge(item.status)}</td>
      <td>${esc(item.durationText || "--")}</td>
      <td><button class="button small secondary session-open-btn" data-session="${esc(item.name)}">查看</button></td>
    </tr>`).join("");
}

async function loadSessionDetail(name, silent) {
  try {
    const payload = await api(`/api/sessions/detail?name=${encodeURIComponent(name)}`);
    sessionArchive.selectedName = name;
    sessionArchive.detail = payload;
    renderSessionDetail();
    renderSessionList();
  } catch (error) {
    if (!silent) showNotice(`会话详情加载失败：${error.message}`, "error");
  }
}

function renderSessionDetail() {
  const detail = sessionArchive.detail;
  if (!detail) return;
  $("sessionsDetailEmpty").classList.add("hidden");
  $("sessionsDetail").classList.remove("hidden");
  const s = detail.session || {};
  const summary = detail.summary || {};
  $("sessionsMetaCard").innerHTML = `
    <div class="sessions-meta-grid">
      <div><span>会话名称</span><strong>${esc(s.name || "--")}</strong></div>
      <div><span>设备</span><strong>${esc(s.deviceName || s.deviceId || "--")}</strong></div>
      <div><span>开始时间</span><strong>${esc(s.startedAt || "--")}</strong></div>
      <div><span>结束时间</span><strong>${esc(s.endedAt || (s.status === "recording" ? "记录中" : "--"))}</strong></div>
      <div><span>状态</span><strong>${sessionStatusBadge(s.status)}</strong></div>
      <div><span>持续时长</span><strong>${esc(s.durationText || "--")}</strong></div>
      <div><span>事件总数</span><strong>${esc(summary.totalEvents ?? 0)}</strong></div>
      <div><span>加热开启总次数</span><strong>${esc(summary.heatOpenTotal ?? 0)}</strong></div>
      <div><span>阀门动作总次数</span><strong>${esc(summary.valveActionTotal ?? 0)}</strong></div>
    </div>`;

  const statsBody = $("sessionsStatsBody");
  const rows = summary.channels || [];
  statsBody.innerHTML = rows.length ? rows.map((row) => `
    <tr>
      <td>${esc(row.channel)}</td>
      <td>${row.kind === "heat" ? "加热" : "阀门"}</td>
      <td>${row.kind === "heat" ? esc(row.openCount) : "--"}</td>
      <td>${row.kind === "heat" ? esc(row.activeDurationText) : "--"}</td>
      <td>${row.kind === "valve" ? esc(row.actionCount) : "--"}</td>
      <td>${esc(row.lastEvent ? `${row.lastEventTime} ${row.lastEvent}` : "--")}</td>
    </tr>`).join("") : `<tr><td colspan="6" class="sessions-empty">暂无统计数据</td></tr>`;

  const channelFilter = $("sessionsChannelFilter");
  const eventFilter = $("sessionsEventFilter");
  const prevChannel = channelFilter.value;
  const prevEvent = eventFilter.value;
  channelFilter.innerHTML = `<option value="">全部通道</option>` + (detail.channels || []).map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  eventFilter.innerHTML = `<option value="">全部事件</option>` + (detail.eventTypes || []).map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  channelFilter.value = prevChannel;
  eventFilter.value = prevEvent;
  renderSessionEvents();
}

function renderSessionEvents() {
  const detail = sessionArchive.detail;
  if (!detail) return;
  const channelValue = $("sessionsChannelFilter").value;
  const eventValue = $("sessionsEventFilter").value;
  const events = (detail.events || []).filter((item) =>
    (!channelValue || item.channel === channelValue) && (!eventValue || item.event === eventValue));
  $("sessionsEventCount").textContent = `共 ${events.length} 条`;
  const body = $("sessionsEventsBody");
  body.innerHTML = events.length ? events.map((item) => `
    <tr>
      <td class="session-event-time">${esc(item.time)}</td>
      <td>${esc(item.channel)}</td>
      <td><span class="session-event-tag">${esc(item.event)}</span></td>
      <td>${esc(item.detail || "--")}</td>
    </tr>`).join("") : `<tr><td colspan="4" class="sessions-empty">该会话暂无匹配事件</td></tr>`;
}

function exportSessionCsv() {
  const detail = sessionArchive.detail;
  if (!detail || !(detail.events || []).length) {
    showNotice("当前会话没有可导出的事件", "error");
    return;
  }
  const channelValue = $("sessionsChannelFilter").value;
  const eventValue = $("sessionsEventFilter").value;
  const events = detail.events.filter((item) =>
    (!channelValue || item.channel === channelValue) && (!eventValue || item.event === eventValue));
  const lines = ["时间,通道,事件,详情"].concat(events.map((item) =>
    [item.time, item.channel, item.event, item.detail || ""].map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(",")));
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${sessionArchive.selectedName || "session"}_events.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function bindSessionArchive() {
  $("sessionsRefreshBtn").addEventListener("click", sessionArchiveRefresh);
  $("sessionsTableBody").addEventListener("click", (event) => {
    const row = event.target.closest("[data-session]");
    if (row) loadSessionDetail(row.dataset.session);
  });
  $("sessionsChannelFilter").addEventListener("change", renderSessionEvents);
  $("sessionsEventFilter").addEventListener("change", renderSessionEvents);
  $("sessionsExportBtn").addEventListener("click", exportSessionCsv);
}

bindSessionArchive();
