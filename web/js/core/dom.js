// DOM helpers. XSS-safe by default: strings always become text nodes / escaped text.
// Never assign untrusted strings to innerHTML; use h() or html``.

const PROP_ATTRS = new Set(["value", "checked", "disabled", "selected", "hidden", "readOnly", "multiple", "indeterminate"]);

/**
 * h(tag, attrs?, ...children) -> Element
 *  attrs: { class, style (string|object), dataset: {}, onClick: fn (any on<Event>), ref: fn(el),
 *           value/checked/disabled (properties), other keys -> setAttribute; null/false skipped }
 *  children: strings/numbers (text), Nodes, arrays, null/false (skipped)
 */
export function h(tag, attrs, ...children) {
  if (attrs != null && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  const el = tag.startsWith("svg:")
    ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4))
    : document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class" || k === "className") {
        const cls = Array.isArray(v) ? v.filter(Boolean).join(" ") : v;
        if (cls) el.setAttribute("class", cls);
      } else if (k === "style") {
        if (typeof v === "string") el.setAttribute("style", v);
        else for (const [sk, sv] of Object.entries(v)) {
          if (sv == null) continue;
          if (sk.startsWith("--")) el.style.setProperty(sk, sv); else el.style[sk] = sv;
        }
      } else if (k === "dataset") {
        for (const [dk, dv] of Object.entries(v)) if (dv != null) el.dataset[dk] = dv;
      } else if (k === "ref") {
        v(el);
      } else if (k.length > 2 && k.startsWith("on") && typeof v === "function") {
        el.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (PROP_ATTRS.has(k)) {
        el[k] = v;
      } else if (k === "html") {
        throw new Error("h(): 'html' attribute is not allowed (XSS). Build nodes instead.");
      } else {
        el.setAttribute(k, v === true ? "" : String(v));
      }
    }
  }
  append(el, children);
  return el;
}

export function append(parent, ...children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false || c === true) continue;
    parent.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return parent;
}

/** Replace all children. */
export function mount(parent, ...children) {
  parent.replaceChildren();
  return append(parent, ...children);
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function on(target, event, selectorOrHandler, handler) {
  if (typeof selectorOrHandler === "function") {
    target.addEventListener(event, selectorOrHandler);
    return () => target.removeEventListener(event, selectorOrHandler);
  }
  const fn = (e) => {
    const m = e.target.closest(selectorOrHandler);
    if (m && target.contains(m)) handler(e, m);
  };
  target.addEventListener(event, fn);
  return () => target.removeEventListener(event, fn);
}

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };
export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"'`]/g, (c) => ESC[c]);
}

/**
 * html`<div class="x">${value}</div>` -> DocumentFragment.
 * Interpolated strings are escaped; interpolated Nodes/arrays of Nodes are inserted as nodes.
 * Inline event handlers are blocked by CSP anyway; attach listeners after with on()/h().
 */
export function html(strings, ...values) {
  const nodes = [];
  let src = strings[0];
  values.forEach((v, i) => {
    if (v instanceof Node || (Array.isArray(v) && v.some((x) => x instanceof Node))) {
      nodes.push(v);
      src += `<template data-slot="${nodes.length - 1}"></template>`;
    } else if (Array.isArray(v)) {
      src += v.map(escapeHtml).join("");
    } else {
      src += escapeHtml(v);
    }
    src += strings[i + 1];
  });
  const tpl = document.createElement("template");
  tpl.innerHTML = src;
  const frag = tpl.content;
  frag.querySelectorAll("template[data-slot]").forEach((slot) => {
    const v = nodes[Number(slot.dataset.slot)];
    slot.replaceWith(...(Array.isArray(v) ? v.flat(Infinity).filter(Boolean) : [v]));
  });
  return frag;
}

export function debounce(fn, ms = 250) {
  let t;
  const d = (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
  d.cancel = () => clearTimeout(t);
  return d;
}

/** Toggle a loading state on a button while awaiting fn(). */
export async function withBusy(btn, fn) {
  if (!btn) return fn();
  btn.classList.add("is-loading");
  btn.disabled = true;
  try {
    return await fn();
  } finally {
    btn.classList.remove("is-loading");
    btn.disabled = false;
  }
}

/** Initials for avatars. */
export function initials(name) {
  return String(name || "?").trim().split(/\s+/).slice(0, 2).map((p) => p[0] || "").join("").toUpperCase() || "?";
}

/** Only allow #-hashes and same-origin relative paths as link targets coming from data. */
export function safeHref(link) {
  if (typeof link !== "string") return null;
  if (link.startsWith("#/")) return link;
  if (link.startsWith("/") && !link.startsWith("//")) return link;
  return null;
}

/** Validate a #rrggbb color (branding values come from the server but are user-entered). */
export function safeColor(c) {
  return typeof c === "string" && /^#[0-9a-fA-F]{6}$/.test(c) ? c : null;
}

const loadedStyles = new Set();
/** Load a module stylesheet once: loadStylesheet(new URL("./dentistry.css", import.meta.url)). */
export function loadStylesheet(url) {
  const href = String(url);
  if (loadedStyles.has(href)) return;
  loadedStyles.add(href);
  document.head.append(h("link", { rel: "stylesheet", href }));
}
