// Image viewer (spec §103): zoom, rotate, pan, fullscreen, basic annotation (pen / arrow / text)
// drawn on a canvas overlay in image coordinates. Annotations JSON (normalized 0..1 coordinates):
//   [{type: "path", points: [[x,y],...], color}, {type: "arrow", points: [[x1,y1],[x2,y2]], color},
//    {type: "text", points: [[x,y]], text, color}]
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { api, apiUrl } from "../core/api.js";
import { icon } from "./icons.js";
import { openModal } from "./modal.js";
import { toast, toastApiError } from "./toast.js";

/**
 * openImageViewer({src, title, annotations, editable, onSave: async (annotations) => void}) -> {close}
 */
export function openImageViewer({ src, title = "", annotations = [], editable = false, onSave } = {}) {
  let anns = Array.isArray(annotations) ? structuredClone(annotations) : [];
  let dirty = false;
  let tool = "pan";
  let color = "#ef4444";
  let s = 1, rot = 0, tx = 0, ty = 0, w = 1, hgt = 1;
  let drag = null;

  const img = h("img", { alt: title, draggable: "false" });
  const canvas = h("canvas");
  const content = h("div", { class: "viewer-content" }, img, canvas);
  const stage = h("div", { class: "viewer-stage" }, content);
  const zoomLabel = h("span", { class: "viewer-zoom" }, "100%");
  const btn = (ic, label, fn, extra = {}) => h("button", { class: "btn btn-sm btn-icon", type: "button", title: label, "aria-label": label, onClick: fn, ...extra }, icon(ic));
  const toolBtns = {};
  const toolBtn = (name, ic, label) => (toolBtns[name] = btn(ic, label, () => setTool(name)));
  const saveBtn = h("button", { class: "btn btn-sm", type: "button", disabled: true, onClick: save }, icon("save"), t("core.save"));
  const colorInput = h("input", { type: "color", value: color, title: t("core.viewer.color"), onInput: (e) => { color = e.target.value; } });

  const bar = h("div", { class: "viewer-bar" },
    h("div", { class: "viewer-title" }, title),
    btn("zoomOut", t("core.viewer.zoom_out"), () => zoomBy(1 / 1.25)), zoomLabel, btn("zoomIn", t("core.viewer.zoom_in"), () => zoomBy(1.25)),
    btn("rotate", t("core.viewer.rotate"), () => { rot = (rot + 90) % 360; fit(); }),
    btn("grid", t("core.viewer.fit"), () => fit()),
    btn("maximize", t("core.viewer.fullscreen"), toggleFullscreen),
    editable ? [h("span", { class: "sep" }), toolBtn("pan", "hand", t("core.viewer.pan")), toolBtn("pen", "pen", t("core.viewer.pen")),
      toolBtn("arrow", "arrowTool", t("core.viewer.arrow")), toolBtn("text", "type", t("core.viewer.text")), colorInput,
      btn("undo", t("core.viewer.undo"), () => { anns.pop(); changed(); }),
      btn("trash", t("core.viewer.clear"), () => { anns = []; changed(); }),
      onSave ? saveBtn : null] : null,
    h("span", { class: "sep" }),
    btn("x", t("core.close"), () => close()));
  const root = h("div", { class: "viewer", role: "dialog", "aria-modal": "true", "aria-label": title }, bar, stage);
  document.body.append(root);
  setTool("pan");

  img.addEventListener("load", () => {
    w = img.naturalWidth;
    hgt = img.naturalHeight;
    content.style.width = `${w}px`;
    content.style.height = `${hgt}px`;
    canvas.width = w;
    canvas.height = hgt;
    fit();
    draw();
  });
  img.addEventListener("error", () => toast(t("core.viewer.load_failed"), { type: "error" }));
  img.src = src;

  function matrix() {
    return new DOMMatrix().translate(tx, ty).scale(s).translate(w / 2, hgt / 2).rotate(rot).translate(-w / 2, -hgt / 2);
  }
  function apply() {
    content.style.transform = matrix().toString();
    zoomLabel.textContent = `${Math.round(s * 100)}%`;
  }
  function fit() {
    const r = stage.getBoundingClientRect();
    const rotated = rot % 180 !== 0;
    const bw = rotated ? hgt : w;
    const bh = rotated ? w : hgt;
    s = Math.min(r.width / bw, r.height / bh, 4) * 0.95 || 1;
    tx = (r.width - w * s) / 2;
    ty = (r.height - hgt * s) / 2;
    apply();
  }
  function zoomBy(f, cx, cy) {
    const r = stage.getBoundingClientRect();
    const px = cx ?? r.width / 2;
    const py = cy ?? r.height / 2;
    const before = matrix().inverse().transformPoint(new DOMPoint(px, py));
    s = Math.min(20, Math.max(0.05, s * f));
    const after = matrix().transformPoint(before);
    tx += px - after.x;
    ty += py - after.y;
    apply();
  }
  function toImage(e) {
    const r = stage.getBoundingClientRect();
    const p = matrix().inverse().transformPoint(new DOMPoint(e.clientX - r.left, e.clientY - r.top));
    return [Math.min(1, Math.max(0, p.x / w)), Math.min(1, Math.max(0, p.y / hgt))];
  }
  function setTool(name) {
    tool = name;
    Object.entries(toolBtns).forEach(([k, b]) => b.classList.toggle("is-active", k === name));
    stage.classList.toggle("is-drawing", name !== "pan");
  }
  function changed() {
    dirty = true;
    saveBtn.disabled = false;
    draw();
  }

  function draw() {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, hgt);
    const lw = Math.max(2, Math.min(w, hgt) / 250);
    const all = drag?.draft ? [...anns, drag.draft] : anns;
    for (const a of all) {
      const pts = (a.points || []).map(([x, y]) => [x * w, y * hgt]);
      ctx.strokeStyle = ctx.fillStyle = a.color || "#ef4444";
      ctx.lineWidth = lw;
      ctx.lineCap = ctx.lineJoin = "round";
      if (a.type === "path" && pts.length) {
        ctx.beginPath();
        pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.stroke();
      } else if (a.type === "arrow" && pts.length === 2) {
        const [[x1, y1], [x2, y2]] = pts;
        const ang = Math.atan2(y2 - y1, x2 - x1);
        const head = lw * 5;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - head * Math.cos(ang - 0.45), y2 - head * Math.sin(ang - 0.45));
        ctx.lineTo(x2 - head * Math.cos(ang + 0.45), y2 - head * Math.sin(ang + 0.45));
        ctx.closePath();
        ctx.fill();
      } else if (a.type === "text" && pts.length && a.text) {
        const size = Math.max(14, Math.min(w, hgt) / 28);
        ctx.font = `700 ${size}px ${getComputedStyle(document.body).fontFamily}`;
        ctx.lineWidth = size / 6;
        ctx.strokeStyle = "rgba(0,0,0,0.6)";
        ctx.strokeText(a.text, pts[0][0], pts[0][1]);
        ctx.fillText(a.text, pts[0][0], pts[0][1]);
      }
    }
  }

  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    stage.setPointerCapture(e.pointerId);
    if (tool === "pan") {
      drag = { mode: "pan", x: e.clientX, y: e.clientY, tx, ty };
      stage.classList.add("is-panning");
    } else if (tool === "pen") {
      drag = { mode: "draw", draft: { type: "path", points: [toImage(e)], color } };
    } else if (tool === "arrow") {
      const p = toImage(e);
      drag = { mode: "draw", draft: { type: "arrow", points: [p, p], color } };
    } else if (tool === "text") {
      const p = toImage(e);
      askText().then((text) => {
        if (text) {
          anns.push({ type: "text", points: [p], text, color });
          changed();
        }
      });
    }
  });
  stage.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (drag.mode === "pan") {
      tx = drag.tx + (e.clientX - drag.x);
      ty = drag.ty + (e.clientY - drag.y);
      apply();
    } else if (drag.draft.type === "path") {
      drag.draft.points.push(toImage(e));
      draw();
    } else {
      drag.draft.points[1] = toImage(e);
      draw();
    }
  });
  const end = () => {
    if (drag?.mode === "draw") {
      const d = drag.draft;
      const moved = d.type === "path" ? d.points.length > 1 : d.points[0].join() !== d.points[1].join();
      if (moved) {
        d.points = d.points.map(([x, y]) => [Math.round(x * 10000) / 10000, Math.round(y * 10000) / 10000]);
        anns.push(d);
        drag = null;
        changed();
      }
    }
    drag = null;
    stage.classList.remove("is-panning");
    draw();
  };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = stage.getBoundingClientRect();
    zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  const onKey = (e) => {
    if (e.target.closest?.("input, textarea") || document.querySelector(".overlay")) return;
    if (e.key === "Escape" && !document.fullscreenElement) close();
    else if (e.key === "+" || e.key === "=") zoomBy(1.25);
    else if (e.key === "-") zoomBy(1 / 1.25);
    else if (e.key.toLowerCase() === "r") { rot = (rot + 90) % 360; fit(); }
  };
  document.addEventListener("keydown", onKey);
  const onResize = () => fit();
  window.addEventListener("resize", onResize);

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else root.requestFullscreen?.().then(() => setTimeout(fit, 100)).catch(() => {});
  }

  async function save() {
    if (!onSave) return;
    saveBtn.classList.add("is-loading");
    try {
      await onSave(structuredClone(anns));
      dirty = false;
      saveBtn.disabled = true;
      toast(t("core.saved"), { type: "success" });
    } catch (e) {
      toastApiError(e);
    } finally {
      saveBtn.classList.remove("is-loading");
    }
  }

  function close() {
    if (dirty && onSave && !window.confirm(t("core.viewer.discard"))) return;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("resize", onResize);
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    root.remove();
  }
  return { close };
}

function askText() {
  return new Promise((resolve) => {
    const input = h("input", { class: "input", maxlength: 120, autofocus: true });
    let value = null;
    const m = openModal({
      title: t("core.viewer.text"), size: "sm", body: input,
      actions: [{ label: t("core.cancel") }, { label: t("core.ok"), variant: "primary", onClick: () => { value = input.value.trim(); } }],
      onClose: () => resolve(value),
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        value = input.value.trim();
        m.close();
      }
    });
  });
}

/**
 * openFileViewer(file, {editable, onSaved(updatedFile)}) for a files-API record
 * {id, display_name, mime_type, annotations, version}. Images open in the viewer (annotations saved with
 * PATCH /files/<id> {annotations, version}); other types (PDF...) open in a new tab.
 */
export function openFileViewer(file, { editable = false, onSaved } = {}) {
  const src = apiUrl(`/files/${encodeURIComponent(file.id)}/content`);
  if (!String(file.mime_type || "").startsWith("image/")) {
    window.open(src, "_blank", "noopener");
    return null;
  }
  let version = file.version;
  return openImageViewer({
    src, title: file.display_name || file.original_name || "", annotations: file.annotations || [], editable,
    onSave: editable ? async (annotations) => {
      const res = await api.patch(`/files/${encodeURIComponent(file.id)}`, { annotations, version });
      if (res && res.version != null) version = res.version;
      if (onSaved) onSaved(res);
    } : null,
  });
}
