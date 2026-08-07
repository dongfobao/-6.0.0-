const host = document.getElementById("digitalTwinViewport");
const statusHost = document.getElementById("digitalTwinStatus");
const connectionNode = document.getElementById("digitalTwinConnection");
const breathNode = document.getElementById("digitalTwinBreath");
const resetButton = document.getElementById("resetDigitalTwinBtn");
const upperCallout = document.getElementById("twinUpperCallout");
const heatCallout = document.getElementById("twinHeatCallout");
const drainCallout = document.getElementById("twinDrainCallout");
// 单管设备的左侧温湿度为 T1/传感器 1，对应监控快照的第一路环境通道。
const LEFT_HUMIDITY_CHANNEL_INDEX = 0;

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
  air: new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: .94 }),
  water: new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: .74 }),
  fault: new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0x5f0000, emissiveIntensity: .7 }),
};
const cadMaterials = {
  structure: new THREE.MeshStandardMaterial({ color: 0x405567, metalness: .88, roughness: .23 }),
  valve: new THREE.MeshStandardMaterial({ color: 0x102b42, metalness: .90, roughness: .18 }),
  heater: new THREE.MeshStandardMaterial({ color: 0x743416, metalness: .72, roughness: .30 }),
  support: new THREE.MeshStandardMaterial({ color: 0x6d7781, metalness: .42, roughness: .46 }),
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
const REAL = { upperValve: null, drainValve: null, heatMeshes: [], shellMeshes: [], airParticles: [], lowerDiffusionParticles: [], silicaFlowParticles: [], upperDiffusionParticles: [], sensorParticles: [], heatBypassParticles: [], waterParticles: [], steamParticles: [], heatWaves: [], condensationDrops: [], valveDrops: [], airTube: null, sensorTube: null, heatBypassTube: null, upperHalo: null, drainHalo: null, heatHalo: null };

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

function buildRealProcessEffects(oilCoverNode, oilCupNode, heaterNode, upperValveNode, sensorNode, outletNode, drainValveNode) {
  const oilCover = centerOf(oilCoverNode || oilCupNode || drainValveNode);
  const oil = centerOf(oilCupNode || oilCoverNode || drainValveNode);
  const heaterCenter = centerOf(heaterNode || upperValveNode);
  const upper = centerOf(upperValveNode);
  const sensor = centerOf(sensorNode || upperValveNode);
  const outlet = centerOf(outletNode || sensorNode || upperValveNode);
  const drain = centerOf(drainValveNode);
  const frontOffset = new THREE.Vector3(0, 0, .16);
  const coreX = heaterCenter.x;
  const coreZ = heaterCenter.z + .16;
  const coreEntry = new THREE.Vector3(coreX, heaterCenter.y - .70, coreZ);
  const coreExit = new THREE.Vector3(coreX, upper.y - .18, coreZ);
  const upperChamber = new THREE.Vector3(coreX, upper.y + .38, coreZ);
  // 普通气体的通气孔全部使用竖直路径；玻璃罩内采用向外扩散、向内汇聚的粒子场。
  const airPath = new THREE.LineCurve3(coreEntry, coreExit);
  const sensorPath = new THREE.LineCurve3(upperChamber, new THREE.Vector3(coreX, outlet.y, coreZ));
  const waterPath = new THREE.CatmullRomCurve3([heaterCenter.clone().add(new THREE.Vector3(.45, .55, .18)), heaterCenter.clone().add(new THREE.Vector3(.58, -.65, .20)), drain.clone().add(frontOffset), oil.clone().add(frontOffset)]);
  const waterTubeReal = new THREE.Mesh(new THREE.TubeGeometry(waterPath, 72, .020, 8, false), new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: .46, depthTest: false, depthWrite: false }));
  realEffects.add(waterTubeReal);
  // 加热旁路是玻璃筒内的直通圆管：上阀反向接口直达油杯，不沿设备外侧布置。
  const bypassPort = upper.clone().add(new THREE.Vector3(-.24, -.03, .18));
  const bypassPipeX = oil.x + .48;
  const bypassPipeZ = oil.z + .22;
  const heatBypassPath = new THREE.CatmullRomCurve3([
    bypassPort,
    new THREE.Vector3(bypassPipeX, upper.y - .28, bypassPipeZ),
    new THREE.Vector3(bypassPipeX, oil.y + .20, bypassPipeZ),
    oil.clone().add(new THREE.Vector3(.14, 0, .18)),
  ]);
  const heatBypassHousing = new THREE.Mesh(new THREE.TubeGeometry(heatBypassPath, 84, .052, 12, false), new THREE.MeshStandardMaterial({ color: 0x738394, metalness: .84, roughness: .24, transparent: true, opacity: .48, depthTest: false, depthWrite: false }));
  const heatBypassTube = new THREE.Mesh(new THREE.TubeGeometry(heatBypassPath, 84, .028, 8, false), new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: .08, depthTest: false, depthWrite: false }));
  realEffects.add(heatBypassHousing, heatBypassTube);
  REAL.heatBypassTube = heatBypassTube;
  // 中间无硅胶气道使用圆点平流，不使用锥形箭头。
  REAL.airParticles = Array.from({ length: 20 }, (_, index) => {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(.025, 8, 8), new THREE.MeshBasicMaterial({ color: 0xa5f3fc, transparent: true, opacity: .94, depthTest: false, depthWrite: false }));
    dot.renderOrder = 20;
    realEffects.add(dot);
    return { dot, path: airPath, offset: index / 20 };
  });
  // 壁缝为一指宽的环形上升通道，半径仅作微小随机扰动。
  REAL.lowerDiffusionParticles = Array.from({ length: 48 }, (_, index) => {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(.018 + (index % 3) * .004, 8, 8), new THREE.MeshBasicMaterial({ color: 0x67e8f9, transparent: true, opacity: .82, depthTest: false, depthWrite: false }));
    dot.renderOrder = 19;
    realEffects.add(dot);
    return { dot, start: coreEntry.clone(), end: coreExit.clone(), angle: index * 2.399, offset: index / 48, radiusOffset: ((index * .618) % 1 - .5) * .040 };
  });
  // 硅胶床内的气体以较慢速度向中心渗流，保留整个圆柱体的孔隙感。
  REAL.silicaFlowParticles = Array.from({ length: 58 }, (_, index) => {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(.015 + (index % 3) * .003, 8, 8), new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: .44, depthTest: false, depthWrite: false }));
    dot.renderOrder = 18;
    realEffects.add(dot);
    return { dot, start: coreEntry.clone(), end: coreExit.clone(), angle: index * 2.399, offset: index / 58, heightOffset: (index * .382) % 1 };
  });
  REAL.upperDiffusionParticles = Array.from({ length: 42 }, (_, index) => {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(.028 + (index % 3) * .006, 8, 8), new THREE.MeshBasicMaterial({ color: 0x7dd3fc, transparent: true, opacity: .78, depthTest: false, depthWrite: false }));
    dot.renderOrder = 19;
    realEffects.add(dot);
    return { dot, origin: upperChamber.clone(), angle: index * 2.399, offset: index / 42 };
  });
  REAL.sensorParticles = Array.from({ length: 8 }, (_, index) => {
    const dot = new THREE.Mesh(new THREE.ConeGeometry(.052, .17, 8), new THREE.MeshBasicMaterial({ color: 0xa5f3fc, transparent: true, opacity: .96, depthTest: false, depthWrite: false }));
    dot.renderOrder = 20;
    realEffects.add(dot);
    return { dot, path: sensorPath, offset: index / 8 };
  });
  REAL.heatBypassParticles = Array.from({ length: 18 }, (_, index) => {
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(.042, .13, 8), new THREE.MeshBasicMaterial({ color: 0xfbbf24, transparent: true, opacity: .95, depthTest: false, depthWrite: false }));
    realEffects.add(arrow);
    return { arrow, path: heatBypassPath, offset: index / 18 };
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
  const condensationOrigin = heaterCenter.clone();
  REAL.condensationDrops = Array.from({ length: 28 }, (_, index) => {
    const drop = new THREE.Mesh(new THREE.SphereGeometry(.020 + (index % 4) * .004, 8, 8), new THREE.MeshBasicMaterial({ color: 0x7dd3fc, transparent: true, opacity: .72, depthTest: false, depthWrite: false }));
    realEffects.add(drop);
    return { drop, origin: condensationOrigin.clone(), angle: -.86 + (index % 9) * .215, offset: index / 28 };
  });
  const valveOutlet = drain.clone().add(new THREE.Vector3(0, -.06, .26));
  const valveHole = new THREE.Mesh(new THREE.CircleGeometry(.070, 18), new THREE.MeshBasicMaterial({ color: 0x082f49, transparent: true, opacity: .88, depthTest: false, depthWrite: false }));
  valveHole.position.copy(valveOutlet);
  realEffects.add(valveHole);
  REAL.valveDrops = Array.from({ length: 9 }, (_, index) => {
    const drop = new THREE.Mesh(new THREE.SphereGeometry(.024 + (index % 3) * .006, 8, 8), new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: .86, depthTest: false, depthWrite: false }));
    realEffects.add(drop);
    return { drop, origin: valveOutlet.clone(), offset: index / 9 };
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
  new THREE.GLTFLoader().load("/assets/yldq-5-single-pipe.glb?v=4", gltf => {
    let oilCoverNode = null;
    let oilCupNode = null;
    let heaterNode = null;
    let sensorNode = null;
    let outletNode = null;
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
      if (/component_45_/.test(nodeName) && !oilCoverNode) oilCoverNode = object;
      if (/component_52_/.test(nodeName) && !oilCupNode) oilCupNode = object;
      if (/component_(23|24|25)_/.test(nodeName) && !sensorNode) sensorNode = object;
      if (/component_(01|02|18|19)_/.test(nodeName) && !outletNode) outletNode = object;
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
      buildRealProcessEffects(oilCoverNode, oilCupNode, heaterNode, REAL.upperValve, sensorNode, outletNode, REAL.drainValve);
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
  upperCallout?.classList.toggle("active", upper.position === 1 || upper.moving || upper.fault);
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
  const flow = Math.min(Math.abs(value(snapshot?.process?.flow)) || 0, 30);
  const measuredFlow = flow >= .12;
  // 实时流量直接决定气体箭头在设备内上下穿梭的速度，低流量仍保留可辨识的缓慢运动。
  const phase = now * .001 * (.20 + flow * .55);
  const leftHumidity = value(snapshot?.environmentChannels?.[LEFT_HUMIDITY_CHANNEL_INDEX]?.humidity);
  const humidityFactor = leftHumidity === null ? .35 : Math.max(.06, Math.min(1, (leftHumidity - 30) / 60));
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
  const airflowActive = activeBreath || measuredFlow;
  // 阀位未知时不假定阀门已到工作位；只有流量计实际检测到气流才展示观测到的通路。
  const upperWorkPath = !upper.fault && (upper.position === 1 || (upper.position === 2 && measuredFlow));
  const heatingBypass = heat === 1;
  const normalFlowPath = upperWorkPath && !heatingBypass;
  if (REAL.airTube) REAL.airTube.material.opacity = .08;
  if (REAL.sensorTube) REAL.sensorTube.material.opacity = .08;
  if (REAL.airTube && normalFlowPath && airflowActive) REAL.airTube.material.opacity = .96;
  if (REAL.sensorTube && normalFlowPath && airflowActive) REAL.sensorTube.material.opacity = .88;
  if (REAL.airTube && normalFlowPath && !airflowActive) REAL.airTube.material.opacity = .42;
  if (REAL.sensorTube && normalFlowPath && !airflowActive) REAL.sensorTube.material.opacity = .38;
  const flowDirection = breath === 0 ? 1 : breath === 1 ? -1 : (value(snapshot?.process?.flow) || 0) >= 0 ? 1 : -1;
  REAL.airParticles.forEach(({ dot, path, offset }) => { const p = (phase + offset) % 1; const pathPoint = flowDirection === 1 ? p : 1 - p; const tangent = path.getTangentAt(pathPoint).multiplyScalar(flowDirection).normalize(); dot.visible = normalFlowPath && airflowActive; dot.position.copy(path.getPointAt(pathPoint)); dot.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent); dot.scale.setScalar(.82 + Math.min(flow, 8) * .055); });
  REAL.lowerDiffusionParticles.forEach(({ dot, start, end, angle, offset, radiusOffset }) => { const p = (phase * .34 + offset) % 1; const routeP = flowDirection === 1 ? p : 1 - p; const radius = .52 + radiusOffset; dot.visible = normalFlowPath && airflowActive; dot.position.set(start.x + Math.sin(angle) * radius, THREE.MathUtils.lerp(start.y, end.y, routeP), start.z + Math.cos(angle) * radius); dot.scale.setScalar(.82); dot.material.opacity = .82; });
  REAL.silicaFlowParticles.forEach(({ dot, start, end, angle, offset, heightOffset }) => { const p = (phase * .11 + offset) % 1; const inwardP = flowDirection === 1 ? p : 1 - p; const radius = THREE.MathUtils.lerp(.46, .13, inwardP); const y = THREE.MathUtils.lerp(start.y + .10, end.y - .10, heightOffset); dot.visible = normalFlowPath && airflowActive; dot.position.set(start.x + Math.sin(angle) * radius, y, start.z + Math.cos(angle) * radius); dot.scale.setScalar(.76 + inwardP * .22); dot.material.opacity = .26 + inwardP * .42; });
  REAL.upperDiffusionParticles.forEach(({ dot, origin, angle, offset }) => { const p = (phase * .34 + offset) % 1; const routeP = flowDirection === 1 ? p : 1 - p; const spread = routeP < .54 ? routeP / .54 : 1 - (routeP - .54) / .46; const radius = .10 + spread * .56; dot.visible = normalFlowPath && airflowActive; dot.position.set(origin.x + Math.sin(angle) * radius, origin.y + (routeP - .35) * .72, origin.z + Math.cos(angle) * radius); dot.scale.setScalar(.58 + spread * .78); dot.material.opacity = .24 + spread * .54; });
  REAL.sensorParticles.forEach(({ dot, path, offset }) => { const p = (phase * .90 + offset) % 1; const pathPoint = flowDirection === 1 ? p : 1 - p; const tangent = path.getTangentAt(pathPoint).multiplyScalar(flowDirection).normalize(); dot.visible = normalFlowPath && airflowActive; dot.position.copy(path.getPointAt(pathPoint)); dot.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent); });
  if (REAL.heatBypassTube) REAL.heatBypassTube.material.opacity = heatingBypass ? .88 : .06;
  REAL.heatBypassParticles.forEach(({ arrow, path, offset }) => { const p = (phase * .72 + offset) % 1; const tangent = path.getTangentAt(p).normalize(); arrow.visible = heatingBypass; arrow.position.copy(path.getPointAt(p)); arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent); });
  const drainage = drain.position === 1 && !drain.fault;
  REAL.waterParticles.forEach(({ dot, path, offset }) => { dot.visible = drainage; dot.position.copy(path.getPointAt((phase * (.22 + humidityFactor * .34) + offset) % 1)); });
  REAL.steamParticles.forEach(({ puff, origin, offset }) => { const p = (phase * .22 + offset) % 1; const radius = .18 + p * (.30 + humidityFactor * .20); puff.visible = heat === 1 && humidityFactor > .08; puff.position.set(origin.x + radius * Math.sin((p + offset) * 12), origin.y + .10 + p * (1.00 + humidityFactor * .42), origin.z + radius * Math.cos((p + offset) * 10)); puff.scale.setScalar((.54 + p * 1.15) * (.60 + humidityFactor * .72)); puff.material.opacity = (1 - p) * (.15 + humidityFactor * .48); });
  REAL.heatWaves.forEach(({ wave, origin, offset }) => { const p = (phase * .34 + offset) % 1; wave.visible = heat === 1; wave.position.set(origin.x, origin.y + p * (.58 + humidityFactor * .25), origin.z); wave.scale.setScalar(.72 + p * (1.65 + humidityFactor)); wave.material.opacity = (1 - p) * (.30 + humidityFactor * .42); });
  REAL.condensationDrops.forEach(({ drop, origin, angle, offset }) => { const p = (phase * (.10 + humidityFactor * .16) + offset) % 1; const wallRadius = .57; drop.visible = heat === 1 && humidityFactor > .08; drop.position.set(origin.x + Math.sin(angle) * wallRadius, origin.y + .72 - p * 1.46, origin.z + Math.cos(angle) * wallRadius); drop.scale.setScalar(.56 + humidityFactor * .92); drop.material.opacity = .18 + humidityFactor * .66; });
  REAL.valveDrops.forEach(({ drop, origin, offset }) => { const p = (phase * (.10 + humidityFactor * .18) + offset) % 1; drop.visible = drainage && heat === 1 && humidityFactor > .08; drop.position.set(origin.x + Math.sin(offset * 31) * .035, origin.y - p * (.20 + humidityFactor * .35), origin.z); drop.scale.setScalar(.54 + humidityFactor); drop.material.opacity = .28 + humidityFactor * .62; });
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
