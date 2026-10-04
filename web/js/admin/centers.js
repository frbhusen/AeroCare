// Superadmin: health centers list + create + detail (status, plan/limits, modules, users, danger zone).
import {
  api, h, t, mount, icon, dataTable, tabs, formatDate, formatDateTime, formatBytes, formatNumber, navigate, href,
  createForm, openModal, toast, toastSuccess, toastApiError, confirmDialog, loadingState, errorState, localName,
} from "../core/index.js";
import { enterSupport } from "../auth/session.js";
import { pageHeader, btn, stat, usageBar, kv, centerStatus, formModal, conflictToast } from "./ui.js";
import { usersTable } from "./users.js";

const LIMITS = ["max_departments", "max_head_doctors", "max_doctors", "max_receptionists", "max_clinics"];
const GB = 1024 ** 3;
let metaCache = null;

export async function adminMeta(force = false) {
  if (!metaCache || force) metaCache = await api.get("/admin/meta");
  return metaCache;
}

const until = (c) => (c.status === "trial" ? c.trial_ends_at : c.status === "active" ? c.subscription_ends_at : null);

// ---------------------------------------------------------------- list
export function renderCenters(ctx) {
  const status = h("select", { class: "select", "aria-label": t("admin.centers.status") },
    h("option", { value: "" }, t("admin.centers.all_statuses")),
    ["trial", "active", "expired", "suspended"].map((s) => h("option", { value: s }, t(`core.center.status.${s}`))));
  const table = dataTable({
    search: { placeholder: t("admin.centers.search") },
    toolbar: [status, h("button", { class: "btn btn-primary", type: "button", onClick: () => openCreate(table) },
      icon("plus"), t("admin.centers.new"))],
    columns: [
      { key: "name", label: t("admin.centers.name"), render: (c) => h("div", h("strong", c.name),
        h("div", { class: "text-sm text-muted ltr" }, c.slug)) },
      { key: "status", label: t("admin.centers.status"), render: (c) => centerStatus(c.status) },
      { key: "until", label: t("admin.centers.until"), render: (c) => formatDate(until(c), { year: "always" }) || "—" },
      { key: "plan", label: t("admin.centers.plan"), render: (c) => c.plan?.name || "—" },
      { key: "storage", label: t("admin.centers.storage"), render: (c) => h("span", { class: "num nowrap" },
        `${formatBytes(c.storage_used_bytes)} / ${formatBytes(c.storage_quota_bytes)}`) },
      { key: "created_at", label: t("admin.centers.created"), render: (c) => formatDate(c.created_at, { year: "always" }) },
    ],
    fetch: (q) => api.get("/admin/centers", { query: q }),
    onRowClick: (c) => navigate(`/admin/centers/${c.id}`),
    empty: { icon: "building", title: t("admin.centers.empty") },
  });
  status.addEventListener("change", () => table.setQuery({ status: status.value || null }));
  return h("div", { class: "page" }, pageHeader(t("admin.centers.title"), t("admin.centers.subtitle")), table.el);
}

async function openCreate(table) {
  let meta;
  try {
    meta = await adminMeta(true);
  } catch (e) {
    return toastApiError(e);
  }
  const types = meta.department_types.filter((x) => x.is_active);
  const boxes = types.map((tp) => h("label", { class: "check" },
    h("input", { type: "checkbox", value: tp.code }), localName(tp, tp.name_en)));
  const modulesEl = h("div", { class: "field span-2", dataset: { field: "modules" } },
    h("label", t("admin.centers.modules")), h("div", { class: "adm-checks" }, boxes));
  let modal;
  const form = createForm({
    fields: [
      { name: "name", label: t("admin.centers.name"), required: true, maxLength: 200 },
      { name: "slug", label: t("admin.centers.slug"), help: t("admin.centers.slug_help"), maxLength: 80 },
      { name: "plan_code", label: t("admin.centers.plan"), type: "select", empty: false, required: true,
        options: meta.plans.filter((p) => p.is_active).map((p) => ({ value: p.code, label: p.name })) },
      { name: "currency", label: t("admin.centers.currency"), maxLength: 10 },
      { name: "phone", label: t("admin.centers.phone"), type: "tel" },
      { name: "address", label: t("admin.centers.address") },
      { type: "section", label: t("admin.centers.first_manager") },
      { name: "m_name", label: t("admin.users.name"), maxLength: 200 },
      { name: "m_username", label: t("admin.users.username"), help: t("admin.users.username_help"), maxLength: 50 },
      { name: "m_password", label: t("admin.users.password"), type: "password", autocomplete: "new-password",
        help: t("admin.users.password_help") },
      { name: "m_email", label: t("admin.users.custom_email"), type: "email", help: t("admin.users.email_help") },
    ],
    values: { plan_code: "basic", currency: "SYP" },
    submitLabel: t("admin.centers.create"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      const body = { name: v.name, slug: v.slug, plan_code: v.plan_code, currency: v.currency || "SYP", phone: v.phone,
        address: v.address, modules: [...modulesEl.querySelectorAll("input:checked")].map((x) => x.value) };
      if (v.m_username || v.m_name || v.m_password) {
        body.manager = { name: v.m_name, username: v.m_username, password: v.m_password, email: v.m_email };
      }
      try {
        const res = await api.post("/admin/centers", body);
        modal.close();
        table.reload();
        showCreated(res);
      } catch (e) {
        // Account errors (username/password/email) belong to the manager fields.
        if (e.details && typeof e.details === "object" && body.manager) {
          e.details = Object.fromEntries(Object.entries(e.details).map(([k, m]) =>
            [["username", "password", "email"].includes(k) ? `m_${k}` : k, m]));
        }
        throw e;
      }
    },
  });
  form.el.querySelector(".form-grid").append(modulesEl);
  modal = openModal({ title: t("admin.centers.new"), size: "lg", body: [h("p", { class: "text-muted" }, t("admin.centers.trial_note")), form.el] });
}

function showCreated(c) {
  openModal({
    title: t("admin.centers.created_title"), size: "sm",
    body: [h("p", t("admin.centers.created_msg", { name: c.name })),
      c.manager ? kv([[t("admin.centers.manager_login"), h("strong", { class: "ltr" }, c.manager.email)]]) : null],
    actions: [{ label: t("admin.centers.open"), variant: "primary", onClick: () => navigate(`/admin/centers/${c.id}`) }],
  });
}

// ---------------------------------------------------------------- detail
export async function renderCenter(ctx) {
  const id = Number(ctx.params.id);
  const root = h("div", { class: "page" }, loadingState());
  let active = ctx.query?.tab || "overview";

  async function load() {
    let c;
    let meta;
    try {
      [c, meta] = await Promise.all([api.get(`/admin/centers/${id}`), adminMeta()]);
    } catch (e) {
      if (e.status === 404) throw e;
      return mount(root, errorState(e, load));
    }
    ctx.setTitle?.(c.name);
    const reload = async () => load();
    const tb = tabs([
      { key: "overview", label: t("admin.center.tab.overview"), render: (el) => overview(el, c) },
      { key: "details", label: t("admin.center.tab.details"), render: (el) => details(el, c, reload) },
      { key: "subscription", label: t("admin.center.tab.subscription"), render: (el) => subscription(el, c, reload) },
      { key: "limits", label: t("admin.center.tab.limits"), render: (el) => limits(el, c, meta, reload) },
      { key: "modules", label: t("admin.center.tab.modules"), render: (el) => modules(el, c, meta, reload) },
      { key: "users", label: t("admin.center.tab.users"), render: (el) => users(el, c) },
      { key: "danger", label: t("admin.center.tab.danger"), render: (el) => danger(el, c) },
    ], { active, onChange: (k) => { active = k; } });
    mount(root,
      h("a", { class: "btn btn-link btn-sm", href: href("/admin/centers") }, icon("arrowLeft", "flip-rtl"), t("admin.centers.back")),
      pageHeader(c.name, h("span", { class: "row" }, centerStatus(c.status), h("span", { class: "ltr text-muted" }, c.slug)),
        btn(t("admin.center.support"), () => enterSupport(c.id), { variant: "primary", iconName: "login" })),
      tb.el);
  }
  await load();
  return root;
}

function overview(el, c) {
  const u = c.usage || {};
  mount(el, h("div", { class: "stack" },
    h("div", { class: "grid-4" },
      stat(t("admin.center.status"), centerStatus(c.status), until(c) ? t("admin.center.until", { date: formatDate(until(c), { year: "always" }) }) : null),
      stat(t("admin.center.plan"), c.plan?.name || "—"),
      stat(t("admin.center.active_users"), formatNumber(Object.values(c.user_counts || {}).reduce((a, b) => a + b, 0))),
      stat(t("admin.center.modules_count"), formatNumber((c.modules || []).length))),
    h("div", { class: "card card-body stack" }, h("h2", t("admin.center.usage")),
      ...LIMITS.map((k) => h("div", h("div", { class: "text-sm" }, t(`admin.limit.${k}`)), usageBar(u[k] ?? 0, c.limits[k]))),
      h("div", h("div", { class: "text-sm" }, t("admin.limit.storage")), usageBar(c.storage_used_bytes, c.storage_quota_bytes, { bytes: true }))),
    h("div", { class: "card card-body" }, kv([
      [t("admin.center.created"), formatDateTime(c.created_at)],
      [t("admin.center.trial_ends"), formatDate(c.trial_ends_at, { year: "always" })],
      [t("admin.center.subscription_ends"), formatDate(c.subscription_ends_at, { year: "always" })],
      [t("admin.centers.currency"), c.currency],
      [t("admin.centers.phone"), c.phone ? h("span", { class: "ltr" }, c.phone) : null],
      [t("admin.centers.address"), c.address],
      ...Object.entries(c.user_counts || {}).map(([r, n]) => [t(`admin.role.${r}`), formatNumber(n)]),
    ]))));
}

function details(el, c, reload) {
  const form = createForm({
    fields: [
      { name: "name", label: t("admin.centers.name"), required: true, maxLength: 200 },
      { name: "slug", label: t("admin.centers.slug"), required: true, maxLength: 80 },
      { name: "currency", label: t("admin.centers.currency"), required: true, maxLength: 10 },
      { name: "phone", label: t("admin.centers.phone"), type: "tel" },
      { name: "address", label: t("admin.centers.address"), span: 2 },
      { name: "primary_color", label: t("admin.centers.primary_color"), type: "color" },
      { name: "secondary_color", label: t("admin.centers.secondary_color"), type: "color" },
      { name: "document_footer", label: t("admin.centers.document_footer"), type: "textarea", span: 2, maxLength: 500 },
      { name: "notes", label: t("admin.centers.notes"), type: "textarea", span: 2 },
    ],
    values: c,
    onSubmit: async (v) => {
      try {
        await api.patch(`/admin/centers/${c.id}`, { ...v, version: c.version });
      } catch (e) {
        if (e.code === "version_conflict") conflictToast(reload);
        throw e;
      }
      toastSuccess(t("admin.ui.saved"));
      reload();
    },
  });
  mount(el, h("div", { class: "card card-body" }, form.el));
}

function subscription(el, c, reload) {
  const post = async (body, confirmMsg) => {
    if (confirmMsg && !(await confirmDialog({ message: confirmMsg, danger: true }))) return;
    await api.post(`/admin/centers/${c.id}/status`, body);
    toastSuccess(t("admin.ui.saved"));
    reload();
  };
  const activate = createForm({
    columns: 1,
    fields: [{ name: "subscription_ends_at", label: t("admin.center.subscription_until"), type: "date", required: true }],
    values: { subscription_ends_at: (c.subscription_ends_at || "").slice(0, 10) },
    submitLabel: t("admin.center.activate"),
    onSubmit: (v) => post({ action: "activate", subscription_ends_at: v.subscription_ends_at }),
  });
  const extend = createForm({
    columns: 1,
    fields: [{ name: "days", label: t("admin.center.extend_days"), type: "number", min: 1, max: 3650, required: true }],
    values: { days: 14 },
    submitLabel: t("admin.center.extend_trial"),
    onSubmit: (v) => post({ action: "extend_trial", days: v.days }),
  });
  mount(el, h("div", { class: "stack" },
    h("div", { class: "card card-body" }, kv([
      [t("admin.center.status"), centerStatus(c.status)],
      [t("admin.center.trial_ends"), formatDate(c.trial_ends_at, { year: "always" })],
      [t("admin.center.subscription_ends"), formatDate(c.subscription_ends_at, { year: "always" })]])),
    h("div", { class: "grid-2" },
      h("div", { class: "card card-body stack" }, h("h2", t("admin.center.activate")), h("p", { class: "text-muted" }, t("admin.center.activate_help")), activate.el),
      h("div", { class: "card card-body stack" }, h("h2", t("admin.center.extend_trial")), h("p", { class: "text-muted" }, t("admin.center.extend_help")), extend.el)),
    h("div", { class: "card card-body stack" }, h("h2", t("admin.center.block")), h("p", { class: "text-muted" }, t("admin.center.block_help")),
      h("div", { class: "row" },
        btn(t("admin.center.expire"), () => post({ action: "expire" }, t("admin.center.expire_confirm")), { variant: "danger" }),
        btn(t("admin.center.suspend"), () => post({ action: "suspend" }, t("admin.center.suspend_confirm")), { variant: "danger" })))));
}

function limits(el, c, meta, reload) {
  const planSel = h("select", { class: "select", "aria-label": t("admin.center.plan") },
    meta.plans.map((p) => h("option", { value: String(p.id), selected: c.plan?.id === p.id }, `${p.name}${p.is_active ? "" : ` (${t("admin.plans.inactive")})`}`)));
  const applyPlan = btn(t("admin.center.apply_plan"), async () => {
    if (!(await confirmDialog({ message: t("admin.center.apply_plan_confirm") }))) return;
    await api.put(`/admin/centers/${c.id}/plan`, { plan_id: Number(planSel.value) });
    toastSuccess(t("admin.ui.saved"));
    reload();
  }, { variant: "primary" });
  const values = { storage_gb: +(c.storage_quota_bytes / GB).toFixed(2) };
  LIMITS.forEach((k) => { values[k] = c.limits[k]; });
  const form = createForm({
    fields: [...LIMITS.map((k) => ({ name: k, label: t(`admin.limit.${k}`), type: "number", min: 0,
      help: t("admin.limit.blank_unlimited"), placeholder: t("admin.limit.unlimited") })),
    { name: "storage_gb", label: t("admin.limit.storage_gb"), type: "number", min: 0.01, step: "0.01", required: true,
      help: t("admin.limit.storage_used", { used: formatBytes(c.storage_used_bytes) }) }],
    values,
    submitLabel: t("admin.center.save_limits"),
    onSubmit: async (v) => {
      const body = { storage_quota_bytes: Math.round(Number(v.storage_gb) * GB) };
      LIMITS.forEach((k) => { body[k] = v[k] == null ? null : Number(v[k]); });
      try {
        await api.put(`/admin/centers/${c.id}/limits`, body);
      } catch (e) {
        if (e.details?.storage_quota_bytes) e.details = { storage_gb: e.details.storage_quota_bytes };
        throw e;
      }
      toastSuccess(t("admin.ui.saved"));
      reload();
    },
  });
  mount(el, h("div", { class: "stack" },
    h("div", { class: "card card-body stack" }, h("h2", t("admin.center.plan")), h("p", { class: "text-muted" }, t("admin.center.plan_help")),
      h("div", { class: "row" }, planSel, applyPlan)),
    h("div", { class: "card card-body stack" }, h("h2", t("admin.center.limits")), h("p", { class: "text-muted" }, t("admin.center.limits_help")), form.el)));
}

function modules(el, c, meta, reload) {
  const active = new Set(c.modules || []);
  const boxes = meta.department_types.filter((tp) => tp.is_active || active.has(tp.code)).map((tp) =>
    h("label", { class: "check adm-module" }, h("input", { type: "checkbox", value: tp.code, checked: active.has(tp.code) }),
      h("span", localName(tp, tp.name_en), h("span", { class: "text-sm text-muted" }, ` · ${t(`admin.env.${tp.environment}`)}`),
        tp.is_custom ? h("span", { class: "badge", style: "margin-inline-start:6px" }, t("admin.types.custom")) : null)));
  const wrap = h("div", { class: "adm-checks" }, boxes);
  mount(el, h("div", { class: "card card-body stack" }, h("h2", t("admin.center.modules")),
    h("p", { class: "text-muted" }, t("admin.center.modules_help")), wrap,
    h("div", { class: "row" }, btn(t("admin.ui.save"), async () => {
      const codes = [...wrap.querySelectorAll("input:checked")].map((x) => x.value);
      const removed = [...active].filter((m) => !codes.includes(m));
      if (removed.length && !(await confirmDialog({ message: t("admin.center.modules_remove_confirm", { count: removed.length }), danger: true }))) return;
      await api.put(`/admin/centers/${c.id}/modules`, { modules: codes });
      toastSuccess(t("admin.ui.saved"));
      reload();
    }, { variant: "primary" }))));
}

function users(el, c) {
  const table = usersTable({ centerId: c.id });
  const add = h("button", { class: "btn btn-primary", type: "button", onClick: () => formModal({
    title: t("admin.center.add_manager"),
    fields: [
      { name: "name", label: t("admin.users.name"), required: true },
      { name: "username", label: t("admin.users.username"), required: true, help: t("admin.users.username_help") },
      { name: "password", label: t("admin.users.password"), type: "password", required: true, autocomplete: "new-password",
        help: t("admin.users.password_help") },
      { name: "email", label: t("admin.users.custom_email"), type: "email", help: t("admin.users.email_help") },
    ],
    submit: async (v) => {
      const u = await api.post(`/admin/centers/${c.id}/managers`, v);
      toast(t("admin.users.created_login", { email: u.email }), { type: "success", duration: 0 });
      table.reload();
    },
  }) }, icon("plus"), t("admin.center.add_manager"));
  mount(el, h("div", { class: "stack" }, h("div", { class: "row" }, add), table.el));
}

function danger(el, c) {
  const input = h("input", { class: "input ltr", type: "text", autocomplete: "off", placeholder: c.slug,
    "aria-label": t("admin.center.delete_type_slug") });
  const del = btn(t("admin.center.delete"), async () => {
    if (input.value.trim() !== c.slug) return toast(t("admin.center.delete_slug_mismatch"), { type: "error" });
    if (!(await confirmDialog({ title: t("admin.center.delete"), message: t("admin.center.delete_final", { name: c.name }),
      danger: true, confirmLabel: t("admin.center.delete") }))) return;
    await api.del(`/admin/centers/${c.id}`, { body: { confirm: input.value.trim() } });
    toastSuccess(t("admin.center.deleted", { name: c.name }));
    navigate("/admin/centers");
  }, { variant: "danger", iconName: "trash" });
  mount(el, h("div", { class: "card card-body stack adm-danger" },
    h("h2", t("admin.center.delete")),
    h("div", { class: "alert alert-danger" }, icon("alert"), h("div", t("admin.center.delete_warning"))),
    h("label", { class: "field" }, t("admin.center.delete_type_slug", { slug: c.slug }), input),
    h("div", { class: "row" }, del)));
}
