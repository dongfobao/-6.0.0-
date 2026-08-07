const host = document.getElementById("digitalTwinViewport");
const statusHost = document.getElementById("digitalTwinStatus");
const connectionNode = document.getElementById("digitalTwinConnection");
const breathNode = document.getElementById("digitalTwinBreath");
const resetButton = document.getElementById("resetDigitalTwinBtn");
const upperCallout = document.getElementById("twinUpperCallout");
const heatCallout = document.getElementById("twinHeatCallout");
const drainCallout = document.getElementById("twinDrainCallout");

const STATUS = { snapshot: null, upperTarget: -0.23, drainTarget: -0.20, dragging: false, pointer: null, yaw: -0.42, pitch: 0.10, distance: 7.3 };
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.domElement.setAttribute("aria-hidden", "true");
host.prepend(renderer.domElement);
host.querySelector(".digital-twin-loading")?.remove();

const rig = new THREE.Group();
scene.add(rig);
const materials = {
  metal: new THREE.MeshStandardMaterial({ color: 0xa5b4c3, metalness: .78, roughness: .28 }),
  dark: new THREE.MeshStandardMaterial({ color: 0x1d3c55, metalness: .66, roughness: .30 }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0x4bbfc8, transparent: true, opacity: .18, roughness: .08, metalness: .08, side: THREE.DoubleSide, depthWrite: false }),
  silica: new THREE.MeshStandardMaterial({ color: 0x4c8f9b, transparent: true, opacity: .33, metalness: .15, roughness: .66, depthWrite: false }),
  heated: new THREE.MeshStandardMaterial({ color: 0x8d5534, emissive: 0x000000, emissiveIntensity: 0 }),
  air: new THREE.MeshBasicMaterial({ color: 0xfb7185, transparent: true, opacity: .9 }),
  water: new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: .74 }),
  fault: new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0x5f0000, emissiveIntensity: .7 }),
};
const cadMaterials = {
  structure: new THREE.MeshStandardMaterial({ color: 0x708699, metalness: .64, roughness: .38 }),
  valve: new THREE.MeshStandardMaterial({ color: 0x183d5b, metalness: .62, roughness: .30 }),
  heater: new THREE.MeshStandardMaterial({ color: 0x98583b, metalness: .52, roughness: .42 }),
  support: new THREE.MeshStandardMaterial({ color: 0x987252, metalness: .12, roughness: .58 }),
  desiccant: new THREE.MeshStandardMaterial({ color: 0x3f9b78, transparent: true, opacity: .16, metalness: .05, roughness: .64, depthWrite: false }),
  glass: new THREE.MeshPhysicalMaterial({ color: 0x4cc5cf, transparent: true, opacity: .14, metalness: .04, roughness: .08, side: THREE.DoubleSide, depthWrite: false }),
  activeValve: new THREE.MeshStandardMaterial({ color: 0x0d5b86, emissive: 0x0d2c42, emissiveIntensity: .9, metalness: .58, roughness: .28 }),
};
const makeMesh = (geometry, material, x=0, y=0, z=0) => { const mesh = new THREE.Mesh(geometry, material); mesh.position.set(x,y,z); rig.add(mesh); return mesh; };
const cylinder = (radius, height, material, x=0,y=0,z=0) => makeMesh(new THREE.CylinderGeometry(radius,radius,height,40),material,x,y,z);

scene.add(new THREE.HemisphereLight(0xb7e6ff, 0x06101b, .72));
const keyLight = new THREE.DirectionalLight(0xe7f5ff, .86); keyLight.position.set(4,7,5); scene.add(keyLight);
const rimLight = new THREE.PointLight(0x38bdf8, 1.8, 12); rimLight.position.set(-3,2,3); scene.add(rimLight);

const floor = new THREE.Mesh(new THREE.CircleGeometry(2.7,48), new THREE.MeshStandardMaterial({ color: 0x0b2940, metalness: .6, roughness: .55 })); floor.rotation.x = -Math.PI / 2; floor.position.y = -2.45; rig.add(floor);
// 运行孪生使用半透明开窗壳体，优先呈现内部工艺而不是遮挡视线的实物外观。
const outerShell = makeMesh(new THREE.CylinderGeometry(1.08, 1.08, 4.2, 48, 1, true, .42, Math.PI * 1.55), materials.glass, 0, -.1, 0);
const topFlange = cylinder(1.19,.18,materials.metal,0,2.06,0);
const bottomFlange = cylinder(1.19,.18,materials.metal,0,-2.08,0);
const desiccantBed = cylinder(.82,3.55,materials.silica,0,-.05,0);
const heater = cylinder(.46,3.10,materials.heated,0,-.12,0);
const heaterCoils = [];
for (let y = -1.48; y <= 1.20; y += .24) {
  const coil = new THREE.Mesh(new THREE.TorusGeometry(.51,.022,8,28), materials.heated);
  coil.rotation.x = Math.PI / 2;
  coil.position.y = y;
  rig.add(coil);
  heaterCoils.push(coil);
}
const centerDuct = cylinder(.16,3.48,materials.dark,0,-.08,0);
const oilCup = cylinder(.43,.74,materials.glass,0,-2.52,0);
const upperValve = new THREE.Group(); rig.add(upperValve); upperValve.position.set(0,1.78,.82);
const upperBody = new THREE.Mesh(new THREE.BoxGeometry(1.04,.42,.56),materials.dark); upperValve.add(upperBody);
const upperSlider = new THREE.Mesh(new THREE.BoxGeometry(.34,.25,.38),materials.metal); upperSlider.name="upperSlider"; upperValve.add(upperSlider);
upperSlider.position.set(-.23,.06,0);
const upperCoil = new THREE.Mesh(new THREE.BoxGeometry(.36,.54,.68),materials.metal); upperValve.add(upperCoil); upperCoil.position.set(.66,.04,0);
const drainValve = new THREE.Group(); rig.add(drainValve); drainValve.position.set(.83,-1.84,.72); drainValve.rotation.z = .10;
const drainBody = new THREE.Mesh(new THREE.BoxGeometry(.72,.34,.46),materials.dark); drainValve.add(drainBody);
const drainSlider = new THREE.Mesh(new THREE.BoxGeometry(.28,.22,.32),materials.metal); drainSlider.name="drainSlider"; drainValve.add(drainSlider); drainSlider.position.set(-.20,.04,0);
const drainCoil = new THREE.Mesh(new THREE.BoxGeometry(.26,.42,.52),materials.metal); drainValve.add(drainCoil); drainCoil.position.set(.49,.03,0);

const sensorGroup = new THREE.Group(); rig.add(sensorGroup); sensorGroup.position.y=2.22;
[[-.58,0,"流量"],[0,0,"压力"],[.58,0,"温湿度"]].forEach(([x,z])=>{const s=new THREE.Mesh(new THREE.CylinderGeometry(.12,.12,.38,16),materials.metal);s.position.set(x,.28,z);sensorGroup.add(s);});
const airCurve = new THREE.CatmullRomCurve3([new THREE.Vector3(0,-2.45,.22),new THREE.Vector3(0,-.9,.28),new THREE.Vector3(0,.4,.28),new THREE.Vector3(0,1.45,.28),new THREE.Vector3(0,2.30,.22)]);
const waterCurve = new THREE.CatmullRomCurve3([new THREE.Vector3(.82,.95,.42),new THREE.Vector3(.88,-.65,.42),new THREE.Vector3(.86,-1.85,.25),new THREE.Vector3(.78,-2.23,.08),new THREE.Vector3(0,-2.55,0)]);
const airGuide = new THREE.Line(new THREE.BufferGeometry().setFromPoints(airCurve.getPoints(36)),new THREE.LineBasicMaterial({color:0xfb7185,transparent:true,opacity:.35}));
const waterGuide = new THREE.Line(new THREE.BufferGeometry().setFromPoints(waterCurve.getPoints(36)),new THREE.LineBasicMaterial({color:0x4ade80,transparent:true,opacity:.3}));
rig.add(airGuide, waterGuide);
const airTube = new THREE.Mesh(new THREE.TubeGeometry(airCurve, 56, .018, 8, false), new THREE.MeshBasicMaterial({ color: 0xfb7185, transparent: true, opacity: .34 }));
const waterTube = new THREE.Mesh(new THREE.TubeGeometry(waterCurve, 56, .014, 8, false), new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: .30 }));
rig.add(airTube, waterTube);
const airParticles = Array.from({length: 22}, (_, index) => { const dot=new THREE.Mesh(new THREE.SphereGeometry(.032,8,8),materials.air); rig.add(dot); return {dot, offset:index/22}; });
const waterParticles = Array.from({length: 12}, (_, index) => { const dot=new THREE.Mesh(new THREE.SphereGeometry(.025,8,8),materials.water); rig.add(dot); return {dot, offset:index/12}; });
const steamMaterial = new THREE.MeshBasicMaterial({ color: 0xd9f8ff, transparent: true, opacity: .33, depthWrite: false });
const steamParticles = Array.from({ length: 18 }, (_, index) => {
  const puff = new THREE.Mesh(new THREE.SphereGeometry(.055 + (index % 3) * .018, 10, 8), steamMaterial.clone());
  rig.add(puff);
  return { puff, offset: index / 18 };
});
const cadModel = new THREE.Group();
// Blender 导出的 Z 轴与界面 Y 轴相反；翻正后顶部阀门位于设备上方。
cadModel.position.y = 2.394;
cadModel.rotation.x = Math.PI;
cadModel.visible = false;
rig.add(cadModel);
const realEffects = new THREE.Group();
rig.add(realEffects);
const REAL = { upperValve: null, drainValve: null, heatMeshes: [], shellMeshes: [], airParticles: [], waterParticles: [], steamParticles: [], heatWaves: [], upperHalo: null, drainHalo: null, heatHalo: null };

function hideProceduralDevice() {
  [floor, outerShell, topFlange, bottomFlange, desiccantBed, heater, centerDuct, oilCup, upperValve, drainValve, sensorGroup, airGuide, waterGuide, airTube, waterTube, ...heaterCoils, ...airParticles.map(item => item.dot), ...waterParticles.map(item => item.dot), ...steamParticles.map(item => item.puff)]
    .forEach(object => { object.visible = false; });
}

function centerOf(object) {
  const box = new THREE.Box3().setFromObject(object);
  return box.getCenter(new THREE.Vector3());
}

function addRealHalo(object, color) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3()).multiplyScalar(1.12);
  const helper = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z)), new THREE.LineBasicMaterial({ color, transparent: true, opacity: .72 }));
  helper.position.copy(box.getCenter(new THREE.Vector3()));
  helper.userData.basePosition = helper.position.clone();
  helper.userData.source = object;
  realEffects.add(helper);
  return helper;
}

function buildRealProcessEffects(oilCupNode, heaterNode, upperValveNode, drainValveNode) {
  const oil = centerOf(oilCupNode || drainValveNode);
  const heaterCenter = centerOf(heaterNode || upperValveNode);
  const upper = centerOf(upperValveNode);
  const drain = centerOf(drainValveNode);
  const frontOffset = new THREE.Vector3(0, 0, .16);
  const airPath = new THREE.CatmullRomCurve3([oil.clone().add(frontOffset), heaterCenter.clone().add(frontOffset), upper.clone().add(frontOffset)]);
  const waterPath = new THREE.CatmullRomCurve3([heaterCenter.clone().add(new THREE.Vector3(.45, .55, .18)), heaterCenter.clone().add(new THREE.Vector3(.58, -.65, .20)), drain.clone().add(frontOffset), oil.clone().add(frontOffset)]);
  const airTubeReal = new THREE.Mesh(new THREE.TubeGeometry(airPath, 72, .024, 8, false), new THREE.MeshBasicMaterial({ color: 0xfb7185, transparent: true, opacity: .48 }));
  const waterTubeReal = new THREE.Mesh(new THREE.TubeGeometry(waterPath, 72, .018, 8, false), new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: .42 }));
  realEffects.add(airTubeReal, waterTubeReal);
  REAL.airParticles = Array.from({ length: 26 }, (_, index) => {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(.042, 8, 8), materials.air.clone());
    realEffects.add(dot);
    return { dot, path: airPath, offset: index / 26 };
  });
  REAL.waterParticles = Array.from({ length: 16 }, (_, index) => {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(.022, 8, 8), materials.water.clone());
    realEffects.add(dot);
    return { dot, path: waterPath, offset: index / 16 };
  });
  REAL.steamParticles = Array.from({ length: 20 }, (_, index) => {
    const puff = new THREE.Mesh(new THREE.SphereGeometry(.065 + (index % 3) * .022, 9, 8), new THREE.MeshBasicMaterial({ color: 0xfff3d6, transparent: true, opacity: .52, depthWrite: false }));
    realEffects.add(puff);
    return { puff, origin: heaterCenter.clone(), offset: index / 20 };
  });
  REAL.heatWaves = Array.from({ length: 6 }, (_, index) => {
    const wave = new THREE.Mesh(new THREE.TorusGeometry(.18 + index * .07, .020, 8, 32), new THREE.MeshBasicMaterial({ color: 0xfb923c, transparent: true, opacity: .62, depthWrite: false }));
    wave.rotation.x = Math.PI / 2;
    wave.position.copy(heaterCenter);
    realEffects.add(wave);
    return { wave, origin: heaterCenter.clone(), offset: index / 6 };
  });
  REAL.upperHalo = addRealHalo(upperValveNode, 0xfb7185);
  REAL.drainHalo = addRealHalo(drainValveNode, 0x4ade80);
  REAL.heatHalo = addRealHalo(heaterNode || upperValveNode, 0xfb923c);
}

function loadCadAssembly() {
  if (!THREE.GLTFLoader) {
    console.warn("未加载 GLTFLoader，将使用简化数字孪生外观。");
    return;
  }
  new THREE.GLTFLoader().load("/assets/yldq-5-single-pipe.glb?v=3", gltf => {
    let oilCupNode = null;
    let heaterNode = null;
    gltf.scene.traverse(object => {
      if (!object.isMesh) return;
      // glTF 的业务属性和零件名在节点上，实际网格是其子对象。
      const nodeName = `${object.name} ${object.parent?.name || ""}`;
      const isGlassShell = object.userData?.digital_twin_role === "outer_shell" || /component_(16|36|51|52)_/.test(nodeName) || nodeName.includes("400玻璃管");
      if (isGlassShell) {
        object.material = cadMaterials.glass;
        object.renderOrder = 5;
        REAL.shellMeshes.push(object);
        return;
      }
      object.material = /valve_or_sensor/.test(nodeName) ? cadMaterials.valve
        : /heater_frame/.test(nodeName) ? cadMaterials.heater
          : /support/.test(nodeName) ? cadMaterials.support
            : /desiccant/.test(nodeName) ? cadMaterials.desiccant
              : cadMaterials.structure;
      if (/component_26_/.test(nodeName)) REAL.upperValve = object;
      if (/component_40_/.test(nodeName)) REAL.drainValve = object;
      if (/component_(08|09|10|11|12|13|14|15|30)_/.test(nodeName)) {
        REAL.heatMeshes.push(object);
        heaterNode ||= object;
      }
      if (/component_(52|45)_/.test(nodeName)) oilCupNode ||= object;
    });
    cadModel.add(gltf.scene);
    cadModel.visible = true;
    cadModel.updateMatrixWorld(true);
    hideProceduralDevice();
    if (REAL.upperValve && REAL.drainValve) {
      REAL.upperValve.userData.baseX = REAL.upperValve.position.x;
      REAL.upperValve.userData.baseZ = REAL.upperValve.position.z;
      REAL.drainValve.userData.baseX = REAL.drainValve.position.x;
      REAL.drainValve.userData.baseZ = REAL.drainValve.position.z;
      buildRealProcessEffects(oilCupNode, heaterNode, REAL.upperValve, REAL.drainValve);
    }
    host.classList.add("digital-twin-cad-ready");
  }, undefined, error => {
    console.warn("真实总装模型加载失败，将使用简化数字孪生外观。", error);
  });
}

function value(point) { const n = Number(point?.value); return Number.isFinite(n) ? n : null; }
function valveState(valve) { return { position: value(valve?.position), moving: value(valve?.actuatorState) === 1, fault: value(valve?.faultReason) > 0 || value(valve?.actuatorState) === 2, label: valve?.position?.displayValue || "无有效数据" }; }
function outputState(snapshot, key) { return value((snapshot?.outputs || []).find(item => item.key === key)?.state); }
function setStatus(rows) { statusHost.innerHTML = rows.map(([name, text, state]) => `<div><dt>${name}</dt><dd class="${state || ""}">${text}</dd></div>`).join(""); }

function update(snapshot) {
  STATUS.snapshot = snapshot;
  const upper = valveState(snapshot?.valves?.[0]);
  const drain = valveState(snapshot?.valves?.[1]);
  STATUS.upperTarget = upper.position === 1 ? .23 : -.23;
  STATUS.drainTarget = drain.position === 1 ? .20 : -.20;
  const heat = outputState(snapshot, "htc1");
  const breath = value(snapshot?.process?.breathState);
  const online = value(snapshot?.communication?.online) === 1;
  const alarm = Boolean(snapshot?.alarms?.active);
  connectionNode.textContent = online ? (alarm ? "存在活动告警" : "实时数据") : "等待有效数据";
  connectionNode.className = `digital-twin-pill ${alarm ? "fault" : online ? "online" : "offline"}`;
  breathNode.textContent = `呼吸：${snapshot?.process?.breathState?.displayValue || "--"}`;
  upperCallout?.classList.toggle("active", upper.moving || upper.fault);
  heatCallout?.classList.toggle("active", heat === 1 || heat === 2 || heat === 3);
  drainCallout?.classList.toggle("active", drain.moving || drain.position === 1 || drain.fault);
  setStatus([["上阀", upper.fault ? "故障" : upper.moving ? "切换中" : upper.label, upper.fault ? "fault" : ""],["左排水阀", drain.fault ? "故障" : drain.moving ? "切换中" : drain.label, drain.fault ? "fault" : ""],["HTC1", heat === 1 ? "加热中" : heat === 2 ? "闪烁" : heat === 3 ? "切换中" : "关闭", heat === 1 ? "active" : ""],["气流", `${snapshot?.process?.flow?.displayValue ?? "--"} ${snapshot?.process?.flow?.unit || "L/min"}`, breath === 2 ? "" : "active"]]);
}

function resetView(){ STATUS.yaw=-.42; STATUS.pitch=.10; STATUS.distance=7.3; }
function resize(){ const width=host.clientWidth,height=host.clientHeight; if(!width||!height)return; renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix(); }
function animateRealProcess(now, snapshot) {
  if (!cadModel.visible || !REAL.upperValve || !REAL.drainValve) return;
  const upper = valveState(snapshot?.valves?.[0]);
  const drain = valveState(snapshot?.valves?.[1]);
  const heat = outputState(snapshot, "htc1");
  const breath = value(snapshot?.process?.breathState);
  const flow = Math.min(Math.abs(value(snapshot?.process?.flow)) || 0, 12);
  const phase = now * .001 * (.35 + flow * .16);
  const move = value => value === 1 ? .095 : -.095;
  const upperFocus = upper.moving || upper.fault;
  const drainFocus = drain.moving || drain.fault || drain.position === 1;
  REAL.upperValve.position.x += (REAL.upperValve.userData.baseX + move(upper.position) - REAL.upperValve.position.x) * .14;
  REAL.drainValve.position.x += (REAL.drainValve.userData.baseX + move(drain.position) - REAL.drainValve.position.x) * .14;
  REAL.upperValve.position.z += (REAL.upperValve.userData.baseZ + (upperFocus ? .24 : 0) - REAL.upperValve.position.z) * .12;
  REAL.drainValve.position.z += (REAL.drainValve.userData.baseZ + (drainFocus ? .24 : 0) - REAL.drainValve.position.z) * .12;
  REAL.upperValve.material = upper.fault ? materials.fault : (upper.moving ? cadMaterials.activeValve : cadMaterials.valve);
  REAL.drainValve.material = drain.fault ? materials.fault : (drain.moving ? cadMaterials.activeValve : cadMaterials.valve);
  REAL.heatMeshes.forEach(mesh => { mesh.material = heat === 1 ? materials.heated : cadMaterials.heater; });
  materials.heated.emissive.setHex(heat === 1 ? 0xf05a18 : 0x000000);
  materials.heated.emissiveIntensity = heat === 1 ? 1.1 : 0;
  const activeBreath = breath === 0 || breath === 1;
  REAL.airParticles.forEach(({ dot, path, offset }) => { const p = (phase + offset) % 1; dot.visible = activeBreath; dot.position.copy(path.getPointAt(breath === 0 ? p : 1 - p)); });
  const drainage = drain.position === 1 && !drain.fault;
  REAL.waterParticles.forEach(({ dot, path, offset }) => { dot.visible = drainage; dot.position.copy(path.getPointAt((phase * .46 + offset) % 1)); });
  REAL.steamParticles.forEach(({ puff, origin, offset }) => { const p = (phase * .38 + offset) % 1; puff.visible = heat === 1; puff.position.set(origin.x + .16 * Math.sin((p + offset) * 18), origin.y + p * .92, origin.z + .13 * Math.cos((p + offset) * 13)); puff.scale.setScalar(.70 + p * 1.25); puff.material.opacity = (1 - p) * .52; });
  REAL.heatWaves.forEach(({ wave, origin, offset }) => { const p = (phase * .8 + offset) % 1; wave.visible = heat === 1; wave.position.set(origin.x, origin.y + p * .54, origin.z); wave.scale.setScalar(.8 + p * 2.2); wave.material.opacity = (1 - p) * .62; });
  cadMaterials.glass.opacity = (upperFocus || drainFocus) ? .045 : .14;
  REAL.upperHalo.visible = upper.moving || upper.fault;
  REAL.upperHalo.material.color.setHex(upper.fault ? 0xef4444 : 0xfb7185);
  REAL.drainHalo.visible = drain.moving || drainage || drain.fault;
  REAL.drainHalo.material.color.setHex(drain.fault ? 0xef4444 : 0x4ade80);
  REAL.heatHalo.visible = heat === 1 || heat === 2 || heat === 3;
}

function animate(now=0){ requestAnimationFrame(animate); const snapshot=STATUS.snapshot; const upper=valveState(snapshot?.valves?.[0]); const drain=valveState(snapshot?.valves?.[1]); const heat=outputState(snapshot,"htc1"); const breath=value(snapshot?.process?.breathState); const flow=Math.min(Math.abs(value(snapshot?.process?.flow)) || 0, 12); const activeBreath=breath === 0 || breath === 1; const phase=now*.001*(.35+flow*.16); upperSlider.position.x += (STATUS.upperTarget-upperSlider.position.x)*.14; drainSlider.position.x += (STATUS.drainTarget-drainSlider.position.x)*.14; upperSlider.material=upper.fault?materials.fault:materials.metal;drainSlider.material=drain.fault?materials.fault:materials.metal; materials.heated.emissive.setHex(heat===1?0xf05a18:0x000000);materials.heated.emissiveIntensity=heat===1?1.55:0; heater.rotation.y+=heat===1?.012:0; airParticles.forEach(({dot,offset})=>{const p=activeBreath?((phase+offset)%1):offset;dot.visible=!cadModel.visible && activeBreath;dot.position.copy(airCurve.getPointAt(breath===0?p:1-p));}); const drainage=drain.position===1 && !drain.fault; waterParticles.forEach(({dot,offset})=>{dot.visible=!cadModel.visible && drainage;dot.position.copy(waterCurve.getPointAt((phase*.45+offset)%1));}); steamParticles.forEach(({puff,offset})=>{const p=(phase*.40+offset)%1;puff.visible=!cadModel.visible && heat===1;puff.position.set(.10*Math.sin((p+offset)*18),-1.25+p*2.70,.11*Math.cos((p+offset)*12));puff.scale.setScalar(.65+p*.9);puff.material.opacity=(1-p)*.28;}); animateRealProcess(now, snapshot); rig.rotation.y += (STATUS.yaw-rig.rotation.y)*.08;rig.rotation.x += (STATUS.pitch-rig.rotation.x)*.08;camera.position.set(0,0,STATUS.distance);camera.lookAt(0,0,0);renderer.render(scene,camera); }

host.addEventListener("pointerdown", event => { STATUS.dragging=true; STATUS.pointer={x:event.clientX,y:event.clientY}; host.setPointerCapture(event.pointerId); });
host.addEventListener("pointermove", event => { if(!STATUS.dragging||!STATUS.pointer)return; STATUS.yaw+=(event.clientX-STATUS.pointer.x)*.011;STATUS.pitch=Math.max(-.48,Math.min(.48,STATUS.pitch+(event.clientY-STATUS.pointer.y)*.008));STATUS.pointer={x:event.clientX,y:event.clientY}; });
host.addEventListener("pointerup", () => { STATUS.dragging=false;STATUS.pointer=null; });
host.addEventListener("wheel", event => { event.preventDefault(); STATUS.distance=Math.max(5.1,Math.min(10.5,STATUS.distance+event.deltaY*.006)); },{passive:false});
host.addEventListener("dblclick",resetView);resetButton?.addEventListener("click",resetView);new ResizeObserver(resize).observe(host);resize();loadCadAssembly();animate();
window.digitalTwin = { update, resetView };
