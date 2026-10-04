// Center portal shell (Health Center Manager / center-wide staff / superadmin support view):
// Overview with large department cards (spec §30) + center-wide navigation slots.
import { h, safeColor } from "../core/dom.js";
import { t, localName, formatDate, formatNumber } from "../core/i18n.js";
import { getCenter, getDepartments, clinicsOf } from "../core/state.js";
import { widgetsFor } from "../core/registry.js";
import { allowed } from "../core/perm.js";
import { deptHref } from "../core/router.js";
import { icon } from "../components/icons.js";
import { emptyState, comingSoon, statusPill, errorState } from "../components/states.js";

// Center-wide slots: modules replace these by registering a route/menu with the same area+path/key.
export const CENTER_SLOTS = [
  { key: "patients", path: "patients", label: "core.nav.patients", icon: "users", perm: "patients.view", order: 10 },
  { key: "appointments", path: "appointments", label: "core.nav.appointments", icon: "calendar", perm: "appointments.view", order: 20 },
  { key: "financial", path: "financial", label: "core.nav.financial", icon: "wallet", perm: "billing.view", order: 30 },
  { key: "inventory", path: "inventory", label: "core.nav.inventory", icon: "box", perm: "inventory.view", order: 40 },
  { key: "staff", path: "staff", label: "core.nav.staff", icon: "staff", perm: "staff.view", order: 50 },
  { key: "reports", path: "reports", label: "core.nav.reports", icon: "chart", perm: "reports.view", order: 60 },
  { key: "settings", path: "settings", label: "core.nav.settings", icon: "settings", perm: "settings.view", order: 70 },
];

export function registerCenter(reg) {
  reg.route({ area: "center", path: "", title: "core.nav.overview", render: renderOverview });
  reg.menu({ area: "center", key: "overview", path: "", label: "core.nav.overview", icon: "grid", order: 0 });
  for (const s of CENTER_SLOTS) {
    reg.route({ area: "center", path: s.path, perm: s.perm, title: s.label, placeholder: true, render: () => comingSoon(s.label) });
    reg.menu({ area: "center", ...s, placeholder: true });
  }
}

function departmentCard(d) {
  const clinics = clinicsOf(d.id);
  const local = localName(d, d.name);
  return h("a", { class: "dept-card", href: deptHref(d.id), style: { "--dc": safeColor(d.color) } },
    h("div", { class: "dept-card-icon" }, icon(d.icon)),
    h("div", h("div", { class: "dept-card-name" }, d.name),
      local !== d.name ? h("div", { class: "dept-card-sub" }, local) : null),
    h("div", { class: "dept-card-sub" }, t("core.dept.clinics_count", { count: formatNumber(clinics.length) })),
    h("div", { class: "dept-card-foot" }, h("span", t("core.dept.enter")), icon("arrowRight", "flip-rtl")));
}

function renderOverview(ctx) {
  const center = getCenter();
  const depts = getDepartments();
  const status = center?.status;
  const ends = status === "trial" ? center.trial_ends_at : center?.subscription_ends_at;
  const widgets = widgetsFor("center").filter((w) => allowed(w.perm));

  const widgetGrid = widgets.length ? h("div", { class: "grid-2" }, widgets.map((w) => {
    const body = h("div", { class: "card-body" });
    const card = h("section", { class: "card", style: w.span === 2 ? "grid-column:1/-1" : null },
      w.title ? h("div", { class: "card-header" }, h("h2", t(w.title))) : null, body);
    Promise.resolve().then(() => w.render(body, ctx)).catch((e) => body.replaceChildren(errorState(e)));
    return card;
  })) : null;

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("div", h("h1", center?.name || t("core.nav.overview")),
        h("p", { class: "subtitle" }, t("core.center.overview_sub"))),
      status ? h("div", { class: "row" }, statusPill(status, "core.center.status"),
        ends ? h("span", { class: "text-sm text-muted" }, t("core.center.until", { date: formatDate(ends, { year: "always", month: "short" }) })) : null) : null),
    h("section", { class: "stack" },
      h("h2", t("core.center.departments")),
      depts.length ? h("div", { class: "dept-grid" }, depts.map(departmentCard))
        : emptyState({ icon: "building", title: t("core.dept.none_title"), message: t("core.center.no_departments") })),
    widgetGrid ? h("section", { class: "stack", style: "margin-top:32px" }, widgetGrid) : null);
}
