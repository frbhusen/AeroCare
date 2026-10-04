// Superadmin portal shell: dashboard, navigation slots (filled by the admin module), and
// "Enter center (support view)" via POST /auth/support/enter.
import { h, mount } from "../core/dom.js";
import { t, formatDate } from "../core/i18n.js";
import { api } from "../core/api.js";
import { href } from "../core/router.js";
import { menusFor } from "../core/registry.js";
import { icon } from "../components/icons.js";
import { comingSoon, loadingState, statusPill } from "../components/states.js";
import { createForm } from "../components/form.js";
import { enterSupport } from "../auth/session.js";

// Slots the admin module replaces (same area + path / key).
export const ADMIN_SLOTS = [
  { key: "centers", path: "centers", label: "core.admin.centers", icon: "building", order: 10 },
  { key: "modules", path: "modules", label: "core.admin.modules", icon: "layers", order: 20 },
  { key: "plans", path: "plans", label: "core.admin.plans", icon: "tag", order: 30 },
  { key: "users", path: "users", label: "core.admin.users", icon: "users", order: 40 },
  { key: "storage", path: "storage", label: "core.admin.storage", icon: "database", order: 50 },
  { key: "audit", path: "audit", label: "core.admin.audit", icon: "clipboard", order: 60 },
  { key: "settings", path: "settings", label: "core.admin.settings", icon: "sliders", order: 70 },
];

export function registerPortal(reg) {
  reg.route({ area: "admin", path: "", title: "core.admin.dashboard", render: renderDashboard });
  reg.menu({ area: "admin", key: "dashboard", path: "", label: "core.admin.dashboard", icon: "grid", order: 0 });
  for (const s of ADMIN_SLOTS) {
    reg.route({ area: "admin", path: s.path, title: s.label, placeholder: true, render: () => comingSoon(s.label) });
    reg.menu({ area: "admin", ...s, placeholder: true });
  }
  reg.route({ area: "admin", path: "support", title: "core.support.enter", render: renderSupport });
  reg.menu({ area: "admin", key: "support", path: "support", label: "core.support.enter", icon: "login", order: 90 });
}

function renderDashboard() {
  const tiles = menusFor("admin").filter((m) => m.path);
  return h("div", { class: "page" },
    h("div", { class: "page-header" }, h("div", h("h1", t("core.admin.dashboard")), h("p", { class: "subtitle" }, t("core.admin.dashboard_sub")))),
    h("div", { class: "tile-grid" }, tiles.map((m) => h("a", { class: "tile", href: href(`/admin/${m.path}`) }, icon(m.icon), h("span", t(m.label)),
      m.placeholder ? h("span", { class: "pill pill--warning", style: "margin-inline-start:auto" }, t("core.soon.badge")) : null))));
}

async function renderSupport() {
  const listEl = h("div", loadingState());
  const page = h("div", { class: "page" },
    h("div", { class: "page-header" }, h("div", h("h1", t("core.support.enter")), h("p", { class: "subtitle" }, t("core.support.explain")))),
    h("div", { class: "card" }, listEl));

  const go = async (id) => enterSupport(id);
  let centers = null;
  try {
    const res = await api.get("/admin/centers", { query: { per_page: 100 } });
    centers = res?.items || (Array.isArray(res) ? res : null);
  } catch { centers = null; } // admin module not available yet: manual id entry below

  if (centers && centers.length) {
    mount(listEl, h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
      h("thead", h("tr", h("th", t("core.support.center")), h("th", t("core.support.status")), h("th", t("core.support.until")), h("th", ""))),
      h("tbody", centers.map((c) => h("tr",
        h("td", { "data-label": t("core.support.center") }, h("strong", c.name)),
        h("td", { "data-label": t("core.support.status") }, c.status ? statusPill(c.status, "core.center.status") : ""),
        h("td", { "data-label": t("core.support.until") }, formatDate(c.status === "trial" ? c.trial_ends_at : c.subscription_ends_at, { year: "always" })),
        h("td", { class: "actions" }, h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: (e) => withBtn(e.currentTarget, () => go(c.id)) },
          icon("login"), t("core.support.enter_btn")))))))));
  } else {
    const form = createForm({
      columns: 1,
      fields: [{ name: "center_id", label: t("core.support.center_id"), type: "number", required: true, min: 1,
        help: centers ? t("core.support.none") : t("core.support.manual") }],
      submitLabel: t("core.support.enter_btn"),
      onSubmit: async (v) => go(v.center_id),
    });
    mount(listEl, h("div", { class: "card-body" }, form.el));
  }
  return page;
}

async function withBtn(btn, fn) {
  btn.classList.add("is-loading");
  try {
    await fn();
  } catch (e) {
    const { toastApiError } = await import("../components/toast.js");
    toastApiError(e);
  } finally {
    btn.classList.remove("is-loading");
  }
}
