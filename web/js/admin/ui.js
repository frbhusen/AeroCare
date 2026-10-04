// Small shared UI helpers for the admin and center-admin modules (no data of their own).
import {
  api, h, t, icon, dataTable, formatDateTime, formatNumber, formatBytes, statusPill, openModal, createForm, toast,
  toastApiError,
} from "../core/index.js";

export function pageHeader(title, subtitle, ...actions) {
  return h("div", { class: "page-header" },
    h("div", h("h1", title), subtitle ? h("p", { class: "subtitle" }, subtitle) : null),
    actions.length ? h("div", { class: "page-actions" }, actions) : null);
}

export function btn(label, onClick, { variant, iconName, small = false, disabled = false, title } = {}) {
  return h("button", { class: ["btn", variant && `btn-${variant}`, small && "btn-sm"], type: "button", disabled, title,
    onClick: async (e) => {
      const b = e.currentTarget;
      b.classList.add("is-loading");
      b.disabled = true;
      try {
        await onClick(e);
      } catch (err) {
        if (err?.status !== undefined || err?.message) toastApiError(err);
      } finally {
        b.classList.remove("is-loading");
        b.disabled = false;
      }
    } }, iconName ? icon(iconName) : null, label);
}

export function stat(label, value, sub) {
  return h("div", { class: "card stat" }, h("div", { class: "stat-label" }, label), h("div", { class: "stat-value num" }, value),
    sub ? h("div", { class: "text-sm text-muted" }, sub) : null);
}

/** Usage meter: used of max (max null = unlimited). */
export function usageBar(used, max, { bytes = false } = {}) {
  const fmt = (v) => (bytes ? formatBytes(v) : formatNumber(v));
  const pct = max ? Math.min(100, Math.round((100 * used) / max)) : 0;
  const level = !max ? "ok" : pct >= 100 ? "full" : pct >= 80 ? "high" : "ok";
  return h("div", { class: "adm-usage" },
    h("div", { class: "row-between text-sm" },
      h("span", { class: "num" }, max == null ? t("admin.ui.used_unlimited", { used: fmt(used) })
        : t("admin.ui.used_of", { used: fmt(used), max: fmt(max) })),
      max ? h("span", { class: "text-muted num" }, `${pct}%`) : null),
    h("div", { class: `adm-bar adm-bar--${level}`, role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100",
      "aria-valuenow": String(pct) }, h("span", { style: { inlineSize: `${max ? pct : 0}%` } })));
}

export function kv(rows) {
  return h("dl", { class: "kv" }, rows.filter(Boolean).flatMap(([k, v]) => [h("dt", k), h("dd", v ?? "—")]));
}

export const centerStatus = (s) => statusPill(s, "core.center.status");
export const userStatus = (s) => statusPill(s, "core.status");

/** Simple form modal. fields: createForm field specs. submit(values) -> result (closes on success). */
export function formModal({ title, fields, values, submit, submitLabel, size = "md", columns = 2, intro }) {
  let modal;
  const form = createForm({
    fields, values, columns, submitLabel,
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      await submit(v, form);
      modal.close();
    },
  });
  modal = openModal({ title, size, body: [intro || null, form.el] });
  return { modal, form };
}

/** Message for a 409 version conflict with a reload action. */
export function conflictToast(reload) {
  toast(t("admin.ui.conflict"), { type: "warning", duration: 0, action: { label: t("admin.ui.reload"), onClick: reload } });
}

/** Shows `err` on a form; version conflicts also get a reload toast. */
export function rethrowWithConflict(err, reload) {
  if (err?.code === "version_conflict" && reload) conflictToast(reload);
  throw err;
}

/** Audit log table used by the superadmin portal and the center audit view. */
export function auditTable({ url, baseQuery = {}, showCenter = false, extraFilters = [] }) {
  const cat = h("select", { class: "select", "aria-label": t("admin.audit.category") },
    h("option", { value: "" }, t("admin.audit.all_categories")),
    ["login", "department", "clinic", "user"].map((c) => h("option", { value: c }, t(`admin.audit.cat.${c}`))));
  const act = h("select", { class: "select", "aria-label": t("admin.audit.action") },
    h("option", { value: "" }, t("admin.audit.all_actions")),
    ["success", "failure", "create", "edit", "delete"].map((c) => h("option", { value: c }, t(`admin.audit.act.${c}`))));
  const from = h("input", { class: "input", type: "date", "aria-label": t("admin.audit.from") });
  const to = h("input", { class: "input", type: "date", "aria-label": t("admin.audit.to") });
  const table = dataTable({
    perPage: 50,
    query: baseQuery,
    search: { placeholder: t("admin.audit.search") },
    toolbar: [cat, act, h("label", { class: "row text-sm" }, t("admin.audit.from"), from),
      h("label", { class: "row text-sm" }, t("admin.audit.to"), to), ...extraFilters],
    columns: [
      { key: "created_at", label: t("admin.audit.when"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.created_at)) },
      showCenter ? { key: "center", label: t("admin.audit.center"), render: (r) => r.center_name || (r.health_center_id ? `#${r.health_center_id}` : t("admin.audit.platform")) } : null,
      { key: "category", label: t("admin.audit.category"), render: (r) => t(`admin.audit.cat.${r.category}`) },
      { key: "action", label: t("admin.audit.action"), render: (r) => statusPill(r.action, "admin.audit.act",
        { success: "success", failure: "danger", create: "info", edit: "neutral", delete: "warning" }[r.action]) },
      { key: "actor", label: t("admin.audit.actor"), render: (r) => r.actor_name ? h("span", r.actor_name,
        r.actor_role ? h("span", { class: "text-muted text-sm" }, ` · ${t(`admin.role.${r.actor_role}`)}`) : null) : "—" },
      { key: "target", label: t("admin.audit.target"), render: (r) => h("span", r.target_label || "—",
        r.details?.fields?.length ? h("div", { class: "text-sm text-muted" }, t("admin.audit.fields", { fields: r.details.fields.join(", ") })) : null) },
      { key: "ip", label: t("admin.audit.ip"), render: (r) => h("span", { class: "ltr text-sm" }, r.ip || "") },
    ].filter(Boolean),
    fetch: (q) => api.get(url, { query: q }),
    empty: { icon: "clipboard", title: t("admin.audit.empty") },
  });
  const apply = () => table.setQuery({ category: cat.value || null, action: act.value || null,
    date_from: from.value || null, date_to: to.value || null });
  [cat, act, from, to].forEach((el) => el.addEventListener("change", apply));
  return table;
}
