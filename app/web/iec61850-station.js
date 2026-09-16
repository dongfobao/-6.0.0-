"use strict";

const stationState = {snapshot:null, selectedId:null, search:"", loaded:false, stream:null};
const stationEl = (id) => document.getElementById(id);

function stationEscape(value){return String(value??"").replace(/[&<>"']/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function stationTime(value){if(!value)return "--";const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString("zh-CN",{hour12:false});}
function stationValue(value){if(typeof value==="number"){if(Number.isInteger(value))return String(value);return value.toFixed(3).replace(/\.?0+$/,"");}if(typeof value==="boolean")return value?"true":"false";return value??"--";}
function stationNotify(message,error=false){if(typeof notify==="function")notify(message,error);else console[error?"error":"log"](message);}
async function stationApi(path,options={}){
  const response=await fetch(path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{})}});
  const payload=await response.json().catch(()=>({error:`HTTP ${response.status}`}));
  if(!response.ok||payload.ok===false)throw new Error(payload.error||`HTTP ${response.status}`);
  return payload;
}
function stationDevices(){return stationState.snapshot?.devices||[];}
function stationSelected(){const devices=stationDevices();return devices.find((d)=>d.id===stationState.selectedId)||devices.find((d)=>d.id===stationState.snapshot?.selectedDeviceId)||devices[0]||null;}

async function stationLoad(){
  try{
    stationState.snapshot=await stationApi("/api/iec61850-station/bootstrap");
    stationState.selectedId=stationState.snapshot.selectedDeviceId||stationDevices()[0]?.id||null;
    stationState.loaded=true;stationRender();stationOpenStream();
  }catch(error){stationNotify(`61850总站加载失败：${error.message}`,true);}
}

function stationOpenStream(){
  if(stationState.stream)return;
  const stream=new EventSource("/api/iec61850-station/stream");
  stream.addEventListener("station",(event)=>{try{const payload=JSON.parse(event.data);if(payload.snapshot){stationState.snapshot=payload.snapshot;if(!stationState.selectedId)stationState.selectedId=payload.snapshot.selectedDeviceId;stationRender();}}catch(error){console.error(error);}});
  stream.onerror=()=>{};stationState.stream=stream;
}

function stationRender(){
  const device=stationSelected();
  stationRenderCards();
  stationEl("stationSelectedName").textContent=device?.displayName||"尚未选择设备";
  stationEl("stationSelectedMeta").textContent=device?`${device.iedName} · ${device.fileName} · ${device.points.length}个点`:`请先导入ICD`;
  stationEl("stationHost").value=device?.host||"";
  stationEl("stationPort").value=device?.port||102;
  stationEl("stationConnectBtn").disabled=!device||device.status==="online"||device.status==="connecting";
  stationEl("stationDisconnectBtn").disabled=!device||!(["online","connecting","error"].includes(device.status));
  stationEl("stationSaveDeviceBtn").disabled=!device;
  stationRenderTree(device);stationRenderPoints(device);stationRenderReports(device);stationRenderEvents();stationRenderComparison(device);
}

function stationRenderCards(){
  const root=stationEl("stationDeviceCards"),devices=stationDevices();
  if(!devices.length){root.innerHTML='<div class="station-empty panel">尚未导入设备ICD。点击右上角“导入ICD”。</div>';return;}
  root.innerHTML=devices.map((device)=>{
    const selected=device.id===stationSelected()?.id;
    const online=Object.values(device.values||{}).filter((v)=>v.ok&&!v.stale).length;
    const reports=Object.values(device.reportStates||{}).filter((v)=>v.status==="enabled").length;
    return `<article class="station-device-card${selected?" selected":""}" data-station-device="${stationEscape(device.id)}"><header><h3>${stationEscape(device.displayName)}</h3><span class="station-status ${stationEscape(device.status)}">${stationEscape(device.statusText||device.status)}</span></header><p>${stationEscape(device.host)}:${stationEscape(device.port)} · ${stationEscape(device.iedName)}</p><dl><div><dt>实时点</dt><dd>${online}/${device.points.length}</dd></div><div><dt>已启用报告</dt><dd>${reports}/${device.rcbs.length}</dd></div><div><dt>最后数据</dt><dd>${stationEscape(stationTime(device.lastSeen))}</dd></div><div><dt>模型</dt><dd>${device.modelComparison?.matched?"匹配":device.onlineModel?"有差异":"待比对"}</dd></div></dl></article>`;
  }).join("");
}

function stationRenderTree(device){
  const root=stationEl("stationModelTree");if(!device){root.innerHTML='<div class="station-empty">无模型</div>';return;}
  const grouped=new Map();
  for(const point of device.points){if(!grouped.has(point.domain))grouped.set(point.domain,new Map());const nodes=grouped.get(point.domain);if(!nodes.has(point.logicalNode))nodes.set(point.logicalNode,[]);nodes.get(point.logicalNode).push(point);}
  root.innerHTML=`<details open><summary><b>${stationEscape(device.iedName)}</b> · ${stationEscape(device.displayName)}</summary>${[...grouped.entries()].map(([domain,nodes])=>`<details open><summary>${stationEscape(domain)}</summary>${[...nodes.entries()].map(([node,points])=>`<details><summary>${stationEscape(node)} <small>${points.length}</small></summary>${points.map((point)=>`<details><summary>${stationEscape(point.dataObject)} · ${stationEscape(point.displayName)}</summary><div class="leaf">${stationEscape(point.reference.split(".").slice(1).join("."))}</div></details>`).join("")}</details>`).join("")}</details>`).join("")}</details>`;
}

function stationRenderPoints(device){
  const body=stationEl("stationPointTableBody");if(!device){body.innerHTML='<tr><td colspan="8" class="station-empty">无测点</td></tr>';stationEl("stationPointCount").textContent="0个点";return;}
  const search=stationState.search.trim().toLowerCase();
  const points=device.points.filter((point)=>!search||`${point.displayName} ${point.reference} ${point.dataset}`.toLowerCase().includes(search));
  stationEl("stationPointCount").textContent=`${points.length}/${device.points.length}个点`;
  body.innerHTML=points.map((point)=>{
    const current=device.values?.[point.reference];
    const ok=current?.ok&&!current?.stale;
    const value=current?.ok?stationValue(current.value):"--";
    const unit=point.unit?` ${stationEscape(point.unit)}`:"";
    const quality=current?.qualityText||current?.quality||((current?.ok)?"good":"未读取");
    const source=current?.source==="report"?"报告":current?.source==="manual"?"手动读取":current?.source==="poll"?"轮询":"--";
    return `<tr><td class="point-name">${stationEscape(point.displayName)}</td><td><code>${stationEscape(point.reference)}</code><small>${stationEscape(point.dataset)}</small></td><td><span class="station-value${current&&!current.ok?" error":""}">${stationEscape(value)}${unit}</span></td><td>${stationEscape(point.fc)}<br><small>${stationEscape(point.bType)}</small></td><td class="${ok?"station-fresh":"station-stale"}">${stationEscape(quality)}${current?.error?`<br><small>错误${stationEscape(current.error)}</small>`:""}</td><td>${stationEscape(stationTime(current?.receivedAt))}</td><td>${stationEscape(source)}</td><td><button class="button small secondary" data-station-read="${stationEscape(point.id)}">读取</button></td></tr>`;
  }).join("")||'<tr><td colspan="8" class="station-empty">没有匹配的测点</td></tr>';
}

function stationRenderReports(device){
  const rcbRoot=stationEl("stationRcbList"),datasetRoot=stationEl("stationDatasetList");
  if(!device){rcbRoot.innerHTML=datasetRoot.innerHTML='<div class="station-empty">无数据</div>';return;}
  rcbRoot.innerHTML=device.rcbs.map((rcb)=>{const state=device.reportStates?.[rcb.reference];return `<article class="station-info-card"><header><h4>${stationEscape(rcb.name)}</h4><span class="station-status ${state?.status==="enabled"?"online":""}">${stationEscape(state?.text||"未启用")}</span></header><p>${stationEscape(rcb.reference)}<br>RptID: ${stationEscape(rcb.rptId)} · 周期 ${stationEscape(rcb.integrityMs)} ms</p><button class="button small primary" data-station-report="${stationEscape(rcb.reference)}" ${device.status!=="online"||state?.status==="enabled"?"disabled":""}>启用并GI</button></article>`;}).join("")||'<div class="station-empty">ICD没有报告控制块</div>';
  datasetRoot.innerHTML=device.datasets.map((dataset)=>`<article class="station-info-card"><header><h4>${stationEscape(dataset.name)}</h4><span>${dataset.members.length}项</span></header><p>${stationEscape(dataset.description||dataset.reference)}</p><div class="station-dataset-members">${dataset.members.map((m,i)=>`${i+1}. ${stationEscape(`${m.lnClass}${m.lnInst}.${m.doName}`)} [${stationEscape(m.fc)}]`).join("<br>")}</div></article>`).join("");
}

function stationRenderEvents(){
  const root=stationEl("stationEventList"),device=stationSelected();const events=(stationState.snapshot?.events||[]).filter((item)=>!device||item.deviceId===device.id);
  root.innerHTML=events.map((event)=>`<article class="station-event ${event.type==="error"?"error":""}"><time>${stationEscape(stationTime(event.at))}</time><span>${stationEscape(event.type)}</span><strong>${stationEscape(event.message)}</strong></article>`).join("")||'<div class="station-empty">暂无事件</div>';
}

function stationRenderComparison(device){
  const root=stationEl("stationCompareResult");if(!device){root.innerHTML='<div class="station-empty">无设备</div>';return;}
  const comparison=device.modelComparison;if(!comparison){root.innerHTML='<div class="station-empty">连接设备后自动比对ICD与在线模型</div>';return;}
  if(comparison.matched){root.innerHTML=`<div class="station-compare-ok"><strong>基础模型匹配</strong><p>ICD中的逻辑设备和逻辑节点均可在在线设备中找到。</p></div>`;return;}
  const groups=[["缺少逻辑设备",comparison.missingLogicalDevices],["设备额外逻辑设备",comparison.extraLogicalDevices],["缺少逻辑节点",comparison.missingLogicalNodes],["设备额外逻辑节点",comparison.extraLogicalNodes]];
  root.innerHTML=`<div class="station-compare-warn"><strong>发现模型差异</strong>${groups.filter(([,v])=>v?.length).map(([name,values])=>`<h4>${stationEscape(name)}</h4><ul>${values.map((value)=>`<li>${stationEscape(value)}</li>`).join("")}</ul>`).join("")}</div>`;
}

async function stationImportFile(file){
  if(!file)return;try{const content=await file.text();await stationApi("/api/iec61850-station/icd/import",{method:"POST",body:JSON.stringify({fileName:file.name,content})});stationNotify(`已导入 ${file.name}`);await stationLoad();}catch(error){stationNotify(`ICD导入失败：${error.message}`,true);}finally{stationEl("stationIcdFile").value="";}
}
async function stationMutation(path,body,success){try{await stationApi(path,{method:"POST",body:JSON.stringify(body)});if(success)stationNotify(success);}catch(error){stationNotify(error.message,true);}}

function stationBind(){
  document.querySelectorAll('[data-page="iec61850station"]').forEach((node)=>node.addEventListener("click",()=>{if(!stationState.loaded)stationLoad();}));
  stationEl("stationImportBtn").addEventListener("click",()=>stationEl("stationIcdFile").click());
  stationEl("stationIcdFile").addEventListener("change",(event)=>stationImportFile(event.target.files?.[0]));
  stationEl("stationRefreshBtn").addEventListener("click",stationLoad);
  stationEl("stationPointSearch").addEventListener("input",(event)=>{stationState.search=event.target.value;stationRenderPoints(stationSelected());});
  stationEl("stationDeviceCards").addEventListener("click",async(event)=>{const card=event.target.closest("[data-station-device]");if(!card)return;stationState.selectedId=card.dataset.stationDevice;await stationMutation("/api/iec61850-station/device/select",{deviceId:stationState.selectedId});stationRender();});
  stationEl("stationSaveDeviceBtn").addEventListener("click",()=>{const device=stationSelected();if(device)stationMutation("/api/iec61850-station/device/update",{deviceId:device.id,host:stationEl("stationHost").value,port:Number(stationEl("stationPort").value)},"设备地址已保存");});
  stationEl("stationConnectBtn").addEventListener("click",()=>{const device=stationSelected();if(device)stationMutation("/api/iec61850-station/device/connect",{deviceId:device.id},"正在连接设备");});
  stationEl("stationDisconnectBtn").addEventListener("click",()=>{const device=stationSelected();if(device)stationMutation("/api/iec61850-station/device/disconnect",{deviceId:device.id},"设备已断开");});
  stationEl("stationPointTableBody").addEventListener("click",(event)=>{const button=event.target.closest("[data-station-read]");const device=stationSelected();const point=device?.points.find((item)=>item.id===button?.dataset.stationRead);if(point)stationMutation("/api/iec61850-station/read",{deviceId:device.id,reference:point.reference,fc:point.fc},"已发送读取请求");});
  stationEl("stationRcbList").addEventListener("click",(event)=>{const button=event.target.closest("[data-station-report]");const device=stationSelected();if(button&&device)stationMutation("/api/iec61850-station/report/subscribe",{deviceId:device.id,reference:button.dataset.stationReport},"正在启用报告并执行GI");});
  document.querySelectorAll("[data-station-tab]").forEach((button)=>button.addEventListener("click",()=>{document.querySelectorAll("[data-station-tab]").forEach((item)=>item.classList.toggle("active",item===button));document.querySelectorAll("[data-station-tab-view]").forEach((item)=>item.classList.toggle("active",item.dataset.stationTabView===button.dataset.stationTab));}));
}

document.addEventListener("DOMContentLoaded",stationBind);
