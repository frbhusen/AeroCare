// Superadmin: department types (modules catalog, incl. custom) and subscription plans.
import { api, h, t, icon, dataTable, formatBytes, formatNumber, localName, safeColor, toastSuccess, confirmDialog, toastApiError } from "../core/index.js";
import { pageHeader, formModal } from "./ui.js";

const LIMITS = ["max_departments", "max_head_doctors", "max_doctors", "max_receptionists", "max_clinics"];
const GB = 1024 ** 3;
const ICONS = ["stethoscope", "tooth", "sparkles", "baby", "heart", "eye", "brain", "apple", "flask", "pill", "scan", "hospital", "clipboard"];

// ---------------------------------------------------------------- department types
export function renderTypes() {
  const table = dataTable({
    columns: [
      { key: "name", label: t("admin.types.name"), render: (x) => h("div", { class: "row" },
        h("span", { class: "adm-swatch", style: { background: safeColor(x.color) || "var(--neutral-bg)" } }, icon(x.icon || "stethoscope")),
        h("div", h("strong", localName(x, x.name_en)), h("div", { class: "text-sm text-muted" }, `${x.name_en} · ${x.name_ar}`))) },
      { key: "code", label: t("admin.types.code"), render: (x) => h("span", { class: "ltr text-sm" }, x.code) },
      { key: "environment", label: t("admin.types.environment"), render: (x) => h("span", t(`admin.env.${x.environment}`),
        x.is_custom ? h("span", { class: "badge", style: "margin-inline-start:6px" }, t("admin.types.custom")) : null) },
      { key: "center_count", label: t("admin.types.centers"), render: (x) => formatNumber(x.center_count) },
      { key: "is_active", label: t("admin.types.status"), render: (x) => h("span", { class: `pill pill--${x.is_active ? "active" : "archived"}` },
        t(x.is_active ? "admin.ui.active" : "admin.ui.inactive")) },
      { key: "actions", label: "", class: "actions", render: (x) => h("div", { class: "btn-group" },
        h("button", { class: "btn btn-sm", type: "button", onClick: () => editType(x, table) }, icon("edit"), t("admin.ui.edit")),
        h("button", { class: "btn btn-sm", type: "button", onClick: () => toggleType(x, table) },
          t(x.is_active ? "admin.ui.deactivate" : "admin.ui.activate"))) },
    ],
    fetch: () => api.get("/admin/department-types"),
  });
  const add = h("button", { class: "btn btn-primary", type: "button", onClick: () => editType(null, table) }, icon("plus"), t("admin.types.new"));
  return h("div", { class: "page" }, pageHeader(t("admin.types.title"), t("admin.types.subtitle"), add),
    h("div", { class: "alert alert-warning" }, icon("info"), h("div", t("admin.types.custom_note"))), table.el);
}

function editType(x, table) {
  formModal({
    title: x ? t("admin.types.edit", { name: x.name_en }) : t("admin.types.new"),
    intro: x ? null : h("p", { class: "text-muted" }, t("admin.types.custom_note")),
    fields: [
      { name: "name_en", label: t("admin.types.name_en"), required: true, maxLength: 100 },
      { name: "name_ar", label: t("admin.types.name_ar"), required: true, maxLength: 100, attrs: { dir: "rtl" } },
      { name: "icon", label: t("admin.types.icon"), type: "select", options: ICONS.map((i) => ({ value: i, label: i })) },
      { name: "color", label: t("admin.types.color"), type: "color" },
      { name: "sort_order", label: t("admin.types.sort_order"), type: "number", min: 0 },
    ],
    values: x || { icon: "stethoscope", color: "#2563eb", sort_order: 1000 },
    submit: async (v) => {
      if (x) await api.patch(`/admin/department-types/${x.id}`, v);
      else await api.post("/admin/department-types", v);
      toastSuccess(t("admin.ui.saved"));
      table.reload();
    },
  });
}

async function toggleType(x, table) {
  if (x.is_active && !(await confirmDialog({ message: t("admin.types.deactivate_confirm", { name: x.name_en }), danger: true }))) return;
  try {
    await api.patch(`/admin/department-types/${x.id}`, { is_active: !x.is_active });
    table.reload();
  } catch (e) {
    toastApiError(e);
  }
}

// ---------------------------------------------------------------- plans
const lim = (v) => (v == null ? t("admin.limit.unlimited") : formatNumber(v));

export function renderPlans() {
  const table = dataTable({
    columns: [
      { key: "name", label: t("admin.plans.name"), render: (p) => h("div", h("strong", p.name), h("div", { class: "text-sm text-muted ltr" }, p.code)) },
      ...LIMITS.map((k) => ({ key: k, label: t(`admin.limit.${k}`), render: (p) => h("span", { class: "num" }, lim(p[k])) })),
      { key: "storage", label: t("admin.limit.storage"), render: (p) => (p.storage_quota_bytes ? formatBytes(p.storage_quota_bytes) : "—") },
      { key: "center_count", label: t("admin.plans.centers"), render: (p) => formatNumber(p.center_count) },
      { key: "is_active", label: t("admin.types.status"), render: (p) => h("span", { class: `pill pill--${p.is_active ? "active" : "archived"}` },
        t(p.is_active ? "admin.ui.active" : "admin.ui.inactive")) },
      { key: "actions", label: "", class: "actions", render: (p) => h("div", { class: "btn-group" },
        h("button", { class: "btn btn-sm", type: "button", onClick: () => editPlan(p, table) }, icon("edit"), t("admin.ui.edit")),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": t("admin.ui.delete"), disabled: p.center_count > 0,
          title: p.center_count > 0 ? t("admin.plans.in_use") : null, onClick: () => deletePlan(p, table) }, icon("trash"))) },
    ],
    fetch: () => api.get("/admin/plans"),
  });
  const add = h("button", { class: "btn btn-primary", type: "button", onClick: () => editPlan(null, table) }, icon("plus"), t("admin.plans.new"));
  return h("div", { class: "page" }, pageHeader(t("admin.plans.title"), t("admin.plans.subtitle"), add), table.el);
}

function editPlan(p, table) {
  const values = p ? { ...p, storage_gb: p.storage_quota_bytes ? +(p.storage_quota_bytes / GB).toFixed(2) : null } : { is_active: true, storage_gb: 2 };
  formModal({
    title: p ? t("admin.plans.edit", { name: p.name }) : t("admin.plans.new"),
    intro: h("p", { class: "text-muted" }, t("admin.plans.help")),
    fields: [
      { name: "name", label: t("admin.plans.name"), required: true, maxLength: 100 },
      { name: "code", label: t("admin.plans.code"), required: true, help: t("admin.plans.code_help"), maxLength: 40 },
      ...LIMITS.map((k) => ({ name: k, label: t(`admin.limit.${k}`), type: "number", min: 0, placeholder: t("admin.limit.unlimited") })),
      { name: "storage_gb", label: t("admin.limit.storage_gb"), type: "number", min: 0.01, step: "0.01" },
      { name: "is_active", label: t("admin.ui.active"), type: "checkbox" },
    ],
    values,
    submit: async (v) => {
      const body = { name: v.name, code: v.code, is_active: v.is_active,
        storage_quota_bytes: v.storage_gb ? Math.round(Number(v.storage_gb) * GB) : null };
      LIMITS.forEach((k) => { body[k] = v[k] == null ? null : Number(v[k]); });
      try {
        if (p) await api.patch(`/admin/plans/${p.id}`, body);
        else await api.post("/admin/plans", body);
      } catch (e) {
        if (e.details?.storage_quota_bytes) e.details = { ...e.details, storage_gb: e.details.storage_quota_bytes };
        throw e;
      }
      toastSuccess(t("admin.ui.saved"));
      table.reload();
    },
  });
}

async function deletePlan(p, table) {
  if (!(await confirmDialog({ message: t("admin.plans.delete_confirm", { name: p.name }), danger: true }))) return;
  try {
    await api.del(`/admin/plans/${p.id}`);
    toastSuccess(t("admin.plans.deleted"));
    table.reload();
  } catch (e) {
    toastApiError(e);
  }
}
