// Modal, drawer, confirm dialog, popover menus.
import { h, append } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { onEvent } from "../core/events.js";
import { icon } from "./icons.js";

const open = new Set();
// Close dialogs when the route changes (navigation away).
onEvent("route:changed", () => [...open].forEach((m) => m.persistent || m.close()));

/**
 * openModal({title, body: Node|Node[], footer: Node[] | actions: [{label, variant, onClick(modal), close}],
 *            size: "sm"|"md"|"lg"|"xl", drawer: false, dismissible: true, onClose})
 *   -> {el, body, close(), setBusy(bool)}
 * Action onClick may return a promise; returning false keeps the modal open.
 */
export function openModal({ title, body, footer, actions, size = "md", drawer = false, dismissible = true, onClose, persistent = false } = {}) {
  const prevFocus = document.activeElement;
  const bodyEl = h("div", { class: "modal-body" });
  append(bodyEl, body);
  const titleId = `m-${Math.random().toString(36).slice(2, 8)}`;
  let footerEl = null;
  const handle = { el: null, body: bodyEl, close, persistent };

  if (actions && actions.length) {
    footer = actions.map((a) => {
      const b = h("button", { class: `btn ${a.variant ? `btn-${a.variant}` : ""}`, type: a.type || "button" }, a.icon ? icon(a.icon) : null, a.label);
      b.addEventListener("click", async () => {
        if (!a.onClick) return close();
        b.classList.add("is-loading");
        b.disabled = true;
        try {
          const r = await a.onClick(handle);
          if (r !== false && a.close !== false) close();
        } finally {
          b.classList.remove("is-loading");
          b.disabled = false;
        }
      });
      return b;
    });
  }
  if (footer) footerEl = append(h("div", { class: "modal-footer" }), footer);

  const box = h("div", { class: [drawer ? "drawer" : "modal", drawer ? (size === "lg" ? "drawer-lg" : "") : `modal-${size}`],
    role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
  h("div", { class: "modal-header" }, h("h2", { id: titleId }, title || ""),
    h("button", { class: "btn btn-ghost btn-icon btn-sm", type: "button", "aria-label": t("core.close"), onClick: () => close() }, icon("x"))),
  bodyEl, footerEl);
  const overlay = h("div", { class: ["overlay", drawer && "drawer-overlay"] }, box);
  handle.el = box;
  overlay.addEventListener("mousedown", (e) => {
    if (e.target === overlay && dismissible) close();
  });
  const onKey = (e) => {
    if (e.key === "Escape" && dismissible && [...open].pop() === handle) {
      e.stopPropagation();
      close();
    }
    if (e.key === "Tab") trapFocus(e, box);
  };
  document.addEventListener("keydown", onKey);
  document.body.append(overlay);
  open.add(handle);
  requestAnimationFrame(() => {
    const first = box.querySelector("[autofocus], input:not([type=hidden]):not([disabled]), select, textarea, .modal-footer .btn-primary");
    (first || box.querySelector(".modal-header .btn")).focus();
  });

  let closed = false;
  function close(result) {
    if (closed) return;
    closed = true;
    open.delete(handle);
    document.removeEventListener("keydown", onKey);
    overlay.remove();
    if (prevFocus && prevFocus.focus) prevFocus.focus();
    if (onClose) onClose(result);
  }
  return handle;
}

function trapFocus(e, root) {
  const f = [...root.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")]
    .filter((x) => !x.disabled && x.offsetParent !== null);
  if (!f.length) return;
  const first = f[0];
  const last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

/** Side drawer: same options as openModal. */
export const openDrawer = (opts) => openModal({ ...opts, drawer: true });

/** await confirmDialog({title, message, confirmLabel, danger}) -> true/false */
export function confirmDialog({ title, message, confirmLabel, cancelLabel, danger = false } = {}) {
  return new Promise((resolve) => {
    let result = false;
    openModal({
      title: title || t("core.confirm.title"),
      size: "sm",
      body: h("p", message || t("core.confirm.message")),
      actions: [
        { label: cancelLabel || t("core.cancel") },
        { label: confirmLabel || t("core.confirm.ok"), variant: danger ? "danger" : "primary", onClick: () => { result = true; } },
      ],
      onClose: () => resolve(result),
    });
  });
}

/**
 * Popover anchored to a button: popover(anchor, contentNode, {align: "end"}) -> {close}.
 * Closes on outside click / Escape / route change.
 */
export function popover(anchor, content, { align = "end", className = "" } = {}) {
  const el = h("div", { class: `popover ${className}`.trim(), role: "menu" }, content);
  document.body.append(el);
  const place = () => {
    const r = anchor.getBoundingClientRect();
    const rtl = document.documentElement.dir === "rtl";
    const w = el.offsetWidth;
    let left = (align === "end") !== rtl ? r.right - w : r.left;
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
    el.style.top = `${r.bottom + window.scrollY + 6}px`;
    el.style.left = `${left + window.scrollX}px`;
  };
  place();
  const close = () => {
    el.remove();
    document.removeEventListener("mousedown", outside, true);
    document.removeEventListener("keydown", key);
    window.removeEventListener("resize", place);
    offRoute();
  };
  const outside = (e) => {
    if (!el.contains(e.target) && !anchor.contains(e.target)) close();
  };
  const key = (e) => e.key === "Escape" && close();
  document.addEventListener("mousedown", outside, true);
  document.addEventListener("keydown", key);
  window.addEventListener("resize", place);
  const offRoute = onEvent("route:changed", close);
  return { el, close, place };
}
