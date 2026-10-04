// Inventory UI: center slot "inventory" + department-environment Inventory page (every department).
import { api, h, mount, tabs, href, deptHref, icon, loadStylesheet, formatNumber } from "../core/index.js";
import { I18N } from "./i18n.js";
import { tt } from "./shared.js";
import { itemsTab } from "./items.js";
import { stockTab, movementsTab, transfersTab, lowStockTab, expiryTab } from "./reports.js";

const TABS = [
  { key: "stock", render: stockTab },
  { key: "items", render: itemsTab },
  { key: "movements", render: movementsTab },
  { key: "transfers", render: transfersTab },
  { key: "low", render: lowStockTab },
  { key: "expiry", render: expiryTab },
];

export function register(registry) {
  loadStylesheet(new URL("./inventory.css", import.meta.url));
  registry.i18n(I18N);
  registry.route({ area: "center", path: "inventory", title: "inventory.title", perm: "inventory.view", render });
  registry.menu({ area: "center", key: "inventory", path: "inventory", label: "inventory.menu", icon: "box", perm: "inventory.view", order: 80 });
  registry.route({ area: "department", env: "*", path: "inventory", title: "inventory.title", perm: "inventory.view", render });
  registry.menu({ area: "department", env: "*", key: "inventory", path: "inventory", label: "inventory.menu", icon: "box", perm: "inventory.view", order: 80 });
  registry.widget({ area: "department", env: "*", key: "inventory-alerts", title: "inventory.widget.title", perm: "inventory.view", order: 80, render: renderWidget });
  registry.widget({ area: "center", key: "inventory-alerts", title: "inventory.widget.title", perm: "inventory.view", order: 80, render: renderWidget });
}

function render(ctx) {
  let cleanup = null;
  const stopCurrent = () => {
    if (typeof cleanup === "function") cleanup();
    cleanup = null;
  };
  ctx.onLeave = stopCurrent;
  const active = TABS.some((x) => x.key === ctx.query?.tab) ? ctx.query.tab : "stock";
  const tb = tabs(TABS.map((x) => ({
    key: x.key,
    label: tt(`tab.${x.key}`),
    render: (panel) => {
      stopCurrent();
      Promise.resolve(x.render(ctx, panel)).then((stop) => { cleanup = stop; });
    },
  })), {
    active,
    onChange: (key) => {
      // Keep the tab in the URL (bookmarkable) without re-rendering the page.
      const base = ctx.area === "department" ? deptHref(ctx.dept.id, "inventory", { tab: key }) : href("center/inventory", { tab: key });
      history.replaceState(null, "", base);
    },
  });
  const title = ctx.area === "department" ? tt("title_dept", { dept: ctx.dept.name }) : tt("title");
  return h("div", { class: "page inv-page" },
    h("div", { class: "page-header" }, h("div", h("h1", title), h("p", { class: "subtitle" }, tt("subtitle")))),
    tb.el);
}

async function renderWidget(el, ctx) {
  const q = ctx.area === "department" ? { department_id: ctx.dept.id } : {};
  const [low, exp] = await Promise.all([
    api.get("/inventory/low-stock", { query: { ...q, per_page: 5 }, cache: true }),
    api.get("/inventory/expiry", { query: { ...q, days: 30, per_page: 5 }, cache: true }),
  ]);
  const link = (tab) => (ctx.area === "department" ? deptHref(ctx.dept.id, "inventory", { tab }) : href("center/inventory", { tab }));
  mount(el, h("div", { class: "grid-2" },
    h("a", { class: "stat inv-stat", href: link("low") }, h("span", { class: "stat-label" }, icon("alert"), tt("widget.low")),
      h("span", { class: "stat-value" }, formatNumber(low.total))),
    h("a", { class: "stat inv-stat", href: link("expiry") }, h("span", { class: "stat-label" }, icon("clock"), tt("widget.expiring")),
      h("span", { class: "stat-value" }, formatNumber(exp.total)))),
  low.items.length ? h("ul", { class: "inv-widget-list" }, low.items.map((r) => h("li", r.item.name,
    h("span", { class: "text-muted num ltr" }, ` ${formatNumber(r.quantity, { max: 3 })}`)))) : null);
}
