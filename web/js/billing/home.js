// Billing home screens: sub navigation, overview (summary), invoices list, outstanding balances.
import { api, h, t, mount, dataTable, navigate, formatDate, formatMoney, can, getDepartments, localName, todayISO,
  loadingState, errorState, emptyState, icon, offlineCopyBanner } from "../core/index.js";
import { link, basePath, invoiceStatus, clinicOptions, clinicName, areaFilter, money, moneyStat, showDeptFilter } from "./util.js";

/** Page frame with title, actions and the billing sub navigation. */
export function frame(ctx, active, ...content) {
  const tabsDef = [
    ["overview", "", "billing.tab.overview", "billing.view"],
    ["invoices", "invoices", "billing.tab.invoices", "billing.view"],
    ["outstanding", "outstanding", "billing.tab.outstanding", "billing.view"],
    ["services", "services", "billing.tab.services", "billing.view"],
    ["templates", "templates", "billing.tab.templates", "settings.view"],
  ];
  const nav = h("nav", { class: "tabs billing-subnav no-print", role: "tablist" },
    tabsDef.filter((x) => can(x[3])).map(([key, sub, label]) =>
      h("a", { class: "tab", role: "tab", href: link(ctx, sub), "aria-selected": String(key === active) }, t(label))));
  const title = ctx.area === "center" ? t("billing.financial") : t("billing.title");
  return h("div", { class: "page billing-page" },
    h("div", { class: "page-header" }, h("h1", title),
      can("billing.create") ? h("div", { class: "page-actions" },
        h("a", { class: "btn btn-primary", href: link(ctx, "new") }, icon("plus"), t("billing.new_invoice"))) : null),
    nav, ...content);
}

function monthStart() {
  const d = todayISO();
  return `${d.slice(0, 8)}01`;
}

function select(name, options, value, onChange, emptyLabel) {
  const el = h("select", { class: "select", name, "aria-label": emptyLabel },
    emptyLabel ? h("option", { value: "" }, emptyLabel) : null,
    options.map((o) => h("option", { value: String(o.value) }, o.label)));
  el.value = value == null ? "" : String(value);
  el.addEventListener("change", () => onChange(el.value));
  return el;
}

function dateInput(label, value, onChange) {
  const el = h("input", { class: "input", type: "date", value, "aria-label": label });
  el.addEventListener("change", () => onChange(el.value));
  return h("label", { class: "billing-filter" }, h("span", { class: "text-sm text-muted" }, label), el);
}

const deptOptions = () => getDepartments().map((d) => ({ value: d.id, label: localName(d, d.name) }));

// ---------------------------------------------------------------- overview
export function renderOverview(ctx) {
  const q = { date_from: ctx.query.date_from || monthStart(), date_to: ctx.query.date_to || todayISO(),
    group_by: ctx.query.group_by || (ctx.area === "center" ? "department" : "clinic"),
    clinic_id: ctx.query.clinic_id || "", department_id: ctx.query.department_id || "" };
  const out = h("div", { class: "stack" });

  const go = (patch) => navigate(link(ctx, "", { ...q, ...patch }), { replace: true });
  const quick = (from, to) => go({ date_from: from, date_to: to });
  const groups = ["department", "clinic", "doctor", "none"].filter((g) => !(g === "department" && ctx.area !== "center"));
  const filters = h("div", { class: "card card-pad billing-filters" },
    dateInput(t("billing.from"), q.date_from, (v) => go({ date_from: v })),
    dateInput(t("billing.to"), q.date_to, (v) => go({ date_to: v })),
    h("div", { class: "btn-group" },
      h("button", { class: "btn btn-sm", type: "button", onClick: () => quick(todayISO(), todayISO()) }, t("billing.overview.today")),
      h("button", { class: "btn btn-sm", type: "button", onClick: () => quick(monthStart(), todayISO()) }, t("billing.overview.month"))),
    showDeptFilter(ctx) ? select("department_id", deptOptions(), q.department_id, (v) => go({ department_id: v }), t("billing.all_departments")) : null,
    select("clinic_id", clinicOptions(ctx), q.clinic_id, (v) => go({ clinic_id: v }), t("billing.all_clinics")),
    h("label", { class: "billing-filter" }, h("span", { class: "text-sm text-muted" }, t("billing.overview.group")),
      select("group_by", groups.map((g) => ({ value: g, label: t(`billing.overview.by.${g}`) })), q.group_by, (v) => go({ group_by: v }))));

  const body = h("div", loadingState());
  (async () => {
    try {
      const res = await api.get("/billing/summary", { query: { ...q, ...areaFilter(ctx) }, cache: true });
      const tot = res.totals;
      const stats = h("div", { class: "grid-4 billing-stats" },
        moneyStat(t("billing.overview.revenue"), tot.revenue),
        moneyStat(t("billing.overview.received"), tot.payments_received, "paid"),
        moneyStat(t("billing.overview.outstanding_period"), tot.outstanding_in_period),
        moneyStat(t("billing.overview.outstanding_total"), tot.outstanding_total, Number(tot.outstanding_total) > 0 ? "due" : null));
      let table = null;
      if (res.rows) {
        const name = (r) => (r.key == null ? t("billing.overview.unassigned")
          : r.name || (res.group_by === "clinic" ? clinicName(r.key) : `#${r.key}`));
        table = res.rows.length ? h("div", { class: "card table-wrap" }, h("table", { class: "table table-stack" },
          h("thead", h("tr", [t(`billing.overview.by.${res.group_by}`), t("billing.overview.invoices"), t("billing.overview.revenue"),
            t("billing.overview.discounts"), t("billing.overview.received"), t("billing.overview.outstanding_total")].map((x) => h("th", x)))),
          h("tbody", res.rows.map((r) => h("tr",
            h("td", { "data-label": t(`billing.overview.by.${res.group_by}`) }, name(r)),
            h("td", { class: "num", "data-label": t("billing.overview.invoices") }, String(r.invoice_count)),
            h("td", { class: "num", "data-label": t("billing.overview.revenue") }, money(r.revenue)),
            h("td", { class: "num", "data-label": t("billing.overview.discounts") }, money(r.discounts)),
            h("td", { class: "num", "data-label": t("billing.overview.received") }, money(r.payments_received)),
            h("td", { class: "num", "data-label": t("billing.overview.outstanding_total") }, money(r.outstanding_total)))))))
          : emptyState({ icon: "wallet" });
      }
      mount(body, offlineCopyBanner(res), stats, h("p", { class: "text-sm text-muted" }, t("billing.overview.range_hint")), table);
    } catch (e) {
      mount(body, errorState(e, () => renderOverview(ctx)));
    }
  })();
  mount(out, filters, body);
  return frame(ctx, "overview", out);
}

// ---------------------------------------------------------------- invoices list
export function invoiceColumns(ctx, { patient = true } = {}) {
  return [
    { key: "number", label: t("billing.number"), render: (r) => h("a", { class: "ltr nowrap", href: link(ctx, `invoices/${r.id}`) }, r.number) },
    { key: "date", label: t("billing.date"), render: (r) => formatDate(r.issued_at || r.created_at) },
    patient ? { key: "patient_name", label: t("billing.patient"), render: (r) => h("span", r.patient_name || "",
      r.patient_code ? h("span", { class: "text-muted text-sm ltr" }, ` ${r.patient_code}`) : null) } : null,
    { key: "clinic", label: t("billing.clinic"), render: (r) => r.clinic_name || clinicName(r.clinic_id) },
    { key: "status", label: t("billing.status"), render: (r) => invoiceStatus(r.status) },
    { key: "total", label: t("billing.total"), class: "num", render: (r) => money(r.total) },
    { key: "paid", label: t("billing.paid"), class: "num", render: (r) => money(r.paid_total) },
    { key: "balance", label: t("billing.remaining"), class: "num", render: (r) => (r.status === "void" ? "" : money(r.balance)) },
  ].filter(Boolean);
}

function sumsBar(el, sums) {
  mount(el, sums ? h("div", { class: "row billing-sums text-sm" },
    h("span", t("billing.total"), ": ", h("strong", { class: "num ltr" }, formatMoney(sums.total))),
    h("span", t("billing.paid"), ": ", h("strong", { class: "num ltr" }, formatMoney(sums.paid))),
    h("span", t("billing.remaining"), ": ", h("strong", { class: "num ltr" }, formatMoney(sums.balance)))) : null);
}

function listPage(ctx, active, fixedStatus) {
  const query = { ...areaFilter(ctx), status: fixedStatus || ctx.query.status || "", clinic_id: ctx.query.clinic_id || "",
    date_from: ctx.query.date_from || "", date_to: ctx.query.date_to || "" };
  if (showDeptFilter(ctx)) query.department_id = ctx.query.department_id || "";
  const sums = h("div");
  const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v != null));
  const statuses = ["draft", "issued", "partially_paid", "paid", "void"];
  const toolbar = [
    fixedStatus ? null : select("status", statuses.map((s) => ({ value: s, label: t(`billing.status.${s}`) })), query.status,
      (v) => table.setQuery({ status: v }), t("billing.all_statuses")),
    showDeptFilter(ctx) ? select("department_id", deptOptions(), query.department_id, (v) => table.setQuery({ department_id: v }), t("billing.all_departments")) : null,
    select("clinic_id", clinicOptions(ctx), query.clinic_id, (v) => table.setQuery({ clinic_id: v }), t("billing.all_clinics")),
    dateInput(t("billing.from"), query.date_from, (v) => table.setQuery({ date_from: v })),
    dateInput(t("billing.to"), query.date_to, (v) => table.setQuery({ date_to: v })),
  ];
  const table = dataTable({
    columns: invoiceColumns(ctx),
    query,
    search: { placeholder: t("billing.search_invoices") },
    toolbar,
    onRowClick: (r) => navigate(link(ctx, `invoices/${r.id}`)),
    fetch: async (q) => {
      const res = await api.get("/billing/invoices", { query: clean(q), cache: true });
      sumsBar(sums, res.sums);
      return res;
    },
    empty: { icon: "wallet", title: t("core.empty.title") },
  });
  return frame(ctx, active, fixedStatus ? h("p", { class: "text-muted" }, t("billing.outstanding.hint")) : null, table.el, sums);
}

export const renderInvoices = (ctx) => listPage(ctx, "invoices");
export const renderOutstanding = (ctx) => listPage(ctx, "outstanding", "issued,partially_paid");
export { basePath };
