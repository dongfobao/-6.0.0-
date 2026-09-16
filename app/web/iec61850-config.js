"use strict";

(() => {
  const iecState = {loaded: false, loading: false, profile: null, catalog: [], meta: new Map(), capabilities: {}};
  const iecEsc = value => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

  function element(id) { return document.getElementById(id); }
  async function iecApi(path, options = {}) {
    const response = await fetch(path, {headers:{"Content-Type":"application/json", ...(options.headers || {})}, ...options});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
    return payload;
  }
  function notify(message, type = "success") {
    if (typeof showNotice === "function") showNotice(message, type);
  }

  function selectedProfile(payload) {
    const profiles = payload?.profiles?.profiles || [];
    const selectedId = payload?.profiles?.selectedProfileId;
    return structuredClone(profiles.find(item => item.id === selectedId) || profiles[0]);
  }

  function setValue(id, value) { const node = element(id); if (node) node.value = value ?? ""; }
  function readFields() {
    const p = iecState.profile;
    p.name = element("iecProfileName").value.trim();
    p.iedName = element("iecIedName").value.trim();
    p.logicalDevice = element("iecLogicalDevice").value.trim();
    p.pointPrefix = element("iecPointPrefix").value.trim();
    p.stationPrefix = element("iecStationPrefix").value.trim();
    p.network = {
      ip: element("iecIp").value.trim(), netmask: element("iecNetmask").value.trim(),
      gateway: element("iecGateway").value.trim(), port: Number(element("iecPort").value || 102),
    };
    return p;
  }

  function fillFields() {
    const p = iecState.profile;
    setValue("iecProfileName", p.name); setValue("iecIedName", p.iedName);
    setValue("iecLogicalDevice", p.logicalDevice); setValue("iecPointPrefix", p.pointPrefix);
    setValue("iecStationPrefix", p.stationPrefix);
    setValue("iecIp", p.network.ip); setValue("iecNetmask", p.network.netmask);
    setValue("iecGateway", p.network.gateway); setValue("iecPort", p.network.port);
  }

  function currentSearch() { return (element("iecPointSearch")?.value || "").trim().toLowerCase(); }
  function matches(meta, point, search) {
    if (!search) return true;
    return [meta.sourceName, meta.pointId, meta.area, meta.address, point.stationName, point.objectName]
      .some(value => String(value ?? "").toLowerCase().includes(search));
  }

  function renderTable() {
    if (!iecState.profile) return;
    readFields();
    const search = currentSearch();
    const rows = iecState.profile.points.map((point, index) => ({point, index, meta: iecState.meta.get(point.pointId)}))
      .filter(item => item.meta && matches(item.meta, item.point, search));
    element("iecPointTableBody").innerHTML = rows.map(({point, index, meta}) => {
      const attribute = meta.category === "analog" ? "mag.f" : "stVal";
      const reference = `${iecState.profile.iedName}${iecState.profile.logicalDevice}/${meta.logicalNode}.${point.objectName}.${attribute}`;
      return `<tr data-index="${index}">
        <td><input class="iec-enabled" type="checkbox" ${point.enabled ? "checked" : ""} aria-label="启用${iecEsc(meta.sourceName)}"></td>
        <td class="iec-source"><strong>${iecEsc(meta.sourceName)}</strong><small>${iecEsc(meta.area)} ${meta.address} · ${meta.wordLength}字 · ${iecEsc(meta.unit || meta.dataType)}</small></td>
        <td>${meta.category === "analog" ? "模拟量" : meta.category === "binary" ? "状态量" : "统计量"}</td>
        <td><input class="iec-station-name" type="text" maxlength="80" value="${iecEsc(point.stationName)}"></td>
        <td><input class="iec-object-name" type="text" maxlength="12" value="${iecEsc(point.objectName)}"></td>
        <td class="iec-ref">${iecEsc(reference)}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="6" class="muted">没有匹配的转发点</td></tr>`;
    element("iecPointCount").textContent = `${iecState.profile.points.filter(item => item.enabled).length} / ${iecState.catalog.length}`;
    renderSummary();
  }

  function syncRow(event) {
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    const point = iecState.profile.points[Number(row.dataset.index)];
    if (!point) return;
    if (event.target.classList.contains("iec-enabled")) point.enabled = event.target.checked;
    if (event.target.classList.contains("iec-station-name")) point.stationName = event.target.value;
    if (event.target.classList.contains("iec-object-name")) point.objectName = event.target.value.trim();
    renderSummary();
  }

  function renderSummary() {
    if (!iecState.profile) return;
    readFields();
    const selected = iecState.profile.points.filter(item => item.enabled).length;
    element("iecSelectedSummary").textContent = `${selected} / ${iecState.catalog.length}`;
    element("iecMappingSummary").textContent = `${selected * 3} / 128`;
    element("iecNetworkSummary").textContent = `${iecState.profile.network.ip}:${iecState.profile.network.port}`;
    element("iecRootSummary").textContent = `${iecState.profile.iedName}${iecState.profile.logicalDevice}/`;
  }

  function profileBody() { readFields(); return JSON.stringify({profile: iecState.profile}); }

  async function loadWorkspace() {
    if (iecState.loaded || iecState.loading) return;
    iecState.loading = true;
    try {
      const payload = await iecApi("/api/iec61850/bootstrap");
      iecState.catalog = payload.catalog || [];
      iecState.meta = new Map(iecState.catalog.map(item => [item.pointId, item]));
      iecState.capabilities = payload.capabilities || {};
      iecState.profile = selectedProfile(payload);
      if (!iecState.profile) throw new Error("没有可用的IEC61850配置项目");
      fillFields(); renderTable();
      iecState.loaded = true;
    } catch (error) {
      element("iecCapabilityText").textContent = error.message;
      notify(error.message, "error");
    } finally { iecState.loading = false; }
  }

  async function saveProfile(showSuccess = true) {
    const saved = await iecApi("/api/iec61850/profile", {method:"POST", body:profileBody()});
    iecState.profile = saved; fillFields(); renderTable();
    if (showSuccess) notify("IEC61850配置项目已保存");
    return saved;
  }

  async function generatePackage() {
    const button = element("iecGenerateBtn"); button.disabled = true; button.textContent = "正在生成…";
    try {
      await saveProfile(false);
      const result = await iecApi("/api/iec61850/generate", {method:"POST", body:profileBody()});
      const files = Object.entries(result.files || {}).map(([key, path]) => `<li><b>${iecEsc(key)}</b>：<code>${iecEsc(path)}</code></li>`).join("");
      element("iecOutput").className = "iec-output";
      element("iecOutput").innerHTML = `<strong>配置包已生成并校验通过</strong><br>目录：<code>${iecEsc(result.outputDirectory)}</code><ul>${files}</ul><small>共${result.manifest.selectedPointCount}个源点、${result.manifest.mappingCount}条映射属性。</small>`;
      notify("总站配置包生成完成");
    } catch (error) { notify(error.message, "error"); }
    finally { button.disabled = false; button.textContent = "生成总站配置包"; }
  }

  async function probe() {
    readFields();
    const node = element("iecProbeResult"); node.className = "iec-probe-result muted"; node.textContent = "正在测试TCP端口…";
    try {
      const result = await iecApi("/api/iec61850/probe", {method:"POST", body:JSON.stringify({ip:iecState.profile.network.ip, port:iecState.profile.network.port})});
      const mms = result.mms.reachable ? `MMS ${result.mms.port}端口可达` : `MMS ${result.mms.port}端口不可达：${result.mms.message}`;
      node.className = `iec-probe-result ${result.mms.reachable ? "ok" : "warn"}`;
      node.textContent = mms;
    } catch (error) { node.className = "iec-probe-result warn"; node.textContent = error.message; }
  }

  function bind() {
    document.querySelectorAll('[data-page="iec61850"]').forEach(node => node.addEventListener("click", loadWorkspace));
    element("iecPointTableBody")?.addEventListener("input", syncRow);
    element("iecPointTableBody")?.addEventListener("change", syncRow);
    element("iecPointSearch")?.addEventListener("input", renderTable);
    ["iecProfileName","iecIedName","iecLogicalDevice","iecPointPrefix","iecStationPrefix","iecIp","iecNetmask","iecGateway","iecPort"]
      .forEach(id => element(id)?.addEventListener("input", renderSummary));
    element("iecSelectAllBtn")?.addEventListener("click", () => { iecState.profile.points.forEach(p => p.enabled = true); renderTable(); });
    element("iecClearBtn")?.addEventListener("click", () => { iecState.profile.points.forEach(p => p.enabled = false); renderTable(); });
    element("iecApplyPrefixBtn")?.addEventListener("click", () => {
      const prefix = element("iecPointPrefix").value.trim();
      iecState.profile.pointPrefix = prefix;
      iecState.profile.points.forEach(point => { const meta = iecState.meta.get(point.pointId); if (meta) point.objectName = `${prefix}${meta.defaultObjectName}`; });
      renderTable();
    });
    element("iecApplyStationPrefixBtn")?.addEventListener("click", () => {
      const prefix = element("iecStationPrefix").value.trim();
      iecState.profile.stationPrefix = prefix;
      iecState.profile.points.forEach(point => { const meta = iecState.meta.get(point.pointId); if (meta) point.stationName = `${prefix}${meta.sourceName}`; });
      renderTable();
    });
    element("iecSaveBtn")?.addEventListener("click", () => saveProfile().catch(error => notify(error.message, "error")));
    element("iecGenerateBtn")?.addEventListener("click", generatePackage);
    element("iecProbeBtn")?.addEventListener("click", probe);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind); else bind();
})();
