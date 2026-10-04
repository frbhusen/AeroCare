// Department environment core: dashboard route ("#/d/<id>") + default menu slots.
// Specialty modules add their menu items/routes for their environment (registry env filter).
import { h } from "./dom.js";
import { t, localName } from "./i18n.js";
import { clinicsOf } from "./state.js";
import { menusFor, widgetsFor } from "./registry.js";
import { allowed } from "./perm.js";
import { deptHref } from "./router.js";
import { icon } from "../components/icons.js";
import { comingSoon, errorState } from "../components/states.js";

export function registerDepartmentCore(reg) {
  reg.route({ area: "department", path: "", title: "core.nav.dashboard", render: renderDashboard });
  reg.menu({ area: "department", key: "dashboard", path: "", label: "core.nav.dashboard", icon: "home", order: 0 });
  // Slots for shared domains every environment uses (replaced by the patients/appointments modules).
  for (const s of [
    { key: "patients", path: "patients", label: "core.nav.patients", icon: "users", perm: "patients.view", order: 10 },
    { key: "appointments", path: "appointments", label: "core.nav.appointments", icon: "calendar", perm: "appointments.view", order: 20 },
  ]) {
    reg.route({ area: "department", path: s.path, perm: s.perm, title: s.label, placeholder: true, render: () => comingSoon(s.label) });
    reg.menu({ area: "department", ...s, placeholder: true });
  }
}

function renderDashboard(ctx) {
  const d = ctx.dept;
  const clinics = clinicsOf(d.id);
  const tiles = menusFor("department", d.environment).filter((m) => m.path && allowed(m.perm));
  const widgets = widgetsFor("department", d.environment).filter((w) => allowed(w.perm));
  ctx.setTitle(localName(d, d.name));
  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("div", h("h1", d.name), h("p", { class: "subtitle" }, localName(d, d.name) !== d.name ? localName(d) : t("core.dept.environment"))),
      clinics.length ? h("div", { class: "row" }, clinics.map((c) => h("span", { class: "badge", title: c.location || "" },
        icon("building"), c.name))) : null),
    tiles.length ? h("div", { class: "tile-grid" }, tiles.map((m) => h("a", { class: "tile", href: deptHref(d.id, m.path) },
      icon(m.icon || "layers"), h("span", t(m.label))))) : null,
    widgets.length ? h("div", { class: "grid-2", style: "margin-top:24px" }, widgets.map((w) => {
      const body = h("div", { class: "card-body" });
      Promise.resolve().then(() => w.render(body, ctx)).catch((e) => body.replaceChildren(errorState(e)));
      return h("section", { class: "card", style: w.span === 2 ? "grid-column:1/-1" : null },
        w.title ? h("div", { class: "card-header" }, h("h2", t(w.title))) : null, body);
    })) : null);
}
