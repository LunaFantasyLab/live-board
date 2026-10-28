// 「机器人工作室」：读 Blender 导出的 /studio6.glb（顶点色，meshopt 压缩）。
// 风格：原创的高对比漫画风（红 / 黑 / 白高对比、硬边两档卡通明暗、粗黑描边、斜切、星芒），不使用任何第三方素材。
// 立体：透视相机低机位（约 29° 俯角）+ 后排抬高错位 + 有厚度的地台和墙 + 硬阴影；镜头慢慢环绕 / 推拉，交接时镜头「冲」一下。
// 帧率：不再锁 30 帧，跟随 requestAnimationFrame（屏幕刷新率是多少就跑多少，120Hz 屏就是 120 帧）；
//   所有动画都按真实时间差 dt 推进，帧率高低只影响细腻度，不影响速度；页面隐藏时停画；
//   性能：一次 render 约 200 次绘制、无后期、阴影图 2048×1024、像素比最高 2（持续掉帧时自动降到 1.5 / 1.25）、拾取节流到每帧最多一次。
// 全部动态：空闲＝呼吸、眨眼、张望、摆弄道具、偶尔摆个造型；未激活＝褪成浅灰、缩进工位打盹、冒「Z」；
//   工作中＝按道具做夸张的忙碌动作，眼睛和天线灯变红、灯快闪；待你确认＝举手 +「?」；退回 / 报错＝摇头 +「!」。
//   交接＝红色卡片旋转飞过去，退回＝黑卡红边。
// 减少动态（系统设置）：全部静止，只在数据变化时重画一帧。
// ?debug：右下角显示 fps / 每帧 CPU 毫秒 / 绘制次数，并暴露 window.__boardScene 给自测脚本。
import * as THREE from "three";
import { t as tr } from "./i18n.js";   // 场景里 t 是动画时间，翻译函数改叫 tr
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { mergeVertices } from "three/examples/jsm/utils/BufferGeometryUtils.js";

export const PAL = { red: "#E5121D", dred: "#8E0B12", black: "#0E0E10", white: "#F3F1EC", pure: "#FFFFFF", grey: "#BDB8B0" };
// 成员列表小方块等用的状态色
export const LAMP = { work: PAL.red, wait: PAL.red, confirm: PAL.pure, back: PAL.black, error: PAL.black };

// 6 工位模式（实况）：opts.slots = 6 个成员名（工位 1–6 坐谁），读 /studio6.glb；assign() 可随时换人。
// 本项目只用 6 工位模式（studio6.glb）。
export async function createScene(host, roster, { onPick, model, slots, labelOf } = {}) {
  const SLOT = Array.isArray(slots);
  // 工位模式下名单可能晚到：还没人坐的工位先用占位名建好骨架，assign() 时再换成成员名
  const HOLD = "\u0000slot";
  const keyOf = (idx) => (SLOT ? slots[idx] || HOLD + idx : roster[idx]?.name);
  const Q = new URLSearchParams(location.search);
  const DEBUG = Q.has("debug");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance", stencil: false });
  const DPR_MAX = Math.min(devicePixelRatio || 1, Number(Q.get("dpr")) || 2);
  let dpr = DPR_MAX; renderer.setPixelRatio(dpr);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
  host.appendChild(renderer.domElement);
  renderer.domElement.setAttribute("aria-hidden", "true");

  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(26, 2, 1, 120);
  const HOME = { target: new THREE.Vector3(1.1, 0.75, 0.2), dir: new THREE.Vector3(0.16, 0.56, 1.0).normalize(), dist: 34 };
  const placeCam = (d) => cam.position.copy(HOME.target).addScaledVector(HOME.dir, d);
  placeCam(HOME.dist); cam.lookAt(HOME.target);

  // 光：天光打底 + 一盏硬太阳（从左前上方来，影子往右后方落在白地板上）
  scene.add(new THREE.HemisphereLight("#FFFFFF", "#E8E4DE", 1.25));
  const sun = new THREE.DirectionalLight("#FFFFFF", 2.0);
  sun.position.set(-9, 15, 10); sun.target.position.set(1.1, 0, 0); scene.add(sun, sun.target);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 1024); sun.shadow.bias = -0.0006; sun.shadow.normalBias = 0.025; sun.shadow.radius = 1;
  Object.assign(sun.shadow.camera, { left: -15, right: 15, top: 9, bottom: -9, near: 2, far: 50 });
  sun.shadow.autoUpdate = true;

  const controls = new OrbitControls(cam, renderer.domElement);
  controls.target.copy(HOME.target);
  controls.enablePan = false; controls.enableDamping = true; controls.dampingFactor = 0.1;
  controls.minDistance = HOME.dist * 0.55; controls.maxDistance = HOME.dist * 1.15;
  const az0 = Math.atan2(HOME.dir.x, HOME.dir.z);
  controls.minAzimuthAngle = az0 - 0.45; controls.maxAzimuthAngle = az0 + 0.45;
  controls.minPolarAngle = 0.75; controls.maxPolarAngle = 1.35;
  controls.update();

  // 卡通着色：两档硬明暗（亮面 = 原色，暗面 ≈ 55%）；每个机器人一份材质，未激活时褪成浅灰
  const grad = new THREE.DataTexture(new Uint8Array([60, 60, 60, 255, 255, 255, 255, 255]), 2, 1, THREE.RGBAFormat);
  grad.minFilter = grad.magFilter = THREE.NearestFilter; grad.needsUpdate = true;
  const FADE = new THREE.Color(PAL.grey);
  function toon() {
    const m = new THREE.MeshToonMaterial({ vertexColors: true, gradientMap: grad });
    m.userData.fade = { value: 0 }; m.userData.glow = { value: 0 };
    m.onBeforeCompile = (sh) => {
      sh.uniforms.uFade = m.userData.fade; sh.uniforms.uPaper = { value: FADE }; sh.uniforms.uGlow = m.userData.glow;
      sh.fragmentShader = sh.fragmentShader
        .replace("#include <common>", "#include <common>\nuniform float uFade; uniform vec3 uPaper; uniform float uGlow;")
        .replace("#include <color_fragment>", "#include <color_fragment>\n{ float l = dot(diffuseColor.rgb, vec3(0.299,0.587,0.114)); vec3 pale = uPaper * (0.72 + 0.4 * l); diffuseColor.rgb = mix(diffuseColor.rgb, pale, uFade * 0.88); }")
        .replace("#include <opaque_fragment>", "outgoingLight = mix(outgoingLight, diffuseColor.rgb * 1.05, uGlow);\n#include <opaque_fragment>");
    };
    return m;
  }

  // 墨线：反向外壳，按屏幕像素加粗（粗黑描边），缩放时线宽不变
  const res = new THREE.Vector2(1, 1);
  const inkMat = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    uniforms: { uPx: { value: 2.4 }, uRes: { value: res }, uColor: { value: new THREE.Color(PAL.black) } },
    vertexShader: `uniform float uPx; uniform vec2 uRes; attribute vec3 sn;
      void main(){ vec4 c = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        vec3 n = normalize(normalMatrix * sn); vec2 d = n.xy; float l = length(d); if (l > 1e-4) d /= l;
        c.xy += d * uPx * 2.0 / uRes * c.w; c.z += 0.0006 * c.w; gl_Position = c; }`,
    fragmentShader: `uniform vec3 uColor; void main(){ gl_FragColor = vec4(uColor, 1.0); }`,
  });
  const inkCache = new Map();
  function inkFor(px, color) {
    const k = px + "|" + (color || ""); if (inkCache.has(k)) return inkCache.get(k);
    const m = inkMat.clone(); m.uniforms.uPx = { value: px }; m.uniforms.uRes = { value: res };
    if (color) m.uniforms.uColor = { value: new THREE.Color(color) };
    inkCache.set(k, m); return m;
  }
  function addInk(mesh, px, color) {
    const src = mesh.geometry, p = src.attributes.position, n = p.count;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) { pos[i * 3] = p.getX(i); pos[i * 3 + 1] = p.getY(i); pos[i * 3 + 2] = p.getZ(i); }
    let g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); if (src.index) g.setIndex(src.index.clone());
    g = mergeVertices(g, 1e-3); g.computeVertexNormals(); g.setAttribute("sn", g.attributes.normal);
    const o = new THREE.Mesh(g, inkFor(px, color)); o.renderOrder = -1; o.raycast = () => {}; mesh.add(o); return o;
  }

  const loader = new GLTFLoader(); loader.setMeshoptDecoder(MeshoptDecoder);
  const gltf = await loader.loadAsync(model || "/studio6.glb");
  const world = new THREE.Group(); scene.add(world);
  const root = gltf.scene; world.add(root);
  const bots = {}; const meshes = [];
  root.traverse((o) => { if (o.isMesh) meshes.push(o); });
  // 每个成员手里的道具 → 忙碌时的动作类型（顺序与 Blender 里 PROPS 一致）
  const ACT = SLOT ? ["tap", "write", "talk", "look", "tap", "tap"] : ["lead", "tap", "write", "write", "talk", "tap", "tap", "look", "tap", "tap", "tap", "tap", "look", "sweep"];
  const slotObjs = [];
  const RX = /^(body|head|eye|lamp|arml|armr)_(\d\d)$/;
  const deco = { pens: [], hands: {} };
  root.traverse((o) => {            // 先按节点名找骨架（会动的部件都是以转轴为原点的空节点，网格挂在子节点下）
    let m = o.name.match(/^pen_(\d\d)$/); if (m) { deco.pens.push({ o, rx: o.rotation.x, k: Number(m[1]) }); return; }
    m = o.name.match(/^hand_([mh])$/); if (m) { deco.hands[m[1]] = { o, rz: o.rotation.z }; return; }
    m = o.name.match(RX); if (!m) return;
    const idx = Number(m[2]) - 1, nm = keyOf(idx); if (!nm) return;
    if (!bots[nm]) { bots[nm] = { name: nm, idx, act: ACT[idx] || "tap", phase: Math.random() * 6.28, sink: 0, sinkTo: 0, mats: [], pick: [] }; slotObjs[idx] = bots[nm]; }
    bots[nm][m[1]] = o;
  });
  const pickables = [];
  const envMat = new THREE.MeshToonMaterial({ vertexColors: true, gradientMap: grad });
  for (const o of meshes) {
    if (o.name === "env") { o.material = envMat; o.receiveShadow = true; o.castShadow = false; addInk(o, 1.8); continue; }
    let a = o, m = null; while (a && !(m = a.name.match(RX)) && !/^(pen|hand)_/.test(a.name)) a = a.parent;
    if (a && !m) { o.material = envMat; if (/^hand_/.test(a.name)) addInk(o, 1.4); continue; }   // 彩旗不描边（省绘制），钟针描边
    if (!m) { o.material = envMat; o.receiveShadow = true; addInk(o, 1.8); continue; }          // 工位
    const s = slotObjs[Number(m[2]) - 1]; if (!s) continue;
    const kind = m[1];
    o.userData.bot = s.name; s.pick.push(o);
    if (kind === "lamp" || kind === "eye") {
      const base = new THREE.Color().fromBufferAttribute(o.geometry.attributes.color, 0);
      o.material = new THREE.MeshBasicMaterial({ color: base }); s[kind + "Mat"] = o.material; s[kind + "Base"] = base;
      if (kind === "lamp") addInk(o, 1.6);
    } else {
      o.material = toon(); s.mats.push(o.material); o.castShadow = true; o.receiveShadow = true; pickables.push(o);
      addInk(o, 2.4);
    }
  }
  const AX = ["x", "y", "z"];
  for (const s of Object.values(bots)) {
    s.y0 = s.body.position.y; s.headRot = s.head.rotation.clone(); s.headY = s.head.position.y; s.bodyRot = s.body.rotation.clone();
    s.K = SLOT ? 1 : s.name.startsWith("1-") ? 1.22 : 1; s.eyeS = s.eye.scale.clone(); s.lampS = s.lamp.scale.clone();
    s.qL = s.arml.quaternion.clone(); s.qR = s.armr.quaternion.clone();
    let best = 0; AX.forEach((ax, k) => { const v = new THREE.Vector3().setComponent(k, 1).applyQuaternion(s.eye.quaternion); if (Math.abs(v.y) > Math.abs(new THREE.Vector3().setComponent(best, 1).applyQuaternion(s.eye.quaternion).y)) best = k; });
    s.eyeAx = AX[best];
    const r = (a, b) => a + Math.random() * (b - a);
    Object.assign(s, { tBlink: r(0.5, 4), tLook: r(2, 9), tFid: r(3, 10), tLamp: r(1, 5), tZ: r(0.3, 3), tNod: r(4, 9), nod: -9, look: 0, lookTo: 0, fid: -9, fidKind: 0, flash: -9, blink: -9 });
  }

  // 实况待机：每个工位桌面上一块「屏幕微光」（纯装饰，和工作状态无关；未激活的工位更暗）
  const glows = [];
  if (SLOT) {
    const gt = (() => { const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d");
      const rg = g.createRadialGradient(32, 32, 2, 32, 32, 31); rg.addColorStop(0, "rgba(255,255,255,1)"); rg.addColorStop(0.35, "rgba(255,235,230,.55)"); rg.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = rg; g.fillRect(0, 0, 64, 64); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; })();
    root.updateMatrixWorld(true);
    slotObjs.forEach((s, i) => {
      const m = new THREE.SpriteMaterial({ map: gt, color: i % 2 ? PAL.pure : "#FF6A5E", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.3 });
      const sp = new THREE.Sprite(m); const p = s.body.getWorldPosition(new THREE.Vector3());
      sp.position.set(p.x + 0.25, p.y + 1.02, p.z + 0.62); sp.scale.setScalar(1.1); sp.renderOrder = 5; scene.add(sp);
      glows.push({ s, sp, m, ph: Math.random() * 9, glitch: 0 });
    });
  }
  function moveGlows(t) {
    for (const g of glows) {
      const base = g.s.off ? 0.1 : 0.26;
      if (Math.random() < 0.004) g.glitch = t;                         // 偶尔「滋」一下
      const gl = t - g.glitch < 0.18 ? (Math.sin((t - g.glitch) * 90) > 0 ? 0.25 : -0.15) : 0;
      g.m.opacity = Math.max(0, base + 0.07 * Math.sin(t * 2.3 + g.ph) + 0.04 * Math.sin(t * 7.1 + g.ph * 2) + gl);
    }
  }
  // 实况：墙上挂钟走本机时间
  const fmtClock = new Intl.DateTimeFormat("en-GB", { timeZone: window.__LIVEBOARD_TZ || undefined, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

  // 打盹的「Z」：白字粗黑边，从头顶飘起、变大、淡出
  const zTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d");
    g.font = "900 52px Anton, Impact, system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.lineJoin = "round"; g.lineWidth = 10; g.strokeStyle = PAL.black; g.strokeText("Z", 32, 34); g.fillStyle = PAL.pure; g.fillText("Z", 32, 34);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  const zs = [];
  for (let k = 0; k < 16; k++) {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: zTex, transparent: true, depthWrite: false, opacity: 0 }));
    sp.visible = false; sp.renderOrder = 10; scene.add(sp); zs.push({ sp, t0: -1, p: new THREE.Vector3() });
  }
  function spawnZ(s, t) {
    const z = zs.find((q) => q.t0 < 0); if (!z) return;
    s.head.getWorldPosition(z.p); z.p.x += 0.4 * s.K; z.p.y += 0.95 * s.K; z.t0 = t; z.sp.visible = true;
  }

  // 碎纸片：红 / 黑 / 白三角形慢慢飘过（一次绘制）
  const NB = 14, triGeo = new THREE.BufferGeometry();
  triGeo.setAttribute("position", new THREE.Float32BufferAttribute([0, 0.14, 0, -0.12, -0.08, 0, 0.12, -0.08, 0], 3));
  const scraps = new THREE.InstancedMesh(triGeo, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }), NB);
  scraps.frustumCulled = false; scene.add(scraps);
  const SC_COL = [PAL.red, PAL.black, PAL.pure, PAL.red, PAL.black, PAL.red, PAL.pure, PAL.red, PAL.black, PAL.red, PAL.pure, PAL.red, PAL.black, PAL.red];
  const sc = [...Array(NB)].map(() => ({ x: -10 + Math.random() * 22, y: 2.2 + Math.random() * 1.8, z: -3.2 + Math.random() * 6.4, v: 0.25 + Math.random() * 0.3, ph: Math.random() * 6.28, sp: 0.8 + Math.random() }));
  sc.forEach((_, k) => scraps.setColorAt(k, new THREE.Color(SC_COL[k])));
  const M4b = new THREE.Matrix4(), Qb = new THREE.Quaternion(), Eb = new THREE.Euler(), S1 = new THREE.Vector3(1, 1, 1), Pb = new THREE.Vector3();
  function moveScraps(t, dt) {
    for (let k = 0; k < NB; k++) {
      const p = sc[k]; p.x += p.v * dt; if (p.x > 12.5) { p.x = -10.5; p.z = -3.2 + Math.random() * 6.4; p.y = 2.2 + Math.random() * 1.8; }
      Pb.set(p.x, p.y + Math.sin(t * 0.9 * p.sp + p.ph) * 0.35, p.z + Math.sin(t * 0.5 + p.ph) * 0.3);
      Eb.set(t * 1.6 * p.sp + p.ph, t * 1.1 * p.sp, Math.sin(t + p.ph)); Qb.setFromEuler(Eb);
      M4b.compose(Pb, Qb, S1); scraps.setMatrixAt(k, M4b);
    }
    scraps.instanceMatrix.needsUpdate = true;
  }
  moveScraps(0, 0);

  // 标签：斜切小黑牌
  const labels = document.createElement("div"); labels.className = "labels" + (SLOT ? " slotted" : ""); host.appendChild(labels);
  const lab = {};
  // 名牌按需创建（名单是运行时从数据源读的，可能晚于场景到达）；文字一律走 textContent
  function ensureLab(name) {
    let el = lab[name];
    if (!el) {
      el = document.createElement("span"); el.className = "lab"; el.hidden = true;
      el.append(document.createElement("b"), document.createElement("em"));
      labels.appendChild(el); lab[name] = el;
      if (SLOT) { el.dataset.bot = name; el.addEventListener("click", (e) => { e.stopPropagation(); onPick?.(name, { label: true }); }); }
    }
    el.querySelector("em").textContent = (labelOf && labelOf(name)) || name;
    return el;
  }
  for (const b of roster) ensureLab(b.name);

  let hover = null, dirty = true;
  let raf = 0, visible = !document.hidden, t = 0, lastNow = performance.now();
  let running = false;
  const RED = new THREE.Color(PAL.red), WHITE = new THREE.Color(PAL.pure), GREYC = new THREE.Color(PAL.grey), BLACKC = new THREE.Color(PAL.black);
  function setStates(map) {
    for (const [name, s] of Object.entries(bots)) {
      const st = map[name] || { group: "off", st: "none" };
      s.off = st.group === "off"; s.on = st.group === "on"; s.st = st.st;
      s.busy = s.on && (st.st === "work" || st.st === "wait");
      s.sinkTo = s.off ? 0.3 * s.K : 0;
      for (const mt of s.mats) { mt.userData.fade.value = s.off ? 1 : 0; mt.userData.glow.value = s.busy ? 0.1 : 0; }
      s.eyeMat.color.copy(s.busy ? RED : s.off ? GREYC : WHITE);
      if (reduce) { s.sink = s.sinkTo; pose(s, 0, 0); }
    }
    dirty = true; wake();
  }

  // ---------- 动作（夸张） ----------
  const qX = new THREE.Quaternion(), eX = new THREE.Euler();
  function arm(o, base, rx, rz = 0) { eX.set(rx, 0, rz); o.quaternion.copy(base).premultiply(qX.setFromEuler(eX)); }
  const ease = (k) => (k <= 0 || k >= 1 ? 0 : Math.sin(Math.PI * k));
  const POSES = [[-2.9, 0.35, 0.4, -0.5, 0.35, -0.09, -0.45, -0.12], [-1.5, 1.1, -1.5, -1.1, -0.3, 0.08, 0.4, -0.15], [-2.6, -0.25, -2.6, 0.25, 0.15, 0, 0, -0.28]];
  const snap = (k) => (k <= 0 || k >= 1 ? 0 : Math.min(1, k * 6) * Math.min(1, (1 - k) * 4));   // 快进、停住、再回去（摆造型）
  const rnd = (a, b) => a + Math.random() * (b - a);
  function pose(s, t, dt) {
    let hy = 0, rx = 0, ry = 0, rz = 0, bob = 0, by = 0, bz = 0, aL = 0, aR = 0, zL = 0, zR = 0, eye = 1, lamp = 1, lampHot = 0;
    const w = t + s.phase;
    if (reduce) {
      if (s.off) { rz = 0.2; eye = 0.18; }
    } else if (s.off) {                             // 打盹
      const br = Math.sin(w * 1.25);
      hy = br * 0.03; rz = 0.24 + Math.sin(w * 0.6) * 0.08; rx = -0.06 + br * 0.03; eye = 0.14; bz = Math.sin(w * 0.6) * 0.03;
      aL = 0.06 + br * 0.05; aR = 0.06 + br * 0.05;
      if (t > s.tZ) { spawnZ(s, t); s.tZ = t + rnd(1.6, 3.2); }
      if (SLOT) {                                   // 实况待机（未激活）：打瞌睡点头——头越垂越低，猛一下惊醒、眼睛睁一下又眯回去
        if (t > s.tNod) { s.nod = t; s.tNod = t + rnd(6, 11); }
        const k = (t - s.nod) / 2.4;
        if (k > 0 && k < 1) { const drop = k < 0.75 ? Math.sin((k / 0.75) * Math.PI / 2) : 1 - (k - 0.75) / 0.25 * 1.4; rx += 0.32 * Math.max(-0.25, drop); if (k > 0.75 && k < 0.9) { eye = 0.85; hy += 0.04; } }
      }
    } else if (s.busy) {                            // 忙碌：动作跟着道具走，幅度放大
      const W = w;
      bob = Math.abs(Math.sin(W * 3.4)) * 0.06;
      lamp = 1 + 0.5 * Math.max(0, Math.sin(W * 8)); lampHot = Math.max(0, Math.sin(W * 8));
      switch (s.act) {
        case "tap":   aL = -0.7 + Math.sin(W * 14) * 0.3; aR = -0.7 + Math.sin(W * 14 + Math.PI) * 0.3; rx = 0.18 + Math.sin(W * 7) * 0.06; ry = Math.sin(W * 0.9) * 0.2; bz = Math.sin(W * 7) * 0.035; break;
        case "write": aR = -0.9 + Math.sin(W * 7) * 0.35; zR = Math.sin(W * 3.5) * 0.5; aL = -0.3; rx = 0.14; ry = Math.sin(W * 3.5) * 0.25; rz = Math.sin(W * 7) * 0.06; by = Math.sin(W * 3.5) * 0.12; break;
        case "look":  aR = -1.3 + Math.sin(W * 2.2) * 0.25; zR = Math.sin(W * 1.1) * 0.2; rx = 0.14 + Math.sin(W * 2.2) * 0.12; ry = Math.sin(W * 1.1) * 0.5; aL = -0.2; bz = Math.sin(W * 1.1) * 0.08; break;
        case "talk":  rx = Math.sin(W * 4.5) * 0.18; aL = -0.9 + Math.sin(W * 2.6) * 0.55; zL = -0.3 + Math.sin(W * 1.3) * 0.35; aR = -0.25; ry = Math.sin(W * 1.3) * 0.2; by = Math.sin(W * 1.3) * 0.1; break;
        case "sweep": aR = -0.4 + Math.sin(W * 3.4) * 0.2; zR = Math.sin(W * 3.4) * 0.6; by = Math.sin(W * 3.4) * 0.25; ry = -Math.sin(W * 3.4) * 0.2; aL = -0.25; bz = Math.sin(W * 3.4) * 0.05; break;
        case "lead":  aR = -2.7 + Math.sin(W * 2.4) * 0.15; zR = 0.2 + Math.sin(W * 5) * 0.45; ry = Math.sin(W * 0.8) * 0.5; aL = -0.5 + Math.sin(W * 0.8) * 0.3; zL = -0.4; by = Math.sin(W * 0.8) * 0.15; bz = -0.06; break;
      }
    } else {                                        // 空闲（含待确认 / 退回 / 报错）
      const br = Math.sin(w * 1.7);
      hy = br * 0.022; aL = br * 0.045; aR = -br * 0.045; lamp = 1 + 0.08 * Math.sin(w * 2.1);
      if (t > s.tLook) { s.lookTo = s.lookTo ? 0 : rnd(0.4, 0.7) * (Math.random() < 0.5 ? -1 : 1); s.tLook = t + (s.lookTo ? rnd(1.4, 2.6) : rnd(3.5, 8)); }
      s.look += (s.lookTo - s.look) * Math.min(1, dt * 6); ry = s.look; rx = Math.abs(s.look) * 0.1;
      if (t > s.tFid) {
        s.fid = t;
        if (SLOT) { const r = Math.random(); s.fidKind = r < 0.22 ? 1 : r < 0.47 ? 2 : r < 0.72 ? 3 : 0; s.tFid = t + rnd(3.2, 6.5); }   // 实况待机：造型 / 伸懒腰 / 转椅子 / 摆弄道具轮着来，一直有人在动
        else { s.fidKind = Math.random() < (flair ? 0.7 : 0.4) ? 1 : 0; s.tFid = t + (flair ? rnd(2.4, 4.6) : rnd(6, 12)); }
      }
      if (s.fidKind === 2) {                        // 伸懒腰：双手举过头顶、头后仰、眯眼
        const f = ease((t - s.fid) / 2.2);
        aL += -2.75 * f; aR += -2.75 * f; zL += -0.35 * f; zR += -0.35 * f; rx += -0.28 * f; hy += 0.05 * f; bob += 0.05 * f; eye = Math.min(eye, 1 - 0.75 * f);
      } else if (s.fidKind === 3) {                 // 转椅子：整个身子左右转一圈半弧，手扶桌
        const k = (t - s.fid) / 2.6;
        if (k > 0 && k < 1) { by += Math.sin(k * Math.PI * 2) * 0.75 * ease(k); ry += -Math.sin(k * Math.PI * 2) * 0.2; aL += -0.25 * ease(k); }
      } else if (s.fidKind === 1) {                 // 摆造型：右手高举指天、身体一拧、头一甩
        const f = snap((t - s.fid) / 1.5);
        aR += -2.9 * f; zR += 0.35 * f; aL += 0.35 * f; zL += -0.5 * f; by += 0.32 * f; bz += -0.09 * f; ry += -0.4 * f; rx += -0.1 * f;
      } else {                                      // 摆弄道具
        const f = ease((t - s.fid) / 1.4);
        aR += -0.9 * f + Math.sin((t - s.fid) * 16) * 0.16 * f; ry += 0.3 * f; rx += 0.18 * f;
      }
      if (s.on && s.st === "confirm") { aL = -2.6 + Math.sin(w * 7) * 0.3; zL = -0.25; bz = 0.05; }
      if (s.on && (s.st === "back" || s.st === "error")) { ry = Math.sin(w * 6) * 0.42 * (0.5 + 0.5 * Math.sin(w * 0.9)); }
      if (t > s.tLamp) { s.flash = t; s.tLamp = t + rnd(2.5, 6); }
      lampHot = ease((t - s.flash) / 0.3);
    }
    if (!reduce && !s.off && t > s.tBlink) { s.blink = t; s.tBlink = t + rnd(2, 5.5) * (Math.random() < 0.15 ? 0.15 : 1); }
    if (!reduce && !s.off && t - s.blink < 0.12) eye = 0.1;
    if (!reduce && s.force >= 0) {                 // 演示收尾：全员一起摆造型（三种姿势轮换）
      const k = (t - s.force) / s.forceDur;
      if (k >= 0 && k < 1) {
        const f = Math.min(1, k * 7) * Math.min(1, (1 - k) * 6), P = POSES[s.idx % 3], m = (a, b) => a + (b - a) * f;
        aR = m(aR, P[0]); zR = m(zR, P[1]); aL = m(aL, P[2]); zL = m(zL, P[3]); by = m(by, P[4]); bz = m(bz, P[5]); ry = m(ry, P[6]); rx = m(rx, P[7]);
        bob += 0.12 * ease(Math.min(1, k * 3)); eye = Math.max(eye, f); lampHot = Math.max(lampHot, f * 0.8);
      }
    }
    s.body.position.y = s.y0 - s.sink + bob * s.K;
    s.body.rotation.set(s.bodyRot.x, s.bodyRot.y + by, s.bodyRot.z + bz);
    s.head.position.y = s.headY + hy;
    s.head.rotation.set(s.headRot.x + rx, s.headRot.y + ry, s.headRot.z + rz);
    arm(s.arml, s.qL, aL, zL); arm(s.armr, s.qR, aR, -zR);
    s.eye.scale.copy(s.eyeS); s.eye.scale[s.eyeAx] *= eye;
    s.lamp.scale.copy(s.lampS).multiplyScalar(lamp);
    const base = s.busy ? RED : s.off ? GREYC : s.lampBase;
    s.lampMat.color.copy(base); if (lampHot > 0) s.lampMat.color.lerp(s.busy ? WHITE : RED, lampHot * (s.busy ? 0.5 : 0.85));
  }
  function decoPose(t) {
    for (const p of deco.pens) p.o.rotation.x = p.rx + Math.sin(t * 1.5 + p.k * 0.7) * 0.25;
    if (SLOT) {
      const [h, m, sec] = fmtClock.format(Date.now()).split(":").map(Number), mm = m + sec / 60;
      if (deco.hands.m) deco.hands.m.o.rotation.z = deco.hands.m.rz - (mm / 60) * Math.PI * 2;
      if (deco.hands.h) deco.hands.h.o.rotation.z = deco.hands.h.rz - ((((h % 12) + mm / 60) / 12) * Math.PI * 2 - Math.PI / 2);   // 时针模型默认指 3 点
      moveGlows(t); return;
    }
    if (deco.hands.m) deco.hands.m.o.rotation.z = deco.hands.m.rz - (t / 60) * Math.PI * 2;
    if (deco.hands.h) deco.hands.h.o.rotation.z = deco.hands.h.rz - (t / 720) * Math.PI * 2;
  }
  function moveZ(t) {
    for (const z of zs) {
      if (z.t0 < 0) continue; const k = (t - z.t0) / 2.6;
      if (k >= 1) { z.t0 = -1; z.sp.visible = false; continue; }
      z.sp.position.set(z.p.x + Math.sin(k * 5) * 0.18 + k * 0.35, z.p.y + k * 1.2, z.p.z);
      z.sp.scale.setScalar(0.5 + k * 0.45); z.sp.material.opacity = Math.min(1, k * 5) * (1 - k);
    }
  }

  // 交接：红卡旋转飞行 + 一串星星碎片；退回：黑卡红边
  const cardGeo = new THREE.BoxGeometry(0.62, 0.02, 0.4), CARD_S = 2.3;
  const starGeo = (() => {
    const v = []; const n = 5;
    for (let i = 0; i < n * 2; i++) {
      const a0 = (i / (n * 2)) * Math.PI * 2, a1 = ((i + 1) / (n * 2)) * Math.PI * 2;
      const r0 = i % 2 ? 0.05 : 0.12, r1 = i % 2 ? 0.12 : 0.05;
      v.push(0, 0, 0, Math.cos(a0) * r0, Math.sin(a0) * r0, 0, Math.cos(a1) * r1, Math.sin(a1) * r1, 0);
    }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(v, 3)); return g;
  })();
  // 卡面：白底 + 红色斜带 + 黑星（交接）；黑底 + 红星（退回）。画在 canvas 上，不用任何外部素材
  function cardTex(back) {
    const c = document.createElement("canvas"); c.width = 128; c.height = 84; const g = c.getContext("2d");
    g.fillStyle = back ? PAL.black : PAL.pure; g.fillRect(0, 0, 128, 84);
    g.fillStyle = PAL.red; g.beginPath(); g.moveTo(0, 58); g.lineTo(128, 14); g.lineTo(128, 40); g.lineTo(0, 84); g.closePath(); g.fill();
    g.fillStyle = back ? PAL.red : PAL.black; g.beginPath();
    for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + (i * Math.PI) / 5, r = i % 2 ? 11 : 26; g.lineTo(64 + Math.cos(a) * r, 42 + Math.sin(a) * r); }
    g.closePath(); g.fill();
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  const CARD_MAT = { "交接": new THREE.MeshBasicMaterial({ map: cardTex(false), depthTest: false }), "退回": new THREE.MeshBasicMaterial({ map: cardTex(true), depthTest: false }) };
  const flights = []; const TRAIL = 9;
  let punch = 0;
  // 演示用导演镜头（只有 script=showcase 会调用；实况模式不碰）
  const dir = { on: false, z: 1, o: 0, fx: 0, fy: 0, cz: 1, co: 0, cfx: 0, cfy: 0, rate: 2.2, shake: 0 };
  let flair = false;
  function handoff(from, to, kind = "交接") {
    const A = bots[from], B = bots[to]; if (!A || !B || reduce) return;
    const a = A.head.getWorldPosition(new THREE.Vector3()), b = B.head.getWorldPosition(new THREE.Vector3());
    a.y += 0.7; b.y += 0.7;
    const back = kind === "退回";
    const mid = a.clone().lerp(b, 0.5); mid.y += 1.6 + a.distanceTo(b) * 0.1;
    const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
    const card = new THREE.Mesh(cardGeo, CARD_MAT[back ? "退回" : "交接"]);
    card.renderOrder = 20; card.scale.setScalar(CARD_S);
    const ink = addInk(card, 3, back ? PAL.pure : PAL.black); ink.material = ink.material.clone(); ink.material.depthTest = false; ink.material.uniforms.uRes = { value: res }; ink.renderOrder = 19;
    const bits = new THREE.InstancedMesh(starGeo, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide, depthTest: false }), TRAIL);
    for (let j = 0; j < TRAIL; j++) bits.setColorAt(j, j % 2 ? (back ? RED : BLACKC) : WHITE);
    bits.renderOrder = 18; bits.frustumCulled = false;
    scene.add(card, bits); flights.push({ curve, card, bits, k: 0 });
    punch = 1; dirty = true;
  }
  function drop(f) { scene.remove(f.card, f.bits); f.card.children[0]?.geometry.dispose(); f.card.children[0]?.material.dispose(); f.bits.material.dispose(); f.bits.dispose(); }
  function clearFlights() { for (const f of flights.splice(0)) drop(f); dirty = true; }

  // 拾取：pointermove 只记坐标，每帧最多拾取一次
  const ray = new THREE.Raycaster(), ptr = new THREE.Vector2();
  let rect = renderer.domElement.getBoundingClientRect();
  function pickAt(x, y) {
    ptr.set(((x - rect.left) / rect.width) * 2 - 1, -((y - rect.top) / rect.height) * 2 + 1);
    ray.setFromCamera(ptr, cam);
    return ray.intersectObjects(pickables, false)[0]?.object.userData.bot || null;
  }
  let downAt = null, lastUser = -1e9, movePt = null;
  const el = renderer.domElement;
  el.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; lastUser = performance.now(); rect = el.getBoundingClientRect(); });
  el.addEventListener("pointerup", (e) => { if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) < 5) onPick?.(pickAt(e.clientX, e.clientY)); downAt = null; });
  el.addEventListener("pointermove", (e) => { movePt = [e.clientX, e.clientY]; if (reduce) wake(); });
  el.addEventListener("pointerleave", () => { movePt = null; if (hover) { hover = null; el.style.cursor = ""; dirty = true; wake(); } });
  el.addEventListener("dblclick", () => reset());
  controls.addEventListener("change", () => { dirty = true; lastUser = performance.now(); wake(); });
  function reset() { placeCam(HOME.dist); controls.target.copy(HOME.target); controls.update(); dirty = true; wake(); }

  // 取景：透视相机下，二分找能装下整个工作室的距离，再用 setViewOffset 把画面居中（并往下让出标题位置）
  root.updateMatrixWorld(true);
  const pts = [];
  { const p = new THREE.Vector3();
    for (const o of meshes) { const pos = o.geometry.attributes.position; const st = Math.max(1, Math.floor(pos.count / (o.name === "env" ? 6000 : 60)));
      for (let i = 0; i < pos.count; i += st) pts.push(p.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld).clone()); } }
  const tv = new THREE.Vector3();
  function extent(d) {
    placeCam(d); cam.lookAt(HOME.target); cam.updateMatrixWorld(); cam.updateProjectionMatrix();
    let x0 = 9, x1 = -9, y0 = 9, y1 = -9;
    for (const p of pts) { tv.copy(p).project(cam); if (tv.x < x0) x0 = tv.x; if (tv.x > x1) x1 = tv.x; if (tv.y < y0) y0 = tv.y; if (tv.y > y1) y1 = tv.y; }
    return { x0, x1, y0, y1 };
  }
  let W = 1, H = 1, topPad = 0, baseOX = 0, baseOY = 0;
  function resize() {
    W = host.clientWidth; H = host.clientHeight; if (!W || !H) return;
    rect = el.getBoundingClientRect();
    renderer.setSize(W, H, false); res.set(W, H);
    cam.clearViewOffset(); cam.aspect = W / H; cam.zoom = 1;
    topPad = Math.min(0.22, 58 / H);                       // 标题占的高度（NDC 单位的一半）
    const mx = 0.91, my = 0.9 - topPad;
    let lo = 8, hi = 90;
    for (let i = 0; i < 22; i++) { const d = (lo + hi) / 2, e = extent(d); ((e.x1 - e.x0) / 2 <= mx && (e.y1 - e.y0) / 2 <= my) ? (hi = d) : (lo = d); }
    HOME.dist = hi; const e = extent(hi);
    controls.minDistance = hi * 0.55; controls.maxDistance = hi * 1.15;
    const cx = (e.x0 + e.x1) / 2, cy = (e.y0 + e.y1) / 2 + topPad;
    baseOX = (cx * W) / 2; baseOY = (-cy * H) / 2;
    cam.setViewOffset(W, H, baseOX, baseOY, W, H);
    controls.update(); dirty = true; wake();
  }
  new ResizeObserver(resize).observe(host); resize();

  const v = new THREE.Vector3();
  const TAG = { confirm: "?", back: "!", error: "!" };
  function placeLabels() {
    for (const [name, s] of Object.entries(bots)) {
      const lb = lab[name]; if (!lb) continue; const show = SLOT || s.on || hover === name;
      if (SLOT) lb.classList.toggle("hov", hover === name);
      if (lb.hidden !== !show) lb.hidden = !show; if (!show) continue;
      s.lamp.getWorldPosition(v); v.y += 0.3; v.project(cam);
      const lx = Math.min(W - 28, Math.max(28, ((v.x + 1) / 2) * W)), ly = Math.max(24, ((1 - v.y) / 2) * H);
      lb.style.transform = `translate(${lx.toFixed(1)}px, ${ly.toFixed(1)}px) translate(-50%, -100%) rotate(-4deg)`;
      const st = s.on ? s.st : ""; if (lb.dataset.st !== st) { lb.dataset.st = st; lb.firstChild.textContent = s.on ? TAG[s.st] || "" : ""; }
    }
  }

  // ---------- 主循环：跟随屏幕刷新率（不再锁 30 帧），全部按真实时间差推进 ----------
  const stats = { frames: 0, ms: 0, upd: 0, calls: 0, tris: 0, dpr, fps: 0, intervals: [] };
  let meter = null, fpsAcc = 0, fpsN = 0, fpsT = performance.now(), cpuAcc = 0, slow = 0;
  if (DEBUG) { meter = document.createElement("div"); meter.className = "fps"; host.appendChild(meter); }
  document.addEventListener("visibilitychange", () => { visible = !document.hidden; if (visible) { lastNow = performance.now(); wake(); } else { cancelAnimationFrame(raf); running = false; } });   // 收起时停画；running 要一起清掉，否则再弹出时 wake() 以为还在跑，画面就定住了
  const M4 = new THREE.Matrix4(), Qr = new THREE.Quaternion(), SC = new THREE.Vector3(), Ez = new THREE.Euler(), tan = new THREE.Vector3();
  function wake() { if (!running && visible) { running = true; lastNow = performance.now(); raf = requestAnimationFrame(loop); } }
  let lastDraw = 0;
  function loop(now) {
    running = false; if (!visible) return;
    // 实况：窗口没有焦点（菜单栏弹窗收起、切到别的 App）时降到约 30 帧，省电；页面不可见时完全停画；一回来马上恢复满帧
    if (SLOT && !document.hasFocus() && !flights.length && now - lastDraw < 31) { running = true; raf = requestAnimationFrame(loop); return; }
    lastDraw = now;
    const t0 = performance.now();
    const dt = Math.min(0.05, Math.max(0, (now - lastNow) / 1000)); lastNow = now;
    let anim = false;
    if (movePt) { const h = pickAt(movePt[0], movePt[1]); movePt = null; if (h !== hover) { hover = h; el.style.cursor = h ? "pointer" : ""; dirty = true; } }
    if (controls.update()) dirty = true;
    if (!reduce) {
      t += dt;
      for (const s of Object.values(bots)) {
        if (Math.abs(s.sink - s.sinkTo) > 0.002) s.sink += (s.sinkTo - s.sink) * Math.min(1, dt * 5);
        pose(s, t, dt);
      }
      decoPose(t); moveScraps(t, dt); moveZ(t);
      // 镜头：极慢环绕（±2.6°）+ 推拉；用户刚动过视角就先不动
      const free = now - lastUser > 6000;
      const drift = free ? 0.045 * Math.sin(t / 8) : world.rotation.y;
      world.rotation.y += (drift - world.rotation.y) * Math.min(1, dt * 2);
      punch = Math.max(0, punch - dt * 2.2);
      if (dir.on) {
        const k = 1 - Math.exp(-dt * dir.rate);
        dir.cz += (dir.z - dir.cz) * k; dir.co += (dir.o - dir.co) * k; const kp = 1 - Math.exp(-dt * dir.rate * 1.8); dir.cfx += (dir.fx - dir.cfx) * kp; dir.cfy += (dir.fy - dir.cfy) * kp;
        dir.shake = Math.max(0, dir.shake - dt * 2.4);
        const sh = dir.shake * dir.shake * 16;
        world.rotation.y = dir.co + 0.012 * Math.sin(t / 3);
        cam.zoom = dir.cz * (1 + 0.006 * Math.sin(t * 0.9) + 0.09 * punch * punch);
        cam.setViewOffset(W, H, baseOX + dir.cfx * W / 2 * cam.zoom + Math.sin(t * 71) * sh, baseOY - dir.cfy * H / 2 * cam.zoom + Math.cos(t * 59) * sh, W, H);
      } else cam.zoom = 1 + 0.02 * Math.sin(t / 11) + 0.045 * punch * punch;
      cam.updateProjectionMatrix();
      anim = true;
    }
    for (let i = flights.length - 1; i >= 0; i--) {
      const f = flights[i]; f.k += dt / 1.9; const k = f.k;
      if (k >= 1.25) { drop(f); flights.splice(i, 1); continue; }
      const e = Math.min(1, k); const ee = e < 0.5 ? 2 * e * e : 1 - Math.pow(-2 * e + 2, 2) / 2;
      const p = f.curve.getPoint(ee); f.curve.getTangent(Math.min(1, ee), tan);
      f.card.position.copy(p);
      Ez.set(Math.sin(k * 9) * 0.5, Math.atan2(tan.x, tan.z) + k * 14, Math.sin(k * 6) * 0.6); f.card.rotation.copy(Ez);
      const pop = k < 0.12 ? k / 0.12 : 1; f.card.scale.setScalar(CARD_S * (0.4 + 0.6 * pop) * (k > 0.9 && k < 1 ? 1 + (k - 0.9) * 4 : 1));
      f.card.visible = k < 1;
      const fade = k < 1 ? 1 : 1 - (k - 1) / 0.25;
      for (let j = 0; j < TRAIL; j++) {
        const q = Math.max(0, ee - (j + 1) * 0.035); const s2 = (1 - j / TRAIL) * fade * 1.3;
        Qr.setFromAxisAngle(tan, j * 0.9 + t * 4); SC.set(s2, s2, s2);
        M4.compose(f.curve.getPoint(q), Qr, SC); f.bits.setMatrixAt(j, M4);
      }
      f.bits.instanceMatrix.needsUpdate = true; anim = true;
    }
    stats.flights = flights.length;
    if (dirty || anim) {
      const r0 = performance.now();
      renderer.render(scene, cam); placeLabels(); dirty = false;
      const r1 = performance.now();
      stats.frames++; stats.ms += r1 - r0; stats.upd += r0 - t0;
      stats.calls = renderer.info.render.calls; stats.tris = renderer.info.render.triangles;
      cpuAcc += r1 - t0;
    }
    // 实测帧率（debug 面板）+ 持续掉帧时自动降像素比
    fpsN++; fpsAcc += dt;
    if (now - fpsT > 500) {
      stats.fps = Math.round((fpsN * 1000) / (now - fpsT)); const cpu = cpuAcc / fpsN;
      if (meter) meter.textContent = tr("meter", { fps: stats.fps, cpu: cpu.toFixed(2), calls: stats.calls, dpr });
      if (!reduce && !Q.has("dpr")) {
        slow = stats.fps < 50 && dpr > 1.25 ? slow + 1 : 0;
        if (slow >= 6) { dpr = dpr > 1.5 ? 1.5 : 1.25; renderer.setPixelRatio(dpr); renderer.setSize(W, H, false); stats.dpr = dpr; slow = 0; dirty = true; }
      }
      fpsN = 0; fpsAcc = 0; cpuAcc = 0; fpsT = now;
    }
    if (!reduce || flights.length || dirty) wake();
  }
  wake();
  window.__boardStats = stats;
  // 导演接口：focus = 机器人名字数组（取平均位置拉到画面中心附近），zoom = 推近倍数，orbit = 环绕角，pull = 居中力度
  function ndcOf(names) {
    const z0 = cam.zoom, ry0 = world.rotation.y; cam.zoom = 1; world.rotation.y = dir.o; world.updateMatrixWorld(true);
    cam.setViewOffset(W, H, baseOX, baseOY, W, H); cam.updateProjectionMatrix();
    let x = 0, y = 0, n = 0;
    for (const nm of names) { const s = bots[nm]; if (!s) continue; s.lamp.getWorldPosition(v); v.y -= 0.35 * s.K; v.project(cam); x += v.x; y += v.y; n++; }
    cam.zoom = z0; world.rotation.y = ry0; world.updateMatrixWorld(true);
    return n ? [x / n, y / n] : [0, 0];
  }
  function director(o = {}) {
    if (o.off) { dir.on = false; dir.z = 1; dir.o = 0; dir.fx = dir.fy = 0; resize(); return; }
    if (!dir.on) { dir.on = true; dir.cz = cam.zoom; dir.co = world.rotation.y; }
    if (o.rate) dir.rate = o.rate;
    if (o.zoom != null) dir.z = o.zoom;
    if (o.orbit != null) dir.o = o.orbit;
    if (o.focus !== undefined) { if (o.focus && o.focus.length) { const [x, y] = ndcOf(o.focus), k = o.pull ?? 1; dir.fx = x * k; dir.fy = y * k; } else { dir.fx = 0; dir.fy = 0; } }
    if (o.shift) { dir.fx = o.shift[0]; dir.fy = o.shift[1]; }
    if (o.jump) { dir.cz = dir.z; dir.co = dir.o; dir.cfx = dir.fx; dir.cfy = dir.fy; }
    if (o.shake) dir.shake = o.shake;
    if (o.punch) punch = o.punch;
    wake();
  }
  function strikeAll(dur = 1.6, stagger = 0.05) { let i = 0; for (const s of Object.values(bots)) { s.force = t + (i++ % 7) * stagger; s.forceDur = dur; } wake(); }
  function setFlair(on) { flair = !!on; if (flair) for (const s of Object.values(bots)) s.tFid = Math.min(s.tFid, t + rnd(0.5, 2.5)); }
  // 换人：names[i] = 工位 i 坐谁。只改「谁坐在这个工位」，模型不动；换上来的机器人摆个造型亮相
  function assign(names) {
    if (!SLOT) return;
    for (const k of Object.keys(bots)) delete bots[k];
    for (const lb of Object.values(lab)) lb.hidden = true;
    slotObjs.forEach((s, i) => {
      const nm = names[i]; if (!nm) return;
      const changed = s.name !== nm; s.name = nm; bots[nm] = s;
      for (const o of s.pick) o.userData.bot = nm;
      if (changed && !reduce) { s.force = t; s.forceDur = 1.3; }
      const lb = ensureLab(nm); lb.dataset.st = "_";
    });
    hover = null; dirty = true; wake();
  }
  // 某个成员在画面上的位置（host 内像素），给「替换」按钮定位用
  function screenOf(name) {
    const s = bots[name]; if (!s) return null;
    s.lamp.getWorldPosition(v); v.y += 0.3; v.project(cam);
    return { x: ((v.x + 1) / 2) * W, y: ((1 - v.y) / 2) * H, w: W, h: H };
  }
  function strike(name, dur = 1.3) { const s = bots[name]; if (s && !reduce) { s.force = t; s.forceDur = dur; wake(); } }
  const api = { setStates, handoff, clearFlights, reset, director, strikeAll, setFlair, assign, screenOf, strike, slots: () => slotObjs.map((s) => (s.name.startsWith(HOLD) ? null : s.name)), _flights: flights };
  if (DEBUG) { api._dir = dir; api._ndcOf = ndcOf; api._proj = (n) => { bots[n].lamp.getWorldPosition(v); return v.project(cam).toArray(); }; api._bots = bots; window.__boardScene = api; } // 只给自测脚本用
  return api;
}
