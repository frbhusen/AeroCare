// App shell: layout frame per area (superadmin / center / department environment), sidebar
// navigation from the registry, branding + department accent, route rendering with cleanup.
import { h, mount, safeColor } from "./dom.js";
import { t, localName } from "./i18n.js";
import { getCenter, getDepartments, getPortal, setActiveDepartment, getPrincipal } from "./state.js";
import { menusFor } from "./registry.js";
import { allowed } from "./perm.js";
import { navigate, deptHref, href } from "./router.js";
import { buildTopbar } from "./topbar.js";
import { icon } from "../components/icons.js";
import { emptyState, errorState, loadingState } from "../components/states.js";
import { exitSupport } from "../auth/session.js";
import { toastApiError } from "../components/toast.js";

let frame = null; // {key, root, sidebar, main}
let cleanup = null;
let renderSeq = 0;

export function resetShell() {
  runCleanup();
  frame = null;
}

function runCleanup() {
  if (typeof cleanup === "function") {
    try { cleanup(); } catch (e) { console.error(e); }
  }
  cleanup = null;
}

/** Apply center branding colors + department accent as CSS variables. */
function applyTheme(area, dept) {
  const root = document.documentElement.style;
  const center = getCenter();
  const primary = area !== "admin" && safeColor(center?.primary_color);
  const secondary = area !== "admin" && safeColor(center?.secondary_color);
  primary ? root.setProperty("--brand-primary", primary) : root.removeProperty("--brand-primary");
  secondary ? root.setProperty("--brand-secondary", secondary) : root.removeProperty("--brand-secondary");
  const accent = dept && safeColor(dept.color);
  accent ? root.setProperty("--accent", accent) : root.removeProperty("--accent");
  document.body.dataset.portal = area === "admin" ? "superadmin" : getPortal() || "";
  if (dept) document.body.dataset.env = dept.environment;
  else document.body.removeAttribute("data-env");
}

function navLink(item, base, activePath) {
  const target = base(item.path);
  const active = item.path === "" ? activePath === "" : activePath === item.path || activePath.startsWith(`${item.path}/`);
  return h("a", { class: ["nav-link", active && "is-active"], href: target, "aria-current": active ? "page" : null },
    icon(item.icon || "layers"), h("span", t(item.label)),
    item.placeholder ? h("span", { class: "pill pill--warning nav-soon" }, t("core.soon.badge")) : null);
}

function buildSidebar(m) {
  const items = [];
  const path = m.path ?? "";
  if (m.area === "department") {
    const dept = m.dept;
    const depts = getDepartments();
    items.push(h("div", { class: "dept-head" }, h("div", { class: "dept-head-icon" }, icon(dept.icon)),
      h("div", h("div", { class: "dept-head-name" }, localName(dept, dept.name)),
        dept.name !== localName(dept) ? h("div", { class: "text-xs text-muted" }, dept.name) : null)));
    if (depts.length > 1) {
      const sel = h("select", { class: "select dept-switch", "aria-label": t("core.dept.switch"),
        onChange: (e) => navigate(`/d/${e.target.value}`) },
      depts.map((d) => h("option", { value: String(d.id), selected: d.id === dept.id }, localName(d, d.name))));
      items.push(h("label", { class: "nav-section" }, t("core.dept.switch")), sel);
    }
    if (getPortal() === "center") {
      items.push(h("a", { class: "nav-link", href: href("/center") }, icon("arrowLeft", "flip-rtl"), h("span", t("core.dept.back"))));
    }
    items.push(h("div", { class: "nav-section" }, t("core.nav.menu")));
    for (const mi of menusFor("department", dept.environment)) {
      if (allowed(mi.perm)) items.push(navLink(mi, (p) => deptHref(dept.id, p), path));
    }
  } else {
    for (const mi of menusFor(m.area)) {
      if (!allowed(mi.perm)) continue;
      if (mi.section) items.push(h("div", { class: "nav-section" }, t(mi.section)));
      items.push(navLink(mi, (p) => href(`/${m.area}/${p}`), path));
    }
  }
  return h("nav", { class: "sidebar", "aria-label": t("core.nav.menu") }, items);
}

function supportBanner() {
  const p = getPrincipal();
  if (!p?.support_mode) return null;
  return h("div", { class: "app-banner", role: "status" }, icon("shield"),
    t("core.support.banner", { center: getCenter()?.name || "" }),
    h("button", { class: "btn btn-sm", type: "button", onClick: () => exitSupport().catch(toastApiError) }, t("core.support.exit")));
}

/** Render a router match into #app. */
export async function renderMatch(m, appRoot) {
  const dept = m.area === "department" ? m.dept : null;
  setActiveDepartment(dept?.id ?? null);
  applyTheme(m.area, dept);
  const key = `${m.area}|${dept?.id ?? ""}|${document.documentElement.lang}`;
  if (!frame || frame.key !== key || !frame.root.isConnected) {
    const main = h("main", { class: "main", id: "main", tabindex: "-1" });
    const root = h("div", { class: "app" });
    const slot = h("nav", { class: "sidebar" });
    frame = { key, root, main, sidebar: slot };
    const toggleNav = () => document.body.classList.toggle("nav-open");
    mount(root, buildTopbar({ area: m.area, dept, onToggleNav: toggleNav }), supportBanner(), slot, main,
      h("div", { class: "nav-scrim", onClick: toggleNav }));
    mount(appRoot, root);
  }
  // sidebar rebuilt per route (active link); position 3 in the grid
  const sidebar = m.dept || m.area !== "department" ? buildSidebar(m) : h("nav", { class: "sidebar" });
  frame.sidebar.replaceWith(sidebar);
  frame.sidebar = sidebar;
  document.body.classList.remove("nav-open");

  runCleanup();
  const main = frame.main;
  const my = ++renderSeq;
  window.scrollTo(0, 0);

  if (m.status === "notfound") {
    if (m.area === "department" && !getDepartments().length) {
      document.title = t("core.app_name");
      return mount(main, h("div", { class: "page" }, emptyState({ icon: "building", title: t("core.dept.none_title"), message: t("core.dept.none_message") })));
    }
    document.title = t("core.notfound.title");
    return mount(main, h("div", { class: "page" }, emptyState({ icon: "search", title: t("core.notfound.title"), message: t("core.notfound.message"),
      action: h("a", { class: "btn", href: "#/" }, t("core.go_home")) })));
  }
  if (m.status === "forbidden") {
    document.title = t("core.forbidden.title");
    return mount(main, h("div", { class: "page" }, emptyState({ icon: "lock", title: t("core.forbidden.title"), message: t("core.forbidden.message") })));
  }

  const route = m.route;
  const setTitle = (s) => { document.title = s ? `${s} · ${getCenter()?.name || t("core.app_name")}` : t("core.app_name"); };
  setTitle(route.title ? t(route.title) : "");
  const el = h("div", { class: "route-view" });
  mount(main, loadingState());
  const ctx = { el, area: m.area, path: m.path, params: m.params, query: m.query, dept, env: dept?.environment || null,
    navigate, setTitle, onLeave: null };
  try {
    const out = await route.render(ctx);
    if (my !== renderSeq) return; // user navigated meanwhile
    let node = out;
    if (out && typeof out === "object" && !(out instanceof Node) && "node" in out) {
      node = out.node;
      if (out.cleanup) ctx.onLeave = out.cleanup;
    }
    mount(main, node instanceof Node ? node : el);
    cleanup = ctx.onLeave;
  } catch (e) {
    console.error(e);
    if (my !== renderSeq) return;
    if (e?.status === 404) {
      mount(main, h("div", { class: "page" }, emptyState({ icon: "search", title: t("core.notfound.title"), message: t("core.notfound.message") })));
    } else if (e?.status === 403) {
      mount(main, h("div", { class: "page" }, emptyState({ icon: "lock", title: t("core.forbidden.title"), message: e.message })));
    } else {
      mount(main, h("div", { class: "page" }, errorState(e, () => renderMatch(m, appRoot))));
    }
  }
}
