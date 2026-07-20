"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  bootstrap: null, devices: [], selectedDeviceId: null, snapshot: null,
  series: { byMetric: {}, rows: [] }, parameters: [], events: [], traffic: [], trafficLoading: false,
  activePage: "overview", refreshTimer: null, trendTimer: null,
  trendQuery: {windowMs: 900000, start: null, end: null}, trendViewport: null, trendViewportHistory: [], trendDrag: null, trendSelectionDraft: null, trendShowLabels: false, trendShowKeyPoints: true, trendShowEvents: true, trendYScale: 1,
  configModule: "sensor_1",
};

const PAGE_TITLES = {overview:"运行总览",trends:"实时曲线",control:"远程控制",configuration:"参数配置",alarms:"告警事件",diagnostics:"通信诊断",devices:"设备管理"};
const TREND_META = {
  "sensor_1.temperature": ["温度1","#fb923c","°C"], "sensor_2.temperature": ["温度2","#facc15","°C"], "sensor_3.temperature": ["温度3","#f87171","°C"],
  "sensor_1.humidity": ["湿度1","#38bdf8","%RH"], "sensor_2.humidity": ["湿度2","#818cf8","%RH"], "sensor_3.humidity": ["湿度3","#a78bfa","%RH"],
  pressure:["压力","#c084fc","kPa"], flow:["流量","#2dd4bf","L/min"],
};
const activeTrends = new Set(["sensor_1.temperature","sensor_2.temperature","sensor_3.temperature","sensor_1.humidity","sensor_2.humidity","sensor_3.humidity"]);
const pendingControls = new Set();
const HEAT_MODE_CONTROLS = [
  {itemId:"holding.runtime.htc1_mode",outputKey:"htc1"},
  {itemId:"holding.runtime.htc2_mode",outputKey:"htc2"},
  {itemId:"holding.runtime.antifreeze_mode",outputKey:"antifreeze"},
];

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
  $("sensorCards").innerHTML=s.environmentChannels.map(ch=>`<article class="sensor-card ${ch.readOk.value?"is-online":"is-offline"}"><div class="sensor-card-head"><div><span class="sensor-index">0${ch.channel}</span><h3>温湿度 ${ch.channel}</h3></div><span class="quality-dot ${ch.readOk.value?"ok":""}">${ch.readOk.value?"通信正常":"无有效数据"}</span></div><div class="sensor-values"><div class="sensor-value temperature"><span>温度</span><div><strong>${fmt(ch.temperature.value)}</strong><small>°C</small></div></div><div class="sensor-value humidity"><span>湿度</span><div><strong>${fmt(ch.humidity.value)}</strong><small>%RH</small></div></div></div><div class="sensor-card-foot"><span>传感器状态</span><strong>${esc(fmt(ch.status.displayValue))}</strong></div></article>`).join("");
  $("outputCards").innerHTML=s.outputs.map(out=>`<article class="output-card ${Number(out.state.value)===1?"is-active":""}"><div class="output-card-head"><div class="output-icon">${out.key==="alarm"?"A":"H"}</div><strong>${esc(out.name)}</strong><span class="state-pill ${Number(out.state.value)===1?"on":""}">${esc(fmt(out.state.displayValue))}</span></div><div class="output-details"><div><span>控制模式</span><strong>${esc(fmt(out.mode?.displayValue))}</strong></div><div><span>累计动作</span><strong>${out.count?`${esc(fmt(out.count.value,0))} 次`:"—"}</strong></div></div></article>`).join("");
  $("valveCards").innerHTML=s.valves.map(v=>`<article class="valve-card ${Number(v.faultReason.value)?"has-fault":""}"><div class="valve-card-head"><div><span class="valve-index">V${v.channel}</span><strong>${esc(v.name)}</strong></div><span class="state-pill ${Number(v.faultReason.value)?"fault":"ok"}">${Number(v.faultReason.value)?`故障 ${fmt(v.faultReason.value,0)}`:"正常"}</span></div><div class="valve-metrics"><div><span>显示状态</span><strong>${esc(fmt(v.displayState.displayValue))}</strong></div><div><span>执行状态</span><strong>${esc(fmt(v.actuatorState.displayValue))}</strong></div><div><span>位置</span><strong>${fmt(v.position.value,0)}%</strong></div><div><span>电流</span><strong>${fmt(v.currentAdc.value,0)}</strong></div></div><div class="valve-card-foot"><span>控制来源</span><strong>${esc(fmt(v.controlSource.displayValue))}</strong></div></article>`).join("");
  renderHeatModeControls(s.outputs || []);renderValveControls(s.runtimeValves || []);renderAlarmSummary();renderDiagnostics();
}

const TREND_PRESETS={environment:["sensor_1.temperature","sensor_1.humidity","sensor_2.temperature","sensor_2.humidity","sensor_3.temperature","sensor_3.humidity"],process:["pressure","flow"],all:Object.keys(TREND_META)};
// 完整趋势工作台，保留统一 API 供定时刷新和页面切换调用。
function renderTrendToggles(){
  $("trendToggles").innerHTML=Object.entries(TREND_META).map(([key,[label,color,unit]])=>`<label class="trend-toggle ${activeTrends.has(key)?"active":""}"><input type="checkbox" data-trend="${key}" ${activeTrends.has(key)?"checked":""}><i style="background:${color}"></i><span>${label}</span><small>${unit}</small></label>`).join("");
  document.querySelectorAll("[data-trend]").forEach(input=>input.addEventListener("change",()=>{input.checked?activeTrends.add(input.dataset.trend):activeTrends.delete(input.dataset.trend);state.trendViewport=null;state.trendViewportHistory=[];renderTrendToggles();drawTrendChart();renderTrendLatest();}));
  document.querySelectorAll("[data-trend-preset]").forEach(button=>button.onclick=()=>{activeTrends.clear();(TREND_PRESETS[button.dataset.trendPreset]||[]).forEach(key=>activeTrends.add(key));state.trendViewport=null;state.trendViewportHistory=[];renderTrendToggles();drawTrendChart();renderTrendLatest();});
}
function renderTrendDatePresets(){
  const select=$("trendDatePreset"),current=select.value,dates=state.series.availableDates||[];
  select.innerHTML='<option value="">选择数据日期</option>'+dates.map(date=>`<option value="${date}" ${date===current?"selected":""}>${date}</option>`).join("");
}
function selectedTrendRows(){return [...activeTrends].map(key=>({key,rows:(state.series.byMetric?.[key]||[]).map(row=>({...row,epoch:new Date(row.ts).getTime()})).filter(row=>Number.isFinite(row.epoch)&&Number.isFinite(Number(row.value))),meta:TREND_META[key]})).filter(item=>item.rows.length);}
function trendBounds(series){const all=series.flatMap(item=>item.rows);if(!all.length)return null;const start=Math.min(...all.map(row=>row.epoch)),end=Math.max(...all.map(row=>row.epoch));return {start,end:end===start?start+1000:end};}
function clampTrendViewport(viewport,bounds){if(!viewport||!bounds)return bounds;const full=bounds.end-bounds.start,span=Math.max(1000,Math.min(full,viewport.end-viewport.start));const start=Math.max(bounds.start,Math.min(bounds.end-span,viewport.start));return {start,end:start+span};}
function setTrendViewport(next,remember=true){const bounds=trendBounds(selectedTrendRows());if(!bounds)return;if(remember&&state.trendViewport)state.trendViewportHistory.push({...state.trendViewport});if(state.trendViewportHistory.length>30)state.trendViewportHistory.shift();state.trendViewport=clampTrendViewport(next,bounds);drawTrendChart();}
function applyTrendWindow(windowMs){state.trendQuery={windowMs,start:null,end:null};state.trendViewport=null;state.trendViewportHistory=[];$("trendStart").value="";$("trendEnd").value="";$("trendDatePreset").value="";$("trendWindow").value=String(windowMs);refreshSeries();}
async function refreshSeries(){if(!state.selectedDeviceId)return;try{const query=new URLSearchParams({deviceId:state.selectedDeviceId,windowMs:String(state.trendQuery.windowMs),limit:"2000"});if(state.trendQuery.start)query.set("start",state.trendQuery.start);if(state.trendQuery.end)query.set("end",state.trendQuery.end);const [series,eventPayload]=await Promise.all([api(`/api/monitor/series?${query}`),api(`/api/monitor/events?deviceId=${encodeURIComponent(state.selectedDeviceId)}&limit=240`)]);state.series=series;state.events=eventPayload.items||[];renderTrendDatePresets();drawTrendChart();renderTrendLatest();renderTrendRangeText();}catch(error){showNotice(error.message,"error");}}
function renderTrendRangeText(){const series=selectedTrendRows(),all=trendBounds(series),points=series.reduce((sum,item)=>sum+item.rows.length,0);if(!all){$("trendRangeText").textContent="当前时段暂无数据";return;}const view=state.trendViewport||all;$("trendRangeText").textContent=`${new Date(view.start).toLocaleString("zh-CN",{hour12:false})} 至 ${new Date(view.end).toLocaleString("zh-CN",{hour12:false})} · ${points} 点`;}
function trendScale(visible){let low=Math.min(...visible.map(row=>Number(row.value))),high=Math.max(...visible.map(row=>Number(row.value)));if(low===high){const delta=Math.max(1,Math.abs(low)*.05);low-=delta;high+=delta;}const center=(low+high)/2,half=(high-low)*.6*state.trendYScale;return {low:center-half,high:center+half};}
function drawTrendChart(){
  const canvas=$("trendCanvas"),host=$("trendChartPanel"),toolbar=host.querySelector(".trend-chart-toolbar"),hint=host.querySelector(".trend-chart-hint"),dpr=window.devicePixelRatio||1,width=Math.max(1,host.clientWidth),height=Math.max(1,host.clientHeight-toolbar.offsetHeight-hint.offsetHeight),ctx=canvas.getContext("2d");canvas.width=width*dpr;canvas.height=height*dpr;canvas.style.width=`${width}px`;canvas.style.height=`${height}px`;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const series=selectedTrendRows(),bounds=trendBounds(series);$("chartEmpty").classList.toggle("hidden",Boolean(bounds));if(!bounds)return;
  const viewport=clampTrendViewport(state.trendViewport||bounds,bounds);state.trendViewport=viewport;const pad={l:62,r:24,t:44,b:44},plotW=Math.max(1,width-pad.l-pad.r),plotH=Math.max(1,height-pad.t-pad.b),xFor=epoch=>pad.l+(epoch-viewport.start)/(viewport.end-viewport.start)*plotW;
  ctx.strokeStyle="#21364d";ctx.fillStyle="#8ca2b7";ctx.font="11px Segoe UI";ctx.lineWidth=1;
  for(let i=0;i<=5;i++){const y=pad.t+plotH*i/5;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke();}
  const span=viewport.end-viewport.start;for(let i=0;i<=6;i++){const x=pad.l+plotW*i/6,epoch=viewport.start+span*i/6,date=new Date(epoch),label=span>86400000?date.toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}):date.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",second:span<3600000?"2-digit":undefined,hour12:false});ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,height-pad.b);ctx.stroke();ctx.fillText(label,x-30,height-16);}
  const plotted=[];series.forEach((item,index)=>{const visible=item.rows.filter(row=>row.epoch>=viewport.start&&row.epoch<=viewport.end);if(!visible.length)return;const scale=trendScale(visible),yFor=value=>pad.t+(scale.high-value)/(scale.high-scale.low)*plotH;plotted.push({...item,visible,scale,yFor});ctx.strokeStyle=item.meta[1];ctx.lineWidth=2;ctx.beginPath();visible.forEach((row,rowIndex)=>{const x=xFor(row.epoch),y=yFor(Number(row.value));rowIndex?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.fillStyle=item.meta[1];ctx.font="11px Segoe UI";ctx.fillText(`${item.meta[0]} ${scale.low.toFixed(1)}–${scale.high.toFixed(1)} ${item.meta[2]}`,pad.l+(index%4)*Math.max(145,plotW/4),18+Math.floor(index/4)*16);
    if(state.trendShowLabels){const step=Math.max(1,Math.ceil(visible.length/18));visible.forEach((row,i)=>{if(i%step&&i!==visible.length-1)return;ctx.fillStyle=item.meta[1];ctx.font="10px Segoe UI";ctx.fillText(fmt(Number(row.value)),xFor(row.epoch)+3,yFor(Number(row.value))-5);});}
    if(state.trendShowKeyPoints){const min=visible.reduce((a,b)=>Number(a.value)<Number(b.value)?a:b),max=visible.reduce((a,b)=>Number(a.value)>Number(b.value)?a:b),last=visible.at(-1);[[min,"最小"],[max,"最大"],[last,"最新"]].forEach(([row,label])=>{const x=xFor(row.epoch),y=yFor(Number(row.value));ctx.fillStyle=item.meta[1];ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.fill();ctx.fillStyle="#e8f1f8";ctx.font="10px Segoe UI";ctx.fillText(`${label} ${fmt(Number(row.value))}`,Math.min(width-95,x+6),Math.max(12,y-7));});}
  });
  if(state.trendShowEvents){state.events.filter(event=>event.type!=="read_success").map(event=>({...event,epoch:new Date(event.ts).getTime()})).filter(event=>Number.isFinite(event.epoch)&&event.epoch>=viewport.start&&event.epoch<=viewport.end).slice(-24).forEach((event,index)=>{const x=xFor(event.epoch);ctx.strokeStyle="rgba(251,113,133,.72)";ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,height-pad.b);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle="#fb7185";ctx.font="10px Segoe UI";ctx.fillText(index%2?"事件":"▲",Math.min(width-pad.r-28,x+3),pad.t+12+(index%2)*12);});}
  if(state.trendSelectionDraft){const x1=Math.min(state.trendSelectionDraft.startX,state.trendSelectionDraft.endX),x2=Math.max(state.trendSelectionDraft.startX,state.trendSelectionDraft.endX);ctx.fillStyle="rgba(56,189,248,.14)";ctx.strokeStyle="rgba(56,189,248,.8)";ctx.fillRect(x1,pad.t,x2-x1,plotH);ctx.strokeRect(x1,pad.t,x2-x1,plotH);}
  if(state.trendHover&&state.trendHover.epoch>=viewport.start&&state.trendHover.epoch<=viewport.end){const x=xFor(state.trendHover.epoch);ctx.strokeStyle="rgba(232,241,248,.65)";ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,height-pad.b);ctx.stroke();ctx.setLineDash([]);}
  state.trendPlot={width,height,pad,plotW,plotH,viewport,xFor,plotted};renderTrendRangeText();
}
function renderTrendLatest(){$("trendLatest").innerHTML=[...activeTrends].map(key=>{const rows=state.series.byMetric?.[key]||[],last=rows.at(-1),numeric=rows.map(row=>Number(row.value)).filter(Number.isFinite),minimum=numeric.length?Math.min(...numeric):null,maximum=numeric.length?Math.max(...numeric):null,average=numeric.length?numeric.reduce((sum,value)=>sum+value,0)/numeric.length:null,meta=TREND_META[key]||[key,"",""];return `<div class="latest-item" style="border-top:2px solid ${meta[1]}"><span>${meta[0]} · ${meta[2]}</span><strong>${fmt(last?.value)}</strong><small>最小 ${fmt(minimum)} · 最大 ${fmt(maximum)} · 均值 ${fmt(average)}</small></div>`;}).join("");}
function ensureTrendTooltip(){let tooltip=$("trendTooltip");if(!tooltip){tooltip=document.createElement("div");tooltip.id="trendTooltip";tooltip.className="trend-tooltip hidden";$("trendChartPanel").appendChild(tooltip);}return tooltip;}
function showTrendTooltip(event){const plot=state.trendPlot;if(!plot?.plotted?.length)return;const canvas=$("trendCanvas"),rect=canvas.getBoundingClientRect(),x=Math.max(plot.pad.l,Math.min(rect.width-plot.pad.r,event.clientX-rect.left)),target=plot.viewport.start+(x-plot.pad.l)/plot.plotW*(plot.viewport.end-plot.viewport.start);let nearest=null;plot.plotted.forEach(item=>item.visible.forEach(row=>{if(!nearest||Math.abs(row.epoch-target)<Math.abs(nearest.epoch-target))nearest=row;}));if(!nearest)return;state.trendHover=nearest;const values=plot.plotted.map(item=>{const row=item.visible.reduce((best,current)=>!best||Math.abs(current.epoch-nearest.epoch)<Math.abs(best.epoch-nearest.epoch)?current:best,null);return `<div><i style="background:${item.meta[1]}"></i><span>${item.meta[0]}</span><strong>${fmt(row?.value)} ${item.meta[2]}</strong></div>`;}).join("");const tooltip=ensureTrendTooltip();tooltip.innerHTML=`<time>${new Date(nearest.epoch).toLocaleString("zh-CN",{hour12:false})}</time>${values}`;tooltip.style.left=`${Math.min(rect.width-230,Math.max(12,event.clientX-rect.left+14))}px`;tooltip.style.top=`${Math.max(58,event.clientY-rect.top+14)}px`;tooltip.classList.remove("hidden");drawTrendChart();}
function renderTrendSelectionStats(start,end){const items=selectedTrendRows().map(item=>{const values=item.rows.filter(row=>row.epoch>=start&&row.epoch<=end).map(row=>Number(row.value)).filter(Number.isFinite);return {...item,values};}).filter(item=>item.values.length),host=$("trendSelectionStats");if(!items.length){host.classList.add("hidden");return;}host.innerHTML=`<div class="trend-selection-head"><div><h3>框选时段统计</h3><span>${new Date(start).toLocaleString("zh-CN",{hour12:false})} 至 ${new Date(end).toLocaleString("zh-CN",{hour12:false})}</span></div><button id="clearTrendSelectionBtn" class="button small secondary">关闭统计</button></div><div class="trend-selection-grid">${items.map(item=>`<div class="trend-selection-item"><span>${item.meta[0]} · ${item.values.length} 点</span><strong>最小 ${fmt(Math.min(...item.values))} · 最大 ${fmt(Math.max(...item.values))}</strong><small>平均 ${fmt(item.values.reduce((a,b)=>a+b,0)/item.values.length)} ${item.meta[2]}</small></div>`).join("")}</div>`;host.classList.remove("hidden");$("clearTrendSelectionBtn").addEventListener("click",()=>host.classList.add("hidden"));}
function setupTrendInteractions(){const canvas=$("trendCanvas");canvas.addEventListener("wheel",event=>{event.preventDefault();const plot=state.trendPlot;if(!plot)return;const rect=canvas.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(event.clientX-rect.left-plot.pad.l)/plot.plotW)),view=plot.viewport,span=view.end-view.start,nextSpan=Math.max(1000,span*(event.deltaY<0?.78:1.28)),anchor=view.start+span*fraction;setTrendViewport({start:anchor-nextSpan*fraction,end:anchor+nextSpan*(1-fraction)});},{passive:false});canvas.addEventListener("pointerdown",event=>{if(!state.trendPlot)return;canvas.setPointerCapture(event.pointerId);const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left;state.trendDrag={mode:event.shiftKey?"pan":"select",x,viewport:{...state.trendPlot.viewport}};if(!event.shiftKey)state.trendSelectionDraft={startX:x,endX:x};});canvas.addEventListener("pointermove",event=>{if(!state.trendDrag){showTrendTooltip(event);return;}const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left;if(state.trendDrag.mode==="select"){state.trendSelectionDraft.endX=x;drawTrendChart();return;}const plot=state.trendPlot,shift=-(x-state.trendDrag.x)/plot.plotW*(state.trendDrag.viewport.end-state.trendDrag.viewport.start);state.trendViewport=clampTrendViewport({start:state.trendDrag.viewport.start+shift,end:state.trendDrag.viewport.end+shift},trendBounds(selectedTrendRows()));drawTrendChart();});canvas.addEventListener("pointerup",event=>{if(state.trendDrag?.mode==="select"&&state.trendSelectionDraft&&state.trendPlot){const plot=state.trendPlot,x1=Math.max(plot.pad.l,Math.min(plot.width-plot.pad.r,Math.min(state.trendSelectionDraft.startX,state.trendSelectionDraft.endX))),x2=Math.max(plot.pad.l,Math.min(plot.width-plot.pad.r,Math.max(state.trendSelectionDraft.startX,state.trendSelectionDraft.endX)));if(x2-x1>12){const start=plot.viewport.start+(x1-plot.pad.l)/plot.plotW*(plot.viewport.end-plot.viewport.start),end=plot.viewport.start+(x2-plot.pad.l)/plot.plotW*(plot.viewport.end-plot.viewport.start);renderTrendSelectionStats(start,end);setTrendViewport({start,end});}}state.trendDrag=null;state.trendSelectionDraft=null;try{canvas.releasePointerCapture(event.pointerId);}catch(_){}drawTrendChart();});canvas.addEventListener("pointerleave",()=>{if(!state.trendDrag){state.trendHover=null;ensureTrendTooltip().classList.add("hidden");drawTrendChart();}});}
function zoomTrend(factor){const bounds=trendBounds(selectedTrendRows());if(!bounds)return;const view=state.trendViewport||bounds,span=(view.end-view.start)*factor,mid=(view.start+view.end)/2;setTrendViewport({start:mid-span/2,end:mid+span/2});}
function panTrend(fraction){const bounds=trendBounds(selectedTrendRows());if(!bounds)return;const view=state.trendViewport||bounds,shift=(view.end-view.start)*fraction;setTrendViewport({start:view.start+shift,end:view.end+shift});}
function undoTrendViewport(){const previous=state.trendViewportHistory.pop();if(previous){state.trendViewport=previous;drawTrendChart();}}
function resetTrendViewport(){if(state.trendViewport)state.trendViewportHistory.push({...state.trendViewport});state.trendViewport=null;state.trendYScale=1;drawTrendChart();}
function toggleTrendFullscreen(){const panel=$("trendChartPanel"),active=panel.classList.toggle("chart-fullscreen");document.body.classList.toggle("trend-fullscreen-active",active);$("fullscreenTrendBtn").textContent=active?"退出全屏":"全屏";setTimeout(drawTrendChart,80);}
function exportTrendPng(){const link=document.createElement("a");link.href=$("trendCanvas").toDataURL("image/png");link.download=`YLDQ_曲线_${new Date().toISOString().slice(0,19).replaceAll(':','-')}.png`;link.click();}
function exportTrendCsv(){const keys=[...activeTrends],timestamps=[...new Set(keys.flatMap(key=>(state.series.byMetric?.[key]||[]).map(row=>row.ts)))].sort(),byTimestamp=new Map(timestamps.map(ts=>[ts,{ts}]));keys.forEach(key=>(state.series.byMetric?.[key]||[]).forEach(row=>{byTimestamp.get(row.ts)[key]=row.value;}));const header=["时间",...keys.map(key=>`${TREND_META[key]?.[0]||key}(${TREND_META[key]?.[2]||""})`)],csv=[header,...timestamps.map(ts=>[ts,...keys.map(key=>byTimestamp.get(ts)[key]??"")])].map(row=>row.map(value=>`"${String(value).replaceAll('"','""')}"`).join(",")).join("\r\n");const blob=new Blob(["\uFEFF",csv],{type:"text/csv;charset=utf-8"}),link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download=`YLDQ_曲线_${new Date().toISOString().slice(0,19).replaceAll(':','-')}.csv`;link.click();URL.revokeObjectURL(link.href);}
function bindTrendWorkbench(){
  $("trendDatePreset").addEventListener("change",()=>{const date=$("trendDatePreset").value;if(!date)return;$("trendStart").value=`${date}T00:00`;$("trendEnd").value=`${date}T23:59`;$("applyTrendRangeBtn").click();});
  $("undoTrendZoomBtn").addEventListener("click",undoTrendViewport);$("panLeftTrendBtn").addEventListener("click",()=>panTrend(-.2));$("panRightTrendBtn").addEventListener("click",()=>panTrend(.2));$("tightenTrendYBtn").addEventListener("click",()=>{state.trendYScale=Math.max(.2,state.trendYScale*.8);drawTrendChart();});$("relaxTrendYBtn").addEventListener("click",()=>{state.trendYScale=Math.min(5,state.trendYScale*1.25);drawTrendChart();});$("toggleTrendLabelsBtn").addEventListener("click",()=>{state.trendShowLabels=!state.trendShowLabels;$("toggleTrendLabelsBtn").classList.toggle("active",state.trendShowLabels);drawTrendChart();});$("toggleTrendKeyPointsBtn").addEventListener("click",()=>{state.trendShowKeyPoints=!state.trendShowKeyPoints;$("toggleTrendKeyPointsBtn").classList.toggle("active",state.trendShowKeyPoints);drawTrendChart();});$("toggleTrendEventsBtn").addEventListener("click",()=>{state.trendShowEvents=!state.trendShowEvents;$("toggleTrendEventsBtn").classList.toggle("active",state.trendShowEvents);drawTrendChart();});$("fullscreenTrendBtn").addEventListener("click",toggleTrendFullscreen);$("exportTrendPngBtn").addEventListener("click",exportTrendPng);
  document.addEventListener("keydown",event=>{if(state.activePage!=="trends"||["INPUT","SELECT","TEXTAREA"].includes(event.target.tagName))return;if(event.key==="r"||event.key==="R")resetTrendViewport();else if(event.key==="+")zoomTrend(.75);else if(event.key==="-")zoomTrend(1.3);else if(event.key==="ArrowLeft")panTrend(-.15);else if(event.key==="ArrowRight")panTrend(.15);else if((event.key==="f"||event.key==="F"))toggleTrendFullscreen();else if(event.key==="Escape"&&$("trendChartPanel").classList.contains("chart-fullscreen"))toggleTrendFullscreen();});
}

function renderHeatModeControls(outputs=[]){
  const byKey=new Map(outputs.map(output=>[output.key,output]));
  HEAT_MODE_CONTROLS.forEach(({itemId,outputKey})=>{
    const host=document.querySelector(`[data-mode-control="${itemId}"]`);if(!host)return;
    const current=Number(byKey.get(outputKey)?.mode?.value),pending=pendingControls.has(itemId);
    host.innerHTML=[[0,"自动"],[1,"强制关"],[2,"强制开"]].map(([value,label])=>`<button type="button" data-heat-mode data-control="${itemId}" data-value="${value}" class="${current===value?"selected":""}" aria-pressed="${current===value}" ${pending?"disabled":""}>${label}</button>`).join("");
    host.querySelectorAll("[data-control]").forEach(button=>button.addEventListener("click",()=>writeControl(itemId,Number(button.dataset.value))));
  });
}
function buildControlButtons(){
  renderHeatModeControls();
  document.querySelectorAll("[data-control]:not([data-heat-mode])").forEach(button=>button.addEventListener("click",()=>writeControl(button.dataset.control,Number(button.dataset.value))));
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
  pendingControls.add(itemId);renderHeatModeControls(state.snapshot?.outputs||[]);renderValveControls(state.snapshot?.runtimeValves||[]);
  try{
    const result=await api("/api/control/write",{method:"POST",body:JSON.stringify({deviceId:state.selectedDeviceId,itemId,value})});
    const confirmed=result.runtimeFeedback?.[itemId];
    const confirmedLabel=result.item?.enumValues?.[confirmed] ?? result.item?.enumValues?.[String(confirmed)] ?? confirmed;
    showNotice(confirmed===undefined?"命令已发送":`命令已确认：${confirmedLabel}`);
    await refreshLive();
  }catch(error){showNotice(error.message,"error");}
  finally{pendingControls.delete(itemId);renderHeatModeControls(state.snapshot?.outputs||[]);renderValveControls(state.snapshot?.runtimeValves||[]);}
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
async function refreshTraffic(){if(!state.selectedDeviceId||state.trafficLoading)return;state.trafficLoading=true;try{state.traffic=(await api(`/api/monitor/traffic?deviceId=${encodeURIComponent(state.selectedDeviceId)}&limit=200`)).items||[];renderTraffic();}catch(error){showNotice(error.message,"error");}finally{state.trafficLoading=false;}}
function renderTraffic(){$("trafficTableBody").innerHTML=state.traffic.length?[...state.traffic].reverse().map(r=>`<tr><td>${esc(r.sentAt||"")}</td><td>${esc(r.deviceName||r.deviceId||"")}</td><td><code>${esc(r.requestHex||"")}</code></td><td><code>${esc(r.responseHex||"")}</code></td><td><span class="state-pill ${r.status==='ok'?'ok':r.status==='error'?'fault':''}">${esc(r.status||"")}</span></td><td>${esc(r.error||"")}</td></tr>`).join(""):'<tr><td colspan="6" class="empty-state">暂无通信记录</td></tr>';}
async function sendDebugFrame(){
  if(!state.selectedDeviceId)return showNotice("请先选择设备","error");
  const requestHex=$("debugFrameInput").value.trim();if(!requestHex)return showNotice("请输入十六进制报文","error");
  const button=$("sendDebugFrameBtn"), resultNode=$("debugFrameResult");button.disabled=true;resultNode.textContent="正在发送…";
  try{
    const result=await api("/api/diagnostics/send-frame",{method:"POST",body:JSON.stringify({deviceId:state.selectedDeviceId,requestHex,appendCrc:$("debugAppendCrc").checked,expectResponse:$("debugExpectResponse").checked,responseTimeoutMs:Number($("debugTimeoutMs").value)||1200})});
    resultNode.textContent=`状态：${result.status}\n请求：${result.requestHex}\n响应：${result.responseHex||"无响应"}`;showNotice("手动报文已发送");await refreshTraffic();
  }catch(error){resultNode.textContent=`发送失败：${error.message}`;showNotice(error.message,"error");}
  finally{button.disabled=false;}
}
function renderDiagnostics(){const c=state.snapshot?.communication,s=state.snapshot?.session;if(!c)return;$("diagnosticStats").innerHTML=[["通信健康",c.text,""],["连续失败",fmt(c.failureCount.value,0),"次"],["请求总数",fmt(s?.request_count,0),"次"],["最近成功",s?.last_success_at||"--",""]].map(([name,value,unit])=>`<article class="hero-card"><span>${name}</span><strong>${esc(value)}</strong><em>${unit}</em></article>`).join("");}

function renderDevices(){const selected=state.selectedDeviceId;$("deviceCards").innerHTML=state.devices.length?state.devices.map(d=>`<article class="device-card ${d.id===selected?"selected":""}"><div class="card-head"><h3>${esc(d.name)}</h3><span class="state-pill ${d.enabled?'ok':''}">${d.enabled?'已启用':'已禁用'}</span></div><div class="device-meta"><span>端口</span><strong>${esc(d.address)}</strong><span>从站</span><strong>${d.slaveId}</strong><span>串口</span><strong>${d.baudrate} ${d.parity}81</strong><span>协议</span><strong>V7 RTU</strong></div><div class="device-actions"><button class="button small primary" data-select-device="${esc(d.id)}">选择</button><button class="button small secondary" data-edit-device="${esc(d.id)}">编辑</button><button class="button small danger ghost" data-delete-device="${esc(d.id)}">删除</button></div></article>`).join(""):'<div class="empty-state panel">暂无设备，点击“添加设备”开始配置。</div>';
  document.querySelectorAll("[data-select-device]").forEach(b=>b.addEventListener("click",()=>selectDevice(b.dataset.selectDevice)));
  document.querySelectorAll("[data-edit-device]").forEach(b=>b.addEventListener("click",()=>openDeviceDialog(state.devices.find(d=>d.id===b.dataset.editDevice))));
  document.querySelectorAll("[data-delete-device]").forEach(b=>b.addEventListener("click",()=>deleteDevice(b.dataset.deleteDevice)));
}
async function openDeviceDialog(device=null){
  try{const bootstrap=await api("/api/bootstrap");state.bootstrap={...(state.bootstrap||{}),...bootstrap};}catch(error){showNotice(`串口列表刷新失败：${error.message}`,"error");}
  $("deviceDialogTitle").textContent=device?"编辑设备":"添加设备";$("deviceId").value=device?.id||"";$("deviceName").value=device?.name||"";renderPortOptions(device?.address||"COM1");$("deviceSlave").value=device?.slaveId||1;$("deviceBaud").value=device?.baudrate||9600;$("deviceParity").value=device?.parity||"N";$("deviceTimeout").value=device?.timeoutMs||1200;$("deviceEnabled").checked=device?.enabled??true;$("deviceDialog").showModal();
}
function renderPortOptions(selected){const ports=state.bootstrap?.serialPorts||[], knownPorts=state.devices.map(device=>device.address), values=[...new Set([selected,...knownPorts,...ports.map(p=>p.device)].filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b),undefined,{numeric:true}));$("devicePort").innerHTML=values.map(p=>`<option value="${esc(p)}" ${p===selected?"selected":""}>${esc(p)} ${esc(ports.find(x=>x.device===p)?.description||"已保存端口")}</option>`).join("");}
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
  $("refreshTrendBtn").addEventListener("click",refreshSeries);$("trendWindow").addEventListener("change",()=>applyTrendWindow(Number($("trendWindow").value)));document.querySelectorAll("[data-trend-window]").forEach(button=>button.addEventListener("click",()=>applyTrendWindow(Number(button.dataset.trendWindow))));$("applyTrendRangeBtn").addEventListener("click",()=>{const start=$("trendStart").value,end=$("trendEnd").value;if(!start||!end)return showNotice("请选择完整的开始和结束时间","error");if(new Date(end)<new Date(start))return showNotice("结束时间不能早于开始时间","error");state.trendQuery={windowMs:state.trendQuery.windowMs,start:start.replace("T"," "),end:end.replace("T"," ")};state.trendViewport=null;state.trendViewportHistory=[];refreshSeries();});$("zoomInTrendBtn").addEventListener("click",()=>zoomTrend(.65));$("zoomOutTrendBtn").addEventListener("click",()=>zoomTrend(1.55));$("resetTrendZoomBtn").addEventListener("click",resetTrendViewport);$("exportTrendBtn").addEventListener("click",exportTrendCsv);setupTrendInteractions();bindTrendWorkbench();window.addEventListener("resize",()=>state.activePage==="trends"&&drawTrendChart());
  $("resetAllValvesBtn").addEventListener("click",()=>writeControl("holding.runtime.reset",7));
  $("refreshConfigBtn").addEventListener("click",async()=>{try{await api("/api/config/refresh",{method:"POST",body:JSON.stringify({deviceId:state.selectedDeviceId})});await refreshParameters();showNotice("参数读取完成");}catch(e){showNotice(e.message,"error");}});
  $("commitConfigBtn").addEventListener("click",()=>configAction("commit"));$("discardConfigBtn").addEventListener("click",()=>configAction("discard"));$("configSearch").addEventListener("input",renderConfigTable);
  $("refreshEventsBtn").addEventListener("click",refreshEvents);$("refreshTrafficBtn").addEventListener("click",refreshTraffic);$("clearTrafficBtn").addEventListener("click",async()=>{await api("/api/traffic/clear",{method:"POST",body:"{}"});await refreshTraffic();});$("sendDebugFrameBtn").addEventListener("click",sendDebugFrame);
  $("addDeviceBtn").addEventListener("click",()=>openDeviceDialog());$("closeDeviceDialog").addEventListener("click",()=>$("deviceDialog").close());$("cancelDeviceBtn").addEventListener("click",()=>$("deviceDialog").close());$("deviceForm").addEventListener("submit",saveDevice);
  setInterval(()=>$("clockText").textContent=new Date().toLocaleString("zh-CN",{hour12:false}),1000);setInterval(()=>state.activePage==="diagnostics"&&refreshTraffic(),1000);
}

bind();bootstrap().catch(error=>showNotice(`系统初始化失败：${error.message}`,"error"));
