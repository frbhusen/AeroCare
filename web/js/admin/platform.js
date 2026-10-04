// Superadmin: storage overview, platform audit log, platform settings (login branding) and full backups.
import {
  api, h, t, mount, icon, dataTable, tabs, upload, formatBytes, formatNumber, formatDateTime, navigate, createForm,
  toastSuccess, toast, toastApiError, refresh, confirmDialog, loadingState, errorState, safeColor, openModal,
} from "../core/index.js";
import { pageHeader, btn, stat, usageBar, auditTable, kv } from "./ui.js";

const GB = 1024 ** 3;

// ---------------------------------------------------------------- storage
export async function renderStorage() {
  const res = await api.get("/admin/storage");
  const table = dataTable({
    rows: res.items,
    columns: [
      { key: "name", label: t("admin.centers.name"), render: (c) => h("strong", c.name) },
      { key: "usage", label: t("admin.storage.usage"), render: (c) => usageBar(c.used_bytes, c.quota_bytes, { bytes: true }) },
      { key: "remaining", label: t("admin.storage.remaining"), render: (c) => h("span", { class: "num nowrap" }, formatBytes(c.remaining_bytes)) },
      { key: "file_count", label: t("admin.storage.files"), render: (c) => h("span", { class: "num" }, formatNumber(c.file_count)) },
      { key: "actions", label: "", class: "actions", render: (c) => h("button", { class: "btn btn-sm", type: "button",
        onClick: () => editQuota(c) }, icon("edit"), t("admin.storage.change_quota")) },
    ],
    onRowClick: (c) => navigate(`/admin/centers/${c.id}`, { query: { tab: "limits" } }),
  });
  return h("div", { class: "page" }, pageHeader(t("admin.storage.title"), t("admin.storage.subtitle")),
    h("div", { class: "grid-3" },
      stat(t("admin.storage.total_used"), formatBytes(res.total_used_bytes)),
      stat(t("admin.storage.total_quota"), formatBytes(res.total_quota_bytes)),
      stat(t("admin.storage.centers"), formatNumber(res.items.length))),
    table.el);
}

function editQuota(c) {
  let modal;
  const form = createForm({
    columns: 1,
    fields: [{ name: "gb", label: t("admin.limit.storage_gb"), type: "number", min: 0.01, step: "0.01", required: true,
      help: t("admin.limit.storage_used", { used: formatBytes(c.used_bytes) }) }],
    values: { gb: +(c.quota_bytes / GB).toFixed(2) },
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      try {
        await api.put(`/admin/centers/${c.id}/limits`, { storage_quota_bytes: Math.round(Number(v.gb) * GB) });
      } catch (e) {
        if (e.details?.storage_quota_bytes) e.details = { gb: e.details.storage_quota_bytes };
        throw e;
      }
      modal.close();
      toastSuccess(t("admin.ui.saved"));
      refresh();
    },
  });
  modal = openModal({ title: t("admin.storage.quota_for", { name: c.name }), size: "sm", body: form.el });
}

// ---------------------------------------------------------------- audit
export async function renderAudit() {
  const center = h("select", { class: "select", "aria-label": t("admin.audit.center") },
    h("option", { value: "" }, t("admin.audit.all_centers")), h("option", { value: "platform" }, t("admin.audit.platform_only")));
  try {
    const res = await api.get("/admin/centers", { query: { per_page: 100 } });
    res.items.forEach((c) => center.append(h("option", { value: String(c.id) }, c.name)));
  } catch { /* filter stays minimal */ }
  const table = auditTable({ url: "/admin/audit", showCenter: true, extraFilters: [center] });
  center.addEventListener("change", () => table.setQuery({
    center_id: /^\d+$/.test(center.value) ? center.value : null, platform_only: center.value === "platform" ? 1 : null }));
  return h("div", { class: "page" }, pageHeader(t("admin.audit.title"), t("admin.audit.subtitle")), table.el);
}

// ---------------------------------------------------------------- settings + backups
export function renderSettings(ctx) {
  const tb = tabs([
    { key: "branding", label: t("admin.settings.branding"), render: branding },
    { key: "backups", label: t("admin.settings.backups"), render: backups },
  ], { active: ctx.query?.tab || "branding" });
  return h("div", { class: "page" }, pageHeader(t("admin.settings.title"), t("admin.settings.subtitle")), tb.el);
}

async function branding(el) {
  mount(el, loadingState());
  let b;
  try {
    b = await api.get("/admin/settings");
  } catch (e) {
    return mount(el, errorState(e, () => branding(el)));
  }
  const preview = h("div", { class: "adm-login-preview", style: { "--p": safeColor(b.primary_color), "--s": safeColor(b.secondary_color) } },
    b.logo_url ? h("img", { src: b.logo_url, alt: "" }) : h("div", { class: "adm-logo-placeholder" }, icon("hospital")),
    h("strong", b.platform_name), b.login_message ? h("p", { class: "text-sm" }, b.login_message) : null);
  const form = createForm({
    fields: [
      { name: "platform_name", label: t("admin.settings.platform_name"), required: true, maxLength: 120 },
      { name: "support_contact", label: t("admin.settings.support_contact"), maxLength: 200 },
      { name: "primary_color", label: t("admin.centers.primary_color"), type: "color" },
      { name: "secondary_color", label: t("admin.centers.secondary_color"), type: "color" },
      { name: "login_message", label: t("admin.settings.login_message"), type: "textarea", span: 2, maxLength: 300 },
    ],
    values: b,
    onSubmit: async (v) => {
      await api.put("/admin/settings", v);
      toastSuccess(t("admin.ui.saved"));
      branding(el);
    },
  });
  const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", class: "sr-only", id: "adm-logo-file" });
  file.addEventListener("change", async () => {
    if (!file.files[0]) return;
    const fd = new FormData();
    fd.append("file", file.files[0]);
    try {
      await upload("/admin/settings/logo", fd);
      toastSuccess(t("admin.settings.logo_saved"));
      branding(el);
    } catch (e) {
      toastApiError(e);
    }
  });
  mount(el, h("div", { class: "grid-2" },
    h("div", { class: "card card-body stack" }, h("h2", t("admin.settings.login_branding")), form.el),
    h("div", { class: "card card-body stack" }, h("h2", t("admin.settings.preview")), preview,
      h("p", { class: "text-sm text-muted" }, t("admin.settings.logo_help")),
      h("div", { class: "row" },
        h("label", { class: "btn", for: "adm-logo-file" }, icon("upload"), t("admin.settings.upload_logo")), file,
        b.logo_url ? btn(t("admin.settings.remove_logo"), async () => {
          if (!(await confirmDialog({ message: t("admin.settings.remove_logo_confirm"), danger: true }))) return;
          await api.del("/admin/settings/logo");
          branding(el);
        }, { variant: "ghost", iconName: "trash" }) : null))));
}

async function backups(el) {
  mount(el, loadingState());
  let res;
  try {
    res = await api.get("/admin/backups");
  } catch (e) {
    return mount(el, errorState(e, () => backups(el)));
  }
  const create = btn(t("admin.backups.create"), async () => {
    if (!(await confirmDialog({ message: t("admin.backups.create_confirm") }))) return;
    toast(t("admin.backups.running"), { type: "info" });
    const b = await api.post("/admin/backups", {});
    toastSuccess(t("admin.backups.created", { name: b.name }));
    backups(el);
  }, { variant: "primary", iconName: "database" });
  const table = dataTable({
    rows: res.items,
    columns: [
      { key: "name", label: t("admin.backups.name"), render: (b) => h("div", h("strong", { class: "ltr" }, b.name),
        h("div", { class: "text-sm text-muted" }, formatDateTime(b.created_at))) },
      { key: "complete", label: t("admin.types.status"), render: (b) => h("span", { class: `pill pill--${b.complete ? "success" : "danger"}` },
        t(b.complete ? "admin.backups.complete" : "admin.backups.incomplete")) },
      { key: "stored_files", label: t("admin.storage.files"), render: (b) => formatNumber(b.stored_files ?? 0) },
      { key: "total", label: t("admin.backups.size"), render: (b) => h("span", { class: "num" }, formatBytes(b.total_bytes)) },
      { key: "files", label: t("admin.backups.download"), render: (b) => h("div", { class: "btn-group" },
        b.files.map((f) => h("a", { class: "btn btn-sm", href: `/api/v1/admin/backups/${encodeURIComponent(b.name)}/${encodeURIComponent(f.name)}`,
          download: "" }, icon("download"), `${f.name} (${formatBytes(f.size_bytes)})`))) },
    ],
    empty: { icon: "database", title: t("admin.backups.empty") },
  });
  mount(el, h("div", { class: "stack" },
    h("div", { class: "card card-body stack" }, h("p", t("admin.backups.help")),
      kv([[t("admin.backups.contents"), t("admin.backups.contents_value")], [t("admin.backups.restore"), t("admin.backups.restore_value")]]),
      h("div", { class: "row" }, create)),
    table.el));
}
