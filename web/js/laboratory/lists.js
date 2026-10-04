// Lab queue (laboratory side), sent requests (requesting side), dashboard widget.
import { api, h, t, dataTable, formatDateTime, deptHref, icon, navigate, formatNumber } from "../core/index.js";
import { labStatus, priorityPill } from "./common.js";
import { openLabRequestDialog } from "./public.js";

export function requestColumns({ from = true, lab = false } = {}) {
  return [
    { key: "patient", label: t("laboratory.col.patient"), render: (r) => h("div",
      h("strong", r.patient?.full_name || ""), h("div", { class: "text-xs text-muted ltr" }, r.patient?.code || "")) },
    { key: "tests", label: t("laboratory.col.tests"), render: (r) => h("span", { class: "lab-tests-cell" }, (r.tests || []).join(", ")) },
    { key: "priority", label: t("laboratory.col.priority"), render: (r) => priorityPill(r.priority) },
    { key: "status", label: t("laboratory.col.status"), render: (r) => h("span", { class: "row" }, labStatus(r.status),
      r.abnormal_count ? h("span", { class: "pill pill--danger" }, t("laboratory.detail.abnormal_count", { n: r.abnormal_count })) : null) },
    from ? { key: "from", label: t("laboratory.col.from"), render: (r) => h("div", r.requesting_clinic?.name || "",
      h("div", { class: "text-xs text-muted" }, r.requested_by?.name || "")) } : null,
    lab ? { key: "lab", label: t("laboratory.col.lab"), render: (r) => r.lab_clinic?.name || r.lab_department?.name || "" } : null,
    { key: "requested_at", label: t("laboratory.col.requested"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.requested_at)) },
  ].filter(Boolean);
}

function statusFilter(onChange, values, initial) {
  const sel = h("select", { class: "select", style: "width:auto", "aria-label": t("laboratory.col.status") },
    values.map((v) => h("option", { value: v }, t(v ? `laboratory.status.${v}` : "laboratory.status.all"))));
  sel.value = initial;
  sel.addEventListener("change", () => onChange(sel.value));
  return sel;
}

function priorityFilter(onChange) {
  const sel = h("select", { class: "select", style: "width:auto", "aria-label": t("laboratory.col.priority") },
    h("option", { value: "" }, t("laboratory.filter.priority_all")),
    ["urgent", "routine"].map((p) => h("option", { value: p }, t(`laboratory.priority.${p}`))));
  sel.addEventListener("change", () => onChange(sel.value));
  return sel;
}

/** #/d/<lab dept>/lab/queue */
export function renderQueue(ctx) {
  ctx.setTitle(t("laboratory.queue.title"));
  const table = dataTable({
    columns: requestColumns({ from: true }),
    query: { status: "active" },
    fetch: (q) => api.get("/lab/queue", { query: clean(q), cache: true }),
    onRowClick: (r) => navigate(`d/${ctx.dept.id}/lab/requests/${r.id}`),
    rowClass: (r) => (r.priority === "urgent" && r.status !== "completed" ? "lab-row-urgent" : ""),
    toolbar: [
      statusFilter((v) => table.setQuery({ status: v }), ["active", "requested", "in_progress", "completed", "cancelled"], "active"),
      priorityFilter((v) => table.setQuery({ priority: v })),
      h("button", { class: "btn btn-ghost btn-icon", type: "button", "aria-label": t("laboratory.action.reload"), onClick: () => table.reload() }, icon("refresh")),
    ],
    empty: { icon: "flask", title: t("laboratory.empty.queue") },
  });
  const iv = setInterval(() => document.visibilityState === "visible" && table.reload(), 60000);
  ctx.onLeave = () => clearInterval(iv);
  return h("div", { class: "page" }, h("div", { class: "page-header" }, h("h1", t("laboratory.queue.title"))), table.el);
}

/** #/d/<any dept>/lab/sent : requests sent by this department's clinics. */
export function renderSent(ctx) {
  ctx.setTitle(t("laboratory.sent.title"));
  const table = dataTable({
    columns: requestColumns({ from: true, lab: true }),
    query: { department_id: ctx.dept.id },
    fetch: (q) => api.get("/lab/requests", { query: clean(q), cache: true }),
    onRowClick: (r) => navigate(`d/${ctx.dept.id}/lab/requests/${r.id}`),
    toolbar: [
      statusFilter((v) => table.setQuery({ status: v }), ["", "active", "requested", "in_progress", "completed", "cancelled"], ""),
      priorityFilter((v) => table.setQuery({ priority: v })),
    ],
    empty: { icon: "flask", title: t("laboratory.empty.sent") },
  });
  const newBtn = h("button", { class: "btn btn-primary", type: "button",
    onClick: () => openLabRequestDialog({ departmentId: ctx.dept.id, onCreated: () => table.reload() }) },
  icon("plus"), t("laboratory.action.new_request"));
  return h("div", { class: "page" },
    h("div", { class: "page-header" }, h("h1", t("laboratory.sent.title")), h("div", { class: "page-actions" }, newBtn)),
    table.el);
}

/** Dashboard widget for laboratory departments. */
export async function renderWidget(el, ctx) {
  const res = await api.get("/lab/queue", { query: { status: "active", per_page: 100 } });
  const items = res.items || [];
  const count = (f) => formatNumber(items.filter(f).length);
  el.replaceChildren(h("div", { class: "stack" },
    h("div", { class: "grid-3 lab-stats" },
      stat(t("laboratory.widget.urgent"), count((r) => r.priority === "urgent"), "danger"),
      stat(t("laboratory.widget.requested"), count((r) => r.status === "requested")),
      stat(t("laboratory.widget.in_progress"), count((r) => r.status === "in_progress"))),
    h("a", { class: "btn btn-sm", href: deptHref(ctx.dept.id, "lab/queue") }, t("laboratory.widget.open_queue"))));
}

const stat = (label, value, tone) => h("div", { class: ["lab-stat", tone && `lab-stat--${tone}`] },
  h("div", { class: "lab-stat-value num" }, value), h("div", { class: "text-sm text-muted" }, label));

export function clean(q) {
  const out = {};
  for (const [k, v] of Object.entries(q || {})) if (v !== "" && v != null) out[k] = v;
  return out;
}
