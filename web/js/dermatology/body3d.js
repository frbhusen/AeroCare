// Interactive 3D mannequin (three.js, vendored in web/vendor/three). Built from primitives; each
// body region is made of front/back half-shells so a click selects region + side and the exact
// side is highlighted. The model faces +z; the patient's left is +x.
const THREE_URL = new URL("../../vendor/three/three.module.min.js", import.meta.url).href;

/** True when a WebGL context can be created. */
export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

const HALF = Math.PI;
// [region, shape, size, position, options]  shape: s = sphere(r), c = cylinder(rTop, rBottom, h)
// side: "both" (front + back halves), "front" | "back" (single region side, other half neutral)
const PARTS = [
  ["face", "s", [0.3], [0, 1.55, 0], { side: "front", other: "scalp" }],
  ["scalp", "cap", [0.305], [0, 1.6, 0], { side: "both" }],
  ["forehead", "box", [0.26, 0.08, 0.06], [0, 1.69, 0.255], { side: "front" }],
  ["cheeks", "s", [0.07], [-0.15, 1.5, 0.23], { side: "front" }],
  ["cheeks", "s", [0.07], [0.15, 1.5, 0.23], { side: "front" }],
  ["upper_lip", "box", [0.12, 0.035, 0.05], [0, 1.43, 0.28], { side: "front" }],
  ["chin", "s", [0.065], [0, 1.33, 0.22], { side: "front" }],
  ["neck", "c", [0.12, 0.13, 0.22], [0, 1.18, 0], { side: "both" }],
  ["shoulders", "s", [0.14], [-0.42, 0.97, 0], { side: "both" }],
  ["shoulders", "s", [0.14], [0.42, 0.97, 0], { side: "both" }],
  ["chest", "c", [0.38, 0.34, 0.55], [0, 0.75, 0], { side: "front", other: "upper_back", scaleZ: 0.62 }],
  ["abdomen", "c", [0.34, 0.33, 0.45], [0, 0.25, 0], { side: "front", other: "lower_back", scaleZ: 0.62 }],
  ["bikini", "c", [0.33, 0.3, 0.28], [0, -0.115, 0], { side: "front", other: "buttocks", scaleZ: 0.66 }],
  ["underarm_right", "s", [0.07], [-0.36, 0.86, 0.04], { side: "front" }],
  ["underarm_left", "s", [0.07], [0.36, 0.86, 0.04], { side: "front" }],
  ["upper_arm_right", "c", [0.1, 0.09, 0.56], [-0.53, 0.62, 0], { side: "both", rotZ: -0.12 }],
  ["upper_arm_left", "c", [0.1, 0.09, 0.56], [0.53, 0.62, 0], { side: "both", rotZ: 0.12 }],
  ["forearm_right", "c", [0.085, 0.07, 0.52], [-0.6, 0.08, 0], { side: "both", rotZ: -0.05 }],
  ["forearm_left", "c", [0.085, 0.07, 0.52], [0.6, 0.08, 0], { side: "both", rotZ: 0.05 }],
  ["hands", "s", [0.095], [-0.63, -0.27, 0], { side: "both", scaleY: 1.35 }],
  ["hands", "s", [0.095], [0.63, -0.27, 0], { side: "both", scaleY: 1.35 }],
  ["thigh_right", "c", [0.16, 0.12, 0.78], [-0.17, -0.67, 0], { side: "both" }],
  ["thigh_left", "c", [0.16, 0.12, 0.78], [0.17, -0.67, 0], { side: "both" }],
  ["lower_leg_right", "c", [0.115, 0.08, 0.72], [-0.17, -1.43, 0], { side: "both" }],
  ["lower_leg_left", "c", [0.115, 0.08, 0.72], [0.17, -1.43, 0], { side: "both" }],
  ["feet", "s", [0.09], [-0.17, -1.85, 0.07], { side: "both", scaleZ: 1.9, scaleY: 0.55 }],
  ["feet", "s", [0.09], [0.17, -1.85, 0.07], { side: "both", scaleZ: 1.9, scaleY: 0.55 }],
];

function cssColor(varName, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  return v && !v.includes("(") ? v : fallback;
}

/**
 * body3d(container, {label(code), isSelected(region, side), onToggle(region, side), allowedSide(region, side)})
 *   -> Promise<{setView("front"|"back"), refresh(), destroy()}>
 */
export async function body3d(container, { label, isSelected, onToggle, allowedSide }) {
  const THREE = await import(THREE_URL);
  const width = () => Math.max(220, container.clientWidth || 320);
  const height = () => Math.round(Math.min(520, Math.max(360, width() * 1.25)));
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width(), height());
  renderer.domElement.className = "derm-body3d-canvas";
  renderer.domElement.setAttribute("role", "img");
  container.append(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, width() / height(), 0.1, 50);
  camera.position.set(0, 0, 8.2);
  camera.lookAt(0, -0.1, 0);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 2.2));
  const dir = new THREE.DirectionalLight(0xffffff, 1.4);
  dir.position.set(2, 3, 5);
  scene.add(dir);
  const back = new THREE.DirectionalLight(0xffffff, 0.8);
  back.position.set(-2, 2, -5);
  scene.add(back);

  const model = new THREE.Group();
  model.position.y = 0.05;
  scene.add(model);

  const base = new THREE.Color("#d8dee8");
  const neutral = new THREE.Color("#c7ced9");
  const hover = new THREE.Color("#a9c7ea");
  const selected = new THREE.Color(cssColor("--accent", "#c026d3"));
  const pickables = [];

  function material(color) {
    return new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.02, side: THREE.DoubleSide });
  }

  function geometry(shape, size, half) {
    // half: "front" | "back" | null (full)
    const start = half === "back" ? HALF : 0;
    const len = half ? HALF : HALF * 2;
    if (shape === "s") return new THREE.SphereGeometry(size[0], 28, 18, start, len);
    if (shape === "cap") return new THREE.SphereGeometry(size[0], 28, 10, start, len, 0, Math.PI * 0.32);
    if (shape === "box") return new THREE.BoxGeometry(...size);
    // Cylinder theta 0 points to +z; front half = [-pi/2, pi/2].
    const tStart = half === "back" ? HALF / 2 : -HALF / 2;
    return new THREE.CylinderGeometry(size[0], size[1], size[2], 32, 1, !!half, half ? tStart : 0, len);
  }

  function addMesh(region, side, shape, size, pos, o, half) {
    const mesh = new THREE.Mesh(geometry(shape, size, half), material(region ? base : neutral));
    mesh.position.set(...pos);
    if (o.rotZ) mesh.rotation.z = o.rotZ;
    mesh.scale.set(1, o.scaleY || 1, o.scaleZ || 1);
    mesh.userData = { region, side };
    model.add(mesh);
    if (region) pickables.push(mesh);
    return mesh;
  }

  for (const [region, shape, size, pos, o] of PARTS) {
    if (shape === "box") {
      addMesh(region, "front", shape, size, pos, o, null);
      continue;
    }
    if (o.side === "both") {
      addMesh(region, "front", shape, size, pos, o, "front");
      addMesh(region, "back", shape, size, pos, o, "back");
    } else if (o.other) {
      addMesh(region, "front", shape, size, pos, o, "front");
      addMesh(o.other, "back", shape, size, pos, o, "back");
    } else {
      addMesh(region, o.side, shape, size, pos, o, null);
    }
  }
  // The head sphere back half is "scalp" (via `other`); the cap adds a top scalp shell.

  let hovered = null;
  let targetRot = 0;
  let disposed = false;

  function paint() {
    for (const m of pickables) {
      const { region, side } = m.userData;
      const on = isSelected(region, side);
      m.material.color.copy(on ? selected : (hovered && hovered.userData.region === region && hovered.userData.side === side)
        ? hover : base);
      m.material.emissive?.set(on ? 0x220022 : 0x000000);
    }
  }

  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(pickables, false)[0];
    return hit ? hit.object : null;
  }

  // Drag to rotate (pointer), click to toggle.
  let down = null;
  const el = renderer.domElement;
  el.addEventListener("pointerdown", (e) => {
    down = { x: e.clientX, rot: model.rotation.y, moved: false };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener("pointermove", (e) => {
    if (down) {
      const dx = e.clientX - down.x;
      if (Math.abs(dx) > 4) down.moved = true;
      if (down.moved) {
        model.rotation.y = down.rot + dx * 0.012;
        targetRot = model.rotation.y;
      }
      return;
    }
    const m = pick(e);
    if (m !== hovered) {
      hovered = m;
      el.style.cursor = m ? "pointer" : "grab";
      el.title = m ? label(m.userData.region) : "";
      paint();
    }
  });
  el.addEventListener("pointerup", (e) => {
    const wasDrag = down && down.moved;
    down = null;
    if (wasDrag) return;
    const m = pick(e);
    if (!m) return;
    const { region, side } = m.userData;
    if (allowedSide && !allowedSide(region, side)) return;
    onToggle(region, side);
  });
  el.addEventListener("pointerleave", () => {
    hovered = null;
    paint();
  });

  const onResize = () => {
    renderer.setSize(width(), height());
    camera.aspect = width() / height();
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(onResize);
  ro.observe(container);

  function loop() {
    if (disposed) return;
    const d = targetRot - model.rotation.y;
    if (Math.abs(d) > 0.001) model.rotation.y += d * 0.18;
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }
  paint();
  loop();

  return {
    setView(view) {
      const turns = Math.round(model.rotation.y / (2 * Math.PI));
      targetRot = turns * 2 * Math.PI + (view === "back" ? Math.PI : 0);
    },
    refresh: paint,
    destroy() {
      disposed = true;
      ro.disconnect();
      model.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) o.material.dispose();
      });
      renderer.dispose();
      el.remove();
    },
  };
}
