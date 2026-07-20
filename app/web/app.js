"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  bootstrap: null, devices: [], selectedDeviceId: null, snapshot: null,
  series: { byMetric: {}, rows: [] }, parameters: [], events: [], traffic: [],
  activePage: "overview", refreshTimer: null, trendTimer: null,
  trendQuery: {windowMs: 900000, start: null, end: null}, trendViewport: null, trendDrag: null,
  configModule: "sensor_1",
};

const PAGE_TITLES = {overview:"运行总览",trends:"实时曲线",control:"远程控制",configuration:"参数配置",alarms:"告警事件",diagnostics:"通信诊断",devices:"设备管理"};
const TREND_META = {
  "sensor_1.temperature": ["温度1","#fb923c"], "sensor_2.temperature": ["温度2","#facc15"], "sensor_3.temperature": ["温度3","#f87171"],
  "sensor_1.humidity": ["湿度1","#38bdf8"], "sensor_2.humidity": ["湿度2","#818cf8"], "sensor_3.humidity": ["湿度3","#a78bfa"],
  pressure:["压力","#c084fc"], flow:["流量","#2dd4bf"],
};
const activeTrends = new Set(["sensor_1.temperature","sensor_2.temperature","sensor_3.temperature","sensor_1.humidity","sensor_2.humidity","sensor_3.humidity"]);
const pendingControls = new Set();

async function api(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json",...(options.headers||{})},...options});
  const payload = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}
function esc(value){return String(value??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));}
function fmt(value, digits=2){if(value===null||value===undefined||value==="")return "--";if(typeof value==="number")return Number.isInteger(value)?String(value):value.toFixed(digits);return String(value);}
function pointText(point,digits=2){return `${fmt(point?.displayValue ?? point?.value,digits)}${point?.unit?` ${point.unit}`:""}`;}
function showNotice(message,type="success"){const node=$("notice");node.textContent=message;node.className=`notice ${type}`;clearTimeout(showNotice.timer);showNotice.timer=setTimeout(()=>node.classList.add("hidden"),4500);}
function currentDevice(){return state.devices.find(item=>item.id===state.selectedDeviceId)||null;}

async function bootstrap(){
  state.bootstrap=await api("/api/bootstrap");
  state.devices=state.bootstrap.devices.devices||[];
  state.selectedDeviceId=state.bootstrap.devices.selectedDeviceId || state.devices[0]?.id || null;
  renderDeviceSelector();renderDevices();renderTrendToggles();buildControlButtons();
  await refreshAll();
  clearInterval(state.refreshTimer); state.refreshTimer=setInterval(refreshLive,1000);
  clearInterval(state.trendTimer); state.trendTimer=setInterval(()=>state.activePage==="trends"&&refreshSeries(),5000);
}

function renderDeviceSelector(){
  $("deviceSelect").innerHTML=state.devices.length?state.devices.map(d=>`<option value="${esc(d.id)}" ${d.id===state.selectedDeviceId?"selected":""}>${esc(d.name)} · ${esc(d.address)} / ${d.slaveId}</option>`).join(""):`<option value="">请先添加设备</option>`;
}

async function refreshAll(){await Promise.allSettled([refreshLive(),refreshParameters(),refreshEvents(),refreshTraffic(),refreshSeries()]);}
async function refreshLive(){
  if(!state.selectedDeviceId){renderEmptySnapshot();return;}
  try{
    state.snapshot=await api(`/api/monitor/snapshot?deviceId=${encodeURIComponent(state.selectedDeviceId)}`);
    renderSnapshot();
    const status=await api("/api/acquisition/status"); renderAcquisitionStatus(status);
  }catch(error){setConnection("error",error.message);}
}
function setConnection(kind,text){const badge=$("connectionBadge");badge.className=`status-badge ${kind||"idle"}`;badge.querySelector("span").textContent=text||"待采集";}
function renderAcquisitionStatus(payload){
  const status=payload.devices?.[state.selectedDeviceId];
  setConnection(status?.communication_health||"idle",status?.communication_text||"待采集");
  $("startBtn").disabled=Boolean(status?.running); $("stopBtn").disabled=!payload.global?.running;
}
function renderEmptySnapshot(){state.snapshot=null;["pressureValue","flowValue"].forEach(id=>$(id).textContent="--");$("sensorCards").innerHTML=$("outputCards").innerHTML=$("valveCards").innerHTML='<div class="empty-state">请先添加并选择设备</div>';setConnection("idle","待配置");}
function renderSnapshot(){
  const s=state.snapshot;if(!s)return renderEmptySnapshot();
  $("pressureValue").textContent=fmt(s.process.pressure.value);$("flowValue").textContent=fmt(s.process.flow.value);
  $("pressureStatus").textContent=`状态 ${fmt(s.process.pressureStatus.displayValue)}`;$("breathState").textContent=`呼吸状态 ${fmt(s.process.breathState.displayValue)}`;
  $("sensorCards").innerHTML=s.environmentChannels.map(ch=>`<article class="sensor-card"><div class="card-head"><h3>温湿度 ${ch.channel}</h3><span class="quality-dot ${ch.readOk.value?"ok":""}">${ch.readOk.value?"通信正常":"无有效数据"}</span></div><div class="sensor-values"><div class="sensor-value"><span>温度</span><strong>${fmt(ch.temperature.value)} <small>°C</small></strong></div><div class="sensor-value"><span>湿度</span><strong>${fmt(ch.humidity.value)} <small>%RH</small></strong></div></div><div class="output-meta"><span>传感器状态</span><strong>${fmt(ch.status.displayValue)}</strong></div></article>`).join("");
  $("outputCards").innerHTML=s.outputs.map(out=>`<article class="output-card"><div class="card-head"><strong>${esc(out.name)}</strong><span class="state-pill ${Number(out.state.value)===1?"on":""}">${esc(fmt(out.state.displayValue))}</span></div><div class="output-meta"><span>模式 ${esc(fmt(out.mode?.displayValue))}</span><span>${out.count?`累计 ${esc(fmt(out.count.value,0))} 次`:""}</span></div></article>`).join("");
  $("valveCards").innerHTML=s.valves.map(v=>`<article class="valve-card"><div class="valve-row"><strong>${esc(v.name)}</strong><div><span>显示状态</span><br>${esc(fmt(v.displayState.displayValue))}</div><div><span>执行状态</span><br>${esc(fmt(v.actuatorState.displayValue))}</div><div><span>位置 / 电流</span><br>${fmt(v.position.value,0)}% / ${fmt(v.currentAdc.value,0)}</div></div><div class="output-meta"><span>控制源 ${esc(fmt(v.controlSource.displayValue))}</span><span class="${Number(v.faultReason.value)?"state-pill fault":""}">故障 ${fmt(v.faultReason.value,0)}</span></div></article>`).join("");
  renderValveControls(s.runtimeValves || []);renderAlarmSummary();renderDiagnostics();
}

const TREND_PRESETS={environment:["sensor_1.temperature","sensor_1.humidity","sensor_2.temperature","sensor_2.humidity","sensor_3.temperature","sensor_3.humidity"],process:["pressure","flow"],all:Object.keys(TREND_META)};
function renderTrendToggles(){
  $("trendToggles").innerHTML=Object.entries(TREND_META).map(([key,[label,color]])=>`<label class="trend-toggle"><input type="checkbox" data-trend="${key}" ${activeTrends.has(key)?"checked":""}><i style="width:8px;height:8px;border-radius:50%;background:${color}"></i>${label}</label>`).join("");
  document.querySelectorAll("[data-trend]").forEach(input=>input.addEventListener("change",()=>{input.checked?activeTrends.add(input.dataset.trend):activeTrends.delete(input.dataset.trend);state.trendViewport=null;drawTrendChart();renderTrendLatest();}));
  document.querySelectorAll("[data-trend-preset]").forEach(button=>button.addEventListener("click",()=>{activeTrends.clear();(TREND_PRESETS[button.dataset.trendPreset]||[]).forEach(key=>activeTrends.add(key));state.trendViewport=null;renderTrendToggles();drawTrendChart();renderTrendLatest();}));
}
function formatTrendInput(value){if(!value)return "";const date=new Date(value);if(!Number.isFinite(date.getTime()))return "";const offset=date.getTimezoneOffset()*60000;return new Date(date.getTime()-offset).toISOString().slice(0,16);}
function selectedTrendRows(){return [...activeTrends].map(key=>({key,rows:(state.series.byMetric?.[key]||[]).map(row=>({...row,epoch:new Date(row.ts).getTime()})).filter(row=>Number.isFinite(row.epoch)&&Number.isFinite(Number(row.value))),meta:TREND_META[key]})).filter(item=>item.rows.length);}
function trendBounds(series){const all=series.flatMap(item=>item.rows);if(!all.length)return null;const start=Math.min(...all.map(row=>row.epoch)),end=Math.max(...all.map(row=>row.epoch));return {start,end:end===start?start+1000:end};}
function clampTrendViewport(viewport,bounds){if(!viewport||!bounds)return bounds;const full=bounds.end-bounds.start,span=Math.max(1000,Math.min(full,viewport.end-viewport.start));const start=Math.max(bounds.start,Math.min(bounds.end-span,viewport.start));return {start,end:start+span};}
function applyTrendWindow(windowMs){state.trendQuery={windowMs,start:null,end:null};state.trendViewport=null;$("trendStart").value="";$("trendEnd").value="";$("trendWindow").value=String(windowMs);refreshSeries();}
async function refreshSeries(){if(!state.selectedDeviceId)return;try{const query=new URLSearchParams({deviceId:state.selectedDeviceId,windowMs:String(state.trendQuery.windowMs),limit:"2000"});if(state.trendQuery.start)query.set("start",state.trendQuery.start);if(state.trendQuery.end)query.set("end",state.trendQuery.end);state.series=await api(`/api/monitor/series?${query}`);drawTrendChart();renderTrendLatest();renderTrendRangeText();}catch(error){showNotice(error.message,"error");}}
function renderTrendRangeText(){const all=trendBounds(selectedTrendRows());const range=state.trendQuery.start||state.trendQuery.end?`${state.trendQuery.start||"最早"} 至 ${state.trendQuery.end||"现在"}`:`最近 ${Math.round(state.trendQuery.windowMs/60000)} 分钟`;$("trendRangeText").textContent=all?`${range} · 已加载 ${all.start===all.end?0:Math.round((all.end-all.start)/1000)} 秒数据`:`${range} · 暂无数据`;}
function drawTrendChart(){
  const canvas=$("trendCanvas"),host=canvas.parentElement,dpr=window.devicePixelRatio||1,width=Math.max(1,host.clientWidth-28),height=Math.max(1,host.clientHeight-28),ctx=canvas.getContext("2d");canvas.width=width*dpr;canvas.height=height*dpr;canvas.style.width=`${width}px`;canvas.style.height=`${height}px`;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const series=selectedTrendRows(),bounds=trendBounds(series);$("chartEmpty").classList.toggle("hidden",Boolean(bounds));if(!bounds)return;
  const viewport=clampTrendViewport(state.trendViewport||bounds,bounds);state.trendViewport=viewport;const pad={l:54,r:20,t:36,b:38},plotW=width-pad.l-pad.r,plotH=height-pad.t-pad.b,xFor=epoch=>pad.l+(epoch-viewport.start)/(viewport.end-viewport.start)*plotW;
  ctx.strokeStyle="#21364d";ctx.fillStyle="#8ca2b7";ctx.font="11px Segoe UI";ctx.lineWidth=1;
  for(let i=0;i<=5;i++){const y=pad.t+plotH*i/5;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke();}
  for(let i=0;i<=6;i++){const x=pad.l+plotW*i/6;ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,height-pad.b);ctx.stroke();const time=new Date(viewport.start+(viewport.end-viewport.start)*i/6).toLocaleTimeString("zh-CN",{hour12:false,hour:"2-digit",minute:"2-digit",second:"2-digit"});ctx.fillText(time,x-25,height-11);}
  series.forEach((item,index)=>{const visible=item.rows.filter(row=>row.epoch>=viewport.start&&row.epoch<=viewport.end);if(!visible.length)return;let low=Math.min(...visible.map(row=>Number(row.value))),high=Math.max(...visible.map(row=>Number(row.value)));if(low===high){low-=1;high+=1;}const margin=(high-low)*.08;low-=margin;high+=margin;const yFor=value=>pad.t+(high-value)/(high-low)*plotH;ctx.strokeStyle=item.meta[1];ctx.lineWidth=2;ctx.beginPath();visible.forEach((row,rowIndex)=>{const x=xFor(row.epoch),y=yFor(Number(row.value));rowIndex?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.fillStyle=item.meta[1];ctx.fillText(`${item.meta[0]} ${low.toFixed(1)}–${high.toFixed(1)}`,pad.l+index*118,pad.t-15);});
  if(state.trendHover&&state.trendHover.epoch>=viewport.start&&state.trendHover.epoch<=viewport.end){const x=xFor(state.trendHover.epoch);ctx.strokeStyle="rgba(232,241,248,.55)";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,height-pad.b);ctx.stroke();ctx.setLineDash([]);}
}
function renderTrendLatest(){$("trendLatest").innerHTML=[...activeTrends].map(key=>{const rows=state.series.byMetric?.[key]||[],last=rows.at(-1),numeric=rows.map(row=>Number(row.value)).filter(Number.isFinite),minimum=numeric.length?Math.min(...numeric):null,maximum=numeric.length?Math.max(...numeric):null,average=numeric.length?numeric.reduce((sum,value)=>sum+value,0)/numeric.length:null;return `<div class="latest-item"><span>${TREND_META[key]?.[0]||key}</span><strong>${fmt(last?.value)}</strong><small>最小 ${fmt(minimum)} · 最大 ${fmt(maximum)} · 均值 ${fmt(average)}</small></div>`;}).join("");}
function ensureTrendTooltip(){let tooltip=$("trendTooltip");if(!tooltip){tooltip=document.createElement("div");tooltip.id="trendTooltip";tooltip.className="trend-tooltip hidden";$("trendCanvas").parentElement.appendChild(tooltip);}return tooltip;}
function showTrendTooltip(event){const series=selectedTrendRows(),bounds=trendBounds(series),canvas=$("trendCanvas");if(!bounds)return;const rect=canvas.getBoundingClientRect(),pad={l:54,r:20},plotW=rect.width-pad.l-pad.r,x=Math.max(pad.l,Math.min(rect.width-pad.r,event.clientX-rect.left)),viewport=state.trendViewport||bounds,target=viewport.start+(x-pad.l)/plotW*(viewport.end-viewport.start);let nearest=null;series.forEach(item=>item.rows.forEach(row=>{if(!nearest||Math.abs(row.epoch-target)<Math.abs(nearest.epoch-target))nearest=row;}));if(!nearest)return;state.trendHover=nearest;const values=series.map(item=>{const row=item.rows.reduce((best,current)=>!best||Math.abs(current.epoch-nearest.epoch)<Math.abs(best.epoch-nearest.epoch)?current:best,null);return `<div><i style="background:${item.meta[1]}"></i>${item.meta[0]} <strong>${fmt(row?.value)}</strong></div>`;}).join("");const tooltip=ensureTrendTooltip();tooltip.innerHTML=`<time>${new Date(nearest.epoch).toLocaleString("zh-CN",{hour12:false})}</time>${values}`;tooltip.style.left=`${Math.min(rect.width-205,Math.max(12,event.clientX-rect.left+14))}px`;tooltip.style.top=`${Math.max(12,event.clientY-rect.top+14)}px`;tooltip.classList.remove("hidden");drawTrendChart();}
function setupTrendInteractions(){const canvas=$("trendCanvas");canvas.addEventListener("wheel",event=>{event.preventDefault();const bounds=trendBounds(selectedTrendRows());if(!bounds)return;const rect=canvas.getBoundingClientRect(),pad={l:54,r:20},fraction=Math.max(0,Math.min(1,(event.clientX-rect.left-pad.l)/(rect.width-pad.l-pad.r))),view=state.trendViewport||bounds,span=view.end-view.start,nextSpan=Math.max(1000,Math.min(bounds.end-bounds.start,span*(event.deltaY<0?.72:1.38))),anchor=view.start+span*fraction;state.trendViewport=clampTrendViewport({start:anchor-nextSpan*fraction,end:anchor+nextSpan*(1-fraction)},bounds);drawTrendChart();},{passive:false});canvas.addEventListener("pointerdown",event=>{canvas.setPointerCapture(event.pointerId);state.trendDrag={x:event.clientX,viewport:state.trendViewport};});canvas.addEventListener("pointermove",event=>{if(!state.trendDrag){showTrendTooltip(event);return;}const bounds=trendBounds(selectedTrendRows());if(!bounds)return;const rect=canvas.getBoundingClientRect(),view=state.trendDrag.viewport||bounds,shift=-(event.clientX-state.trendDrag.x)/(rect.width-74)*(view.end-view.start);state.trendViewport=clampTrendViewport({start:view.start+shift,end:view.end+shift},bounds);drawTrendChart();});canvas.addEventListener("pointerup",event=>{state.trendDrag=null;try{canvas.releasePointerCapture(event.pointerId);}catch(_){}});canvas.addEventListener("pointerleave",()=>{if(!state.trendDrag){state.trendHover=null;ensureTrendTooltip().classList.add("hidden");drawTrendChart();}});}
function zoomTrend(factor){const bounds=trendBounds(selectedTrendRows());if(!bounds)return;const view=state.trendViewport||bounds,span=(view.end-view.start)*factor,mid=(view.start+view.end)/2;state.trendViewport=clampTrendViewport({start:mid-span/2,end:mid+span/2},bounds);drawTrendChart();}
function exportTrendCsv(){const keys=[...activeTrends],timestamps=[...new Set(keys.flatMap(key=>(state.series.byMetric?.[key]||[]).map(row=>row.ts)))].sort(),byTimestamp=new Map(timestamps.map(ts=>[ts,{ts}]));keys.forEach(key=>(state.series.byMetric?.[key]||[]).forEach(row=>{byTimestamp.get(row.ts)[key]=row.value;}));const header=["时间",...keys.map(key=>TREND_META[key]?.[0]||key)],csv=[header,...timestamps.map(ts=>[ts,...keys.map(key=>byTimestamp.get(ts)[key]??"")])].map(row=>row.map(value=>`"${String(value).replaceAll('"','""')}"`).join(",")).join("\r\n");const blob=new Blob(["\uFEFF",csv],{type:"text/csv;charset=utf-8"}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=`YLDQ_曲线_${new Date().toISOString().slice(0,19).replaceAll(':','-')}.csv`;link.click();URL.revokeObjectURL(link.href);}

function buildControlButtons(){
  document.querySelectorAll("[data-mode-control]").forEach(host=>{host.innerHTML=[[0,"自动"],[1,"强制关"],[2,"强制开"]].map(([v,t])=>`<button data-control="${host.dataset.modeControl}" data-value="${v}">${t}</button>`).join("");});
  document.querySelectorAll("[data-control]").forEach(button=>button.addEventListener("click",()=>writeControl(button.dataset.control,Number(button.dataset.value))));
  renderValveControls();
}
function renderValveControls(runtimeValves=[]){
  const fallbackNames=["上阀","左阀","右阀"], byChannel=new Map(runtimeValves.map(item=>[Number(item.channel),item]));
  $("valveControls").innerHTML=[1,2,3].map(channel=>{
    const valve=byChannel.get(channel)||{}, command=Number(valve.command?.value ?? 0), fault=Number(valve.faultReason?.value ?? 0), pending=pendingControls.has(`holding.runtime.valve_${channel}`);
    const faultText=valve.faultReason?.displayValue || (fault?`故障 ${fault}`:"无故障"), source=valve.effectiveSource?.displayValue || "--", seconds=valve.remoteSeconds?.value;
    const detail=fault===8?"开路：请检查阀门线圈、接线端子及驱动输出。":"";
    return `<article class="panel control-card valve-control-card ${fault?"has-fault":""}"><h3>${esc(valve.name||fallbackNames[channel-1])}</h3><p>三选一远程命令；每次写入均回读下位机确认。</p><div class="segmented">${[[0,"释放"],[1,"原位"],[2,"工作位"]].map(([value,label])=>`<button data-control="holding.runtime.valve_${channel}" data-value="${value}" class="${command===value?"selected":""}" ${pending||(fault&&value!==0)?"disabled":""}>${label}</button>`).join("")}</div><div class="valve-control-status ${fault?"fault":""}"><span>当前选定：${esc(valve.command?.displayValue||"--")}</span><span>生效源：${esc(source)}</span><span>远程剩余：${seconds===undefined||seconds===null?"--":`${fmt(seconds,0)} 秒`}</span><strong>${esc(faultText)}${detail?`；${esc(detail)}`:""}</strong></div></article>`;
  }).join("");
  document.querySelectorAll("[data-control^='holding.runtime.valve_']").forEach(button=>button.addEventListener("click",()=>writeControl(button.dataset.control,Number(button.dataset.value))));
}
async function writeControl(itemId,value){
  if(!state.selectedDeviceId)return showNotice("请先选择设备","error");
  if(pendingControls.has(itemId))return;
  pendingControls.add(itemId);renderValveControls(state.snapshot?.runtimeValves||[]);
  try{
    const result=await api("/api/control/write",{method:"POST",body:JSON.stringify({deviceId:state.selectedDeviceId,itemId,value})});
    const confirmed=result.runtimeFeedback?.[itemId];
    showNotice(confirmed===undefined?"命令已发送":`命令已确认：${result.item?.displayValue||value}`);
    await refreshLive();
  }catch(error){showNotice(error.message,"error");}
  finally{pendingControls.delete(itemId);renderValveControls(state.snapshot?.runtimeValves||[]);}
}

async function refreshParameters(){if(!state.selectedDeviceId){state.parameters=[];return renderConfigTable();}try{const payload=await api(`/api/config/parameters?deviceId=${encodeURIComponent(state.selectedDeviceId)}`);state.parameters=payload.config||[];renderConfigGroups();renderConfigTable();}catch(error){showNotice(error.message,"error");}}
const CONFIG_MODULES=[
  ["sensor_1","温湿度 1"],["sensor_2","温湿度 2"],["sensor_3","温湿度 3"],
  ["pressure","压力传感器"],["flow","流量与呼吸"],["valve","阀门与路由"],
  ["control","控制策略"],["output","输出设置"],["alarm","告警设置"],
  ["logging","数据记录"],["communication","通信设置"],
];
function configSection(item){const section=String(item.id||"").split(".")[1]||"other";return section.startsWith("valve_")?"valve":section;}
function renderConfigGroups(){
  const available=new Set(state.parameters.map(configSection));
  if(state.configModule&& !available.has(state.configModule))state.configModule="";
  $("configModules").innerHTML=`<button class="config-module ${state.configModule===""?"selected":""}" data-config-module="">全部</button>`+CONFIG_MODULES.filter(([key])=>available.has(key)).map(([key,label])=>`<button class="config-module ${state.configModule===key?"selected":""}" data-config-module="${key}">${label}</button>`).join("");
  document.querySelectorAll("[data-config-module]").forEach(button=>button.addEventListener("click",()=>{state.configModule=button.dataset.configModule;renderConfigGroups();renderConfigTable();}));
}
function renderConfigTable(){
  const search=$("configSearch")?.value.trim().toLowerCase()||"", group=state.configModule;const rows=state.parameters.filter(item=>(!group||configSection(item)===group)&&(!search||`${item.name} ${item.id}`.toLowerCase().includes(search)));
  $("configTableBody").innerHTML=rows.length?rows.map(item=>`<tr><td><strong>${esc(item.name)}</strong><br><code>${esc(item.id)}</code>${configRange(item)}</td><td>HR ${item.address}${item.addressEnd!==item.address?`–${item.addressEnd}`:""}</td><td>${configEditor(item)}</td><td>${esc(item.unit||"")}</td><td><button class="button small secondary" data-stage-item="${esc(item.id)}">暂存</button></td></tr>`).join(""):'<tr><td colspan="5" class="empty-state">没有匹配参数</td></tr>';
  document.querySelectorAll("[data-stage-item]").forEach(btn=>btn.addEventListener("click",()=>stageConfig(btn.dataset.stageItem)));
}
function configEditor(item){const value=item.currentValue??"",unknown=item.currentValue===null||item.currentValue===undefined;if(item.dataType==="bool")return `<select class="config-input" data-config-value="${esc(item.id)}"><option value="" disabled ${unknown?"selected":""}>未读取</option><option value="1" ${value===true||value===1?"selected":""}>启用</option><option value="0" ${value===false||value===0?"selected":""}>关闭</option></select>`;if(item.enumValues&&Object.keys(item.enumValues).length)return `<select class="config-input" data-config-value="${esc(item.id)}"><option value="" disabled ${unknown?"selected":""}>未读取</option>${Object.entries(item.enumValues).map(([v,t])=>`<option value="${v}" ${String(value)===String(v)?"selected":""}>${esc(t)} (${v})</option>`).join("")}</select>`;const min=item.minimum!==undefined?` min="${item.minimum}"`:"",max=item.maximum!==undefined?` max="${item.maximum}"`:"",step=item.step??(item.dataType==='float32'?'0.01':'1');return `<input class="config-input" data-config-value="${esc(item.id)}" type="number" step="${step}"${min}${max} value="${esc(value)}" placeholder="未读取">`;}
function configRange(item){if(item.minimum===undefined&&item.maximum===undefined)return "";const unit=esc(item.unit||"");return `<br><small>允许范围：${item.minimum??"−∞"}–${item.maximum??"∞"}${unit}</small>`;}
async function stageConfig(itemId){const input=document.querySelector(`[data-config-value="${CSS.escape(itemId)}"]`);if(!input)return;if(input.validity&&!input.checkValidity())return showNotice(input.validationMessage||"参数超出允许范围","error");try{await api("/api/config/stage",{method:"POST",body:JSON.stringify({deviceId:state.selectedDeviceId,itemId,value:input.value})});showNotice("参数已暂存并回读成功");await refreshParameters();}catch(error){showNotice(error.message,"error");}}
async function configAction(action){try{const result=await api("/api/config/transaction",{method:"POST",body:JSON.stringify({deviceId:state.selectedDeviceId,action})});showNotice(action==="commit"?`配置提交成功，代次 ${result.status.generation}`:"已放弃暂存配置");await refreshParameters();}catch(error){showNotice(error.message,"error");}}

function renderAlarmSummary(){const a=state.snapshot?.alarms;if(!a)return;$("alarmSummary").innerHTML=(a.groups||[]).map((g,i)=>`<article class="alarm-card ${Number(g.value)?"active":""}"><span>告警组 ${i}</span><strong>0x${Number(g.value||0).toString(16).padStart(8,"0").toUpperCase()}</strong><small>${Number(g.value)?"存在活动告警":"无告警"}</small></article>`).join("");}
async function refreshEvents(){if(!state.selectedDeviceId)return;try{state.events=(await api(`/api/monitor/events?deviceId=${encodeURIComponent(state.selectedDeviceId)}&limit=120`)).items||[];renderEvents();}catch(error){showNotice(error.message,"error");}}
function renderEvents(){$("eventList").innerHTML=state.events.length?[...state.events].reverse().map(e=>`<div class="event-item"><time>${esc(e.ts||"")}</time><span>${esc(e.type||"")}</span><strong>${esc(e.message||"")}</strong></div>`).join(""):'<div class="empty-state">暂无事件</div>';}
async function refreshTraffic(){try{state.traffic=(await api(`/api/monitor/traffic?deviceId=${encodeURIComponent(state.selectedDeviceId||"")}&limit=200`)).items||[];renderTraffic();}catch(error){showNotice(error.message,"error");}}
function renderTraffic(){$("trafficTableBody").innerHTML=state.traffic.length?[...state.traffic].reverse().map(r=>`<tr><td>${esc(r.sentAt||"")}</td><td>${esc(r.deviceName||r.deviceId||"")}</td><td><code>${esc(r.requestHex||"")}</code></td><td><code>${esc(r.responseHex||"")}</code></td><td><span class="state-pill ${r.status==='ok'?'ok':r.status==='error'?'fault':''}">${esc(r.status||"")}</span></td><td>${esc(r.error||"")}</td></tr>`).join(""):'<tr><td colspan="6" class="empty-state">暂无通信记录</td></tr>';}
function renderDiagnostics(){const c=state.snapshot?.communication,s=state.snapshot?.session;if(!c)return;$("diagnosticStats").innerHTML=[["通信健康",c.text,""],["连续失败",fmt(c.failureCount.value,0),"次"],["请求总数",fmt(s?.request_count,0),"次"],["最近成功",s?.last_success_at||"--",""]].map(([name,value,unit])=>`<article class="hero-card"><span>${name}</span><strong>${esc(value)}</strong><em>${unit}</em></article>`).join("");}

function renderDevices(){const selected=state.selectedDeviceId;$("deviceCards").innerHTML=state.devices.length?state.devices.map(d=>`<article class="device-card ${d.id===selected?"selected":""}"><div class="card-head"><h3>${esc(d.name)}</h3><span class="state-pill ${d.enabled?'ok':''}">${d.enabled?'已启用':'已禁用'}</span></div><div class="device-meta"><span>端口</span><strong>${esc(d.address)}</strong><span>从站</span><strong>${d.slaveId}</strong><span>串口</span><strong>${d.baudrate} ${d.parity}81</strong><span>协议</span><strong>V7 RTU</strong></div><div class="device-actions"><button class="button small primary" data-select-device="${esc(d.id)}">选择</button><button class="button small secondary" data-edit-device="${esc(d.id)}">编辑</button><button class="button small danger ghost" data-delete-device="${esc(d.id)}">删除</button></div></article>`).join(""):'<div class="empty-state panel">暂无设备，点击“添加设备”开始配置。</div>';
  document.querySelectorAll("[data-select-device]").forEach(b=>b.addEventListener("click",()=>selectDevice(b.dataset.selectDevice)));
  document.querySelectorAll("[data-edit-device]").forEach(b=>b.addEventListener("click",()=>openDeviceDialog(state.devices.find(d=>d.id===b.dataset.editDevice))));
  document.querySelectorAll("[data-delete-device]").forEach(b=>b.addEventListener("click",()=>deleteDevice(b.dataset.deleteDevice)));
}
function openDeviceDialog(device=null){$("deviceDialogTitle").textContent=device?"编辑设备":"添加设备";$("deviceId").value=device?.id||"";$("deviceName").value=device?.name||"";renderPortOptions(device?.address||"COM1");$("deviceSlave").value=device?.slaveId||1;$("deviceBaud").value=device?.baudrate||9600;$("deviceParity").value=device?.parity||"N";$("deviceTimeout").value=device?.timeoutMs||1200;$("deviceEnabled").checked=device?.enabled??true;$("deviceDialog").showModal();}
function renderPortOptions(selected){const ports=state.bootstrap?.serialPorts||[];const values=[...new Set([selected,...ports.map(p=>p.device)].filter(Boolean))];$("devicePort").innerHTML=values.length?values.map(p=>`<option value="${esc(p)}" ${p===selected?"selected":""}>${esc(p)} ${esc(ports.find(x=>x.device===p)?.description||"")}</option>`).join(""):`<option value="COM1">COM1</option>`;}
async function saveDevice(event){event.preventDefault();const id=$("deviceId").value;const payload={name:$("deviceName").value,address:$("devicePort").value,slaveId:Number($("deviceSlave").value),baudrate:Number($("deviceBaud").value),parity:$("deviceParity").value,timeoutMs:Number($("deviceTimeout").value),enabled:$("deviceEnabled").checked};try{const result=await api(id?`/api/devices/${encodeURIComponent(id)}`:"/api/devices",{method:id?"PUT":"POST",body:JSON.stringify(payload)});$("deviceDialog").close();await reloadDevices(result.id||id);showNotice("设备配置已保存");}catch(error){showNotice(error.message,"error");}}
async function reloadDevices(preferred=null){const payload=await api("/api/devices");state.devices=payload.devices||[];state.selectedDeviceId=preferred||payload.selectedDeviceId||state.devices[0]?.id||null;renderDeviceSelector();renderDevices();await refreshAll();}
async function selectDevice(id){await api(`/api/devices/${encodeURIComponent(id)}/select`,{method:"POST",body:"{}"});state.selectedDeviceId=id;renderDeviceSelector();renderDevices();await refreshAll();}
async function deleteDevice(id){if(!confirm("确定删除该设备配置？"))return;try{await api(`/api/devices/${encodeURIComponent(id)}`,{method:"DELETE"});await reloadDevices();showNotice("设备已删除");}catch(error){showNotice(error.message,"error");}}

async function startMonitoring(){if(!state.selectedDeviceId)return showNotice("请先添加设备","error");try{await api("/api/acquisition/start",{method:"POST",body:JSON.stringify({deviceIds:[state.selectedDeviceId]})});showNotice("监控已启动");await refreshAll();}catch(error){showNotice(error.message,"error");}}
async function stopMonitoring(){try{await api("/api/acquisition/stop",{method:"POST",body:"{}"});showNotice("监控已停止");await refreshLive();}catch(error){showNotice(error.message,"error");}}
function switchPage(page){state.activePage=page;document.querySelectorAll(".nav-item").forEach(n=>n.classList.toggle("active",n.dataset.page===page));document.querySelectorAll(".page").forEach(n=>n.classList.toggle("active",n.dataset.pageView===page));$("pageTitle").textContent=PAGE_TITLES[page];if(page==="trends")refreshSeries();if(page==="configuration")refreshParameters();if(page==="alarms")refreshEvents();if(page==="diagnostics")refreshTraffic();}

function bind(){
  document.querySelectorAll(".nav-item").forEach(n=>n.addEventListener("click",()=>switchPage(n.dataset.page)));
  $("deviceSelect").addEventListener("change",()=>selectDevice($("deviceSelect").value));$("startBtn").addEventListener("click",startMonitoring);$("stopBtn").addEventListener("click",stopMonitoring);
  $("refreshTrendBtn").addEventListener("click",refreshSeries);$("trendWindow").addEventListener("change",()=>applyTrendWindow(Number($("trendWindow").value)));document.querySelectorAll("[data-trend-window]").forEach(button=>button.addEventListener("click",()=>applyTrendWindow(Number(button.dataset.trendWindow))));$("applyTrendRangeBtn").addEventListener("click",()=>{const start=$("trendStart").value,end=$("trendEnd").value;if(!start||!end)return showNotice("请选择完整的开始和结束时间","error");if(new Date(end)<new Date(start))return showNotice("结束时间不能早于开始时间","error");state.trendQuery={windowMs:state.trendQuery.windowMs,start:start.replace("T"," "),end:end.replace("T"," ")};state.trendViewport=null;refreshSeries();});$("zoomInTrendBtn").addEventListener("click",()=>zoomTrend(.65));$("zoomOutTrendBtn").addEventListener("click",()=>zoomTrend(1.55));$("resetTrendZoomBtn").addEventListener("click",()=>{state.trendViewport=null;drawTrendChart();});$("exportTrendBtn").addEventListener("click",exportTrendCsv);setupTrendInteractions();window.addEventListener("resize",()=>state.activePage==="trends"&&drawTrendChart());
  $("resetAllValvesBtn").addEventListener("click",()=>writeControl("holding.runtime.reset",7));
  $("refreshConfigBtn").addEventListener("click",async()=>{try{await api("/api/config/refresh",{method:"POST",body:JSON.stringify({deviceId:state.selectedDeviceId})});await refreshParameters();showNotice("参数读取完成");}catch(e){showNotice(e.message,"error");}});
  $("commitConfigBtn").addEventListener("click",()=>configAction("commit"));$("discardConfigBtn").addEventListener("click",()=>configAction("discard"));$("configSearch").addEventListener("input",renderConfigTable);
  $("refreshEventsBtn").addEventListener("click",refreshEvents);$("refreshTrafficBtn").addEventListener("click",refreshTraffic);$("clearTrafficBtn").addEventListener("click",async()=>{await api("/api/traffic/clear",{method:"POST",body:"{}"});await refreshTraffic();});
  $("addDeviceBtn").addEventListener("click",()=>openDeviceDialog());$("closeDeviceDialog").addEventListener("click",()=>$("deviceDialog").close());$("cancelDeviceBtn").addEventListener("click",()=>$("deviceDialog").close());$("deviceForm").addEventListener("submit",saveDevice);
  setInterval(()=>$("clockText").textContent=new Date().toLocaleString("zh-CN",{hour12:false}),1000);
}

bind();bootstrap().catch(error=>showNotice(`系统初始化失败：${error.message}`,"error"));
