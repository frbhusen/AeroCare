// Appointments module UI: center + department "appointments" slots, dashboard widget.
import { api, h, t, loadStylesheet, todayISO, areaHref, mount, emptyState } from "../core/index.js";
import { en, ar } from "./i18n.js";
import { renderSchedule } from "./schedule.js";
import { pill, timeRange } from "./common.js";

export function register(registry) {
  loadStylesheet(new URL("./appointments.css", import.meta.url));
  registry.i18n({ en, ar });
  for (const area of ["center", "department"]) {
    registry.route({ area, ...(area === "department" ? { env: "*" } : {}), path: "appointments", title: "appointments.title",
      perm: "appointments.view", render: renderSchedule });
    registry.menu({ area, ...(area === "department" ? { env: "*" } : {}), key: "appointments", path: "appointments",
      label: "appointments.menu", icon: "calendar", perm: "appointments.view", order: 20 });
    registry.widget({ area, ...(area === "department" ? { env: "*" } : {}), key: "appointments-today", title: "appointments.widget.today",
      perm: "appointments.view", order: 20, render: renderWidget });
  }
}

/** Today's appointments (first 8) for the dashboard. */
async function renderWidget(el, ctx) {
  const query = { from: todayISO(), to: todayISO(), per_page: 8, status: "scheduled,arrived,in_progress" };
  if (ctx?.area === "department" && ctx.dept) query.department_id = ctx.dept.id;
  const res = await api.get("/appointments", { query });
  const link = h("a", { class: "btn btn-link btn-sm", href: areaHref(ctx, "appointments") }, t("appointments.widget.open"));
  if (!res.items.length) return mount(el, emptyState({ icon: "calendar", title: t("appointments.empty_day") }), link);
  mount(el, h("ul", { class: "appt-widget-list" }, res.items.map((a) => h("li", { class: "row row-between" },
    h("span", timeRange(a), " ", h("strong", a.patient.name || "—"), h("span", { class: "text-muted text-sm" }, ` · ${a.clinic.name}`)),
    pill(a.status)))),
  h("div", { class: "text-muted text-sm" }, t("appointments.count", { n: res.total ?? res.items.length })), link);
}
