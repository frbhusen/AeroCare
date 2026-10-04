// Staff management (center area: whole center; department area: that department only).
import {
  api, h, t, icon, mount, dataTable, formatDateTime, createForm, openModal, popover, toast, toastSuccess, toastApiError,
  confirmDialog, can, loadingState, errorState,
} from "../core/index.js";
import { pageHeader, userStatus, formModal, conflictToast } from "../admin/ui.js";
import { resetPassword } from "../admin/users.js";
import { openUserPermissions } from "./perms.js";

const ROLES = ["department_manager", "doctor", "receptionist"];

/** ctx.dept set => department-scoped page. */
export async function renderStaff(ctx) {
  const deptId = ctx.dept?.id || null;
  const root = h("div", { class: "page" }, loadingState());
  let meta;
  try {
    meta = await api.get("/center/staff/meta");
  } catch (e) {
    if (e.status === 403 || e.status === 404) throw e;
    mount(root, errorState(e, () => ctx.navigate?.(ctx.path)));
    return root;
  }
  if (deptId) {
    meta = { ...meta, departments: meta.departments.filter((d) => d.id === deptId),
      clinics: meta.clinics.filter((c) => c.department_id === deptId),
      scope_types: meta.scope_types.filter((s) => s !== "center") };
  }
  const role = h("select", { class: "select", "aria-label": t("center-admin.staff.role") },
    h("option", { value: "" }, t("center-admin.staff.all_roles")),
    ["center_manager", ...ROLES].map((r) => h("option", { value: r }, t(`admin.role.${r}`))));
  const status = h("select", { class: "select", "aria-label": t("center-admin.staff.status") },
    h("option", { value: "active" }, t("core.status.active")), h("option", { value: "archived" }, t("core.status.archived")),
    h("option", { value: "" }, t("center-admin.staff.all_statuses")));
  const dept = deptId ? null : h("select", { class: "select", "aria-label": t("center-admin.staff.department") },
    h("option", { value: "" }, t("center-admin.staff.all_departments")),
    meta.departments.map((d) => h("option", { value: String(d.id) }, d.name)));

  const table = dataTable({
    query: { status: "active", department_id: deptId },
    perPage: 50,
    search: { placeholder: t("center-admin.staff.search") },
    toolbar: [role, status, dept],
    columns: [
      { key: "name", label: t("center-admin.staff.name"), render: (u) => h("div",
        h("strong", u.name), u.is_head ? h("span", { class: "badge", style: "margin-inline-start:6px" }, t("center-admin.staff.head")) : null,
        h("div", { class: "text-sm text-muted ltr" }, u.username)) },
      { key: "role", label: t("center-admin.staff.role"), render: (u) => h("div", t(`admin.role.${u.role}`),
        u.specialty_title ? h("div", { class: "text-sm text-muted" }, u.specialty_title) : null) },
      { key: "assignment", label: t("center-admin.staff.assignment"), render: assignment },
      { key: "email", label: t("center-admin.staff.email"), render: (u) => h("span", { class: "ltr text-sm" }, u.email) },
      { key: "status", label: t("center-admin.staff.status"), render: (u) => userStatus(u.status) },
      { key: "last_login_at", label: t("center-admin.staff.last_login"), render: (u) => formatDateTime(u.last_login_at) || "—" },
      { key: "actions", label: "", class: "actions", render: (u) => (u.can_manage || (meta.can_reset_passwords && u.role !== "center_manager"))
        ? h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": t("admin.ui.actions"),
          onClick: (e) => actions(e.currentTarget, u, meta, table) }, icon("menu")) : null },
    ],
    fetch: (q) => api.get("/center/staff", { query: q, cache: true }),
    empty: { icon: "staff", title: t("center-admin.staff.empty") },
  });
  const apply = () => table.setQuery({ role: role.value || null, status: status.value || null,
    department_id: deptId || (dept && dept.value) || null });
  [role, status, dept].filter(Boolean).forEach((s) => s.addEventListener("change", apply));

  const add = meta.roles.length ? h("button", { class: "btn btn-primary", type: "button",
    onClick: () => chooseRole(meta, table) }, icon("plus"), t("center-admin.staff.new")) : null;
  mount(root, pageHeader(t("center-admin.staff.title"),
    deptId ? t("center-admin.staff.subtitle_dept", { name: ctx.dept.name }) : t("center-admin.staff.subtitle"), add), table.el);
  return root;
}

function assignment(u) {
  if (u.role === "doctor") return h("div", u.clinic_name || "—", h("div", { class: "text-sm text-muted" }, u.department_name || ""));
  if (u.role === "department_manager") return h("div", u.department_name || "—", u.clinic_name ? h("div", { class: "text-sm text-muted" }, u.clinic_name) : null);
  if (u.role === "receptionist") {
    return h("div", { class: "text-sm" }, (u.scopes || []).map((s) => h("div",
      s.type === "center" ? t("center-admin.scope.center") : s.type === "department"
        ? t("center-admin.scope.department_named", { name: s.name || s.id }) : t("center-admin.scope.clinic_named", { name: s.name || s.id }))));
  }
  return t("center-admin.scope.center");
}

// ---------------------------------------------------------------- create
function chooseRole(meta, table) {
  const modal = openModal({
    title: t("center-admin.staff.new"), size: "md",
    body: h("div", { class: "tile-grid" }, meta.roles.map((r) => h("button", { class: "tile", type: "button",
      onClick: () => { modal.close(); createStaff(r, meta, table); } },
    icon({ doctor: "stethoscope", department_manager: "shield", receptionist: "user" }[r]),
    h("span", h("strong", t(`admin.role.${r}`)), h("div", { class: "text-sm text-muted" }, t(`center-admin.staff.role_help.${r}`)))))),
  });
}

const clinicOptions = (meta, deptId) => meta.clinics.filter((c) => !deptId || c.department_id === Number(deptId))
  .map((c) => ({ value: c.id, label: `${c.name} — ${meta.departments.find((d) => d.id === c.department_id)?.name || ""}${c.is_active ? "" : ` (${t("admin.ui.inactive")})`}` }));

function createStaff(roleName, meta, table) {
  const fields = [
    { name: "name", label: t("center-admin.staff.name"), required: true, maxLength: 200 },
    { name: "username", label: t("admin.users.username"), required: true, maxLength: 50, help: t("admin.users.username_help"), autocomplete: "off" },
    { name: "password", label: t("admin.users.password"), type: "password", required: true, autocomplete: "new-password", help: t("admin.users.password_help") },
    { name: "email", label: t("admin.users.custom_email"), type: "email", help: t("admin.users.email_help") },
    { name: "phone", label: t("admin.users.phone"), type: "tel" },
  ];
  if (roleName === "doctor") {
    fields.push({ name: "clinic_id", label: t("center-admin.staff.clinic"), type: "select", required: true, numeric: true,
      options: clinicOptions(meta) }, { name: "specialty_title", label: t("admin.users.title_field") });
  } else if (roleName === "department_manager") {
    fields.push({ name: "department_id", label: t("center-admin.staff.department"), type: "select", required: true, numeric: true,
      options: meta.departments.map((d) => ({ value: d.id, label: d.has_head ? `${d.name} (${t("center-admin.staff.has_head")})` : d.name })) },
    { name: "clinic_id", label: t("center-admin.staff.working_clinic"), type: "select", numeric: true, options: clinicOptions(meta),
      help: t("center-admin.staff.working_clinic_help") },
    { name: "specialty_title", label: t("admin.users.title_field") });
  }
  const scopes = roleName === "receptionist" ? scopeEditor(meta, []) : null;
  let modal;
  const form = createForm({
    fields,
    submitLabel: t("center-admin.staff.create"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      const body = { role: roleName, ...v };
      if (scopes) body.scopes = scopes.value();
      const u = await api.post("/center/staff", body);
      modal.close();
      table.reload();
      toast(t("center-admin.staff.created", { name: u.name, email: u.email }), { type: "success", duration: 0 });
    },
  });
  if (scopes) form.el.querySelector(".form-grid").append(h("div", { class: "field span-2", dataset: { field: "scopes" } },
    h("label", t("center-admin.staff.scopes")), scopes.el));
  modal = openModal({ title: t("center-admin.staff.new_role", { role: t(`admin.role.${roleName}`) }), size: "lg", body: form.el });
}

/** Receptionist scope picker: whole center / departments / single clinics. */
export function scopeEditor(meta, current) {
  const has = (type, id) => current.some((s) => s.type === type && (type === "center" || s.id === id));
  const center = meta.scope_types.includes("center")
    ? h("input", { type: "checkbox", checked: has("center") }) : null;
  const deptBoxes = new Map();
  const clinicBoxes = new Map();
  const groups = meta.departments.map((d) => {
    const db = h("input", { type: "checkbox", checked: has("department", d.id) });
    deptBoxes.set(d.id, db);
    const clinics = meta.clinics.filter((c) => c.department_id === d.id).map((c) => {
      const cb = h("input", { type: "checkbox", checked: has("clinic", c.id) });
      clinicBoxes.set(c.id, cb);
      return h("label", { class: "check", style: "margin-inline-start:24px" }, cb, c.name);
    });
    const sync = () => clinics.forEach((l) => { const i = l.querySelector("input"); i.disabled = db.checked; });
    db.addEventListener("change", sync);
    sync();
    return h("div", { class: "adm-scope-list" }, h("label", { class: "check" }, db, h("strong", t("center-admin.scope.department_named", { name: d.name }))), clinics);
  });
  const body = h("div", { class: "adm-scope-list" }, groups);
  const syncCenter = () => { if (center) body.style.display = center.checked ? "none" : ""; };
  center?.addEventListener("change", syncCenter);
  syncCenter();
  const el = h("div", { class: "card card-body adm-scope-list" },
    center ? h("label", { class: "check" }, center, h("strong", t("center-admin.scope.center"))) : null,
    center ? h("p", { class: "text-sm text-muted" }, t("center-admin.scope.help")) : null, body);
  return {
    el,
    value() {
      if (center?.checked) return [{ type: "center" }];
      const out = [];
      for (const [id, b] of deptBoxes) if (b.checked) out.push({ type: "department", id });
      for (const [id, b] of clinicBoxes) if (b.checked && !b.disabled) out.push({ type: "clinic", id });
      return out;
    },
  };
}

// ---------------------------------------------------------------- row actions
function actions(anchor, u, meta, table) {
  const item = (label, ic, fn, danger) => h("button", { class: ["menu-item", danger && "text-danger"], type: "button",
    onClick: async () => {
      pop.close();
      try {
        await fn();
      } catch (e) {
        toastApiError(e);
      }
    } }, icon(ic), label);
  const m = u.can_manage;
  const pop = popover(anchor, h("div",
    m && can("staff.edit") ? item(t("center-admin.staff.edit"), "edit", () => editStaff(u, table)) : null,
    m && u.role === "doctor" && can("staff.edit") ? item(t("center-admin.staff.reassign"), "arrowRight", () => reassign(u, meta, table)) : null,
    m && u.role === "receptionist" && can("staff.edit") ? item(t("center-admin.staff.edit_scopes"), "layers", () => editScopes(u, meta, table)) : null,
    m && can("permissions.manage") ? item(t("center-admin.perms.user_title"), "shield", () => openUserPermissions(u)) : null,
    meta.can_reset_passwords && u.role !== "center_manager" ? item(t("admin.users.reset_password"), "key",
      () => resetPassword(u, `/center/staff/${u.id}/password`)) : null,
    m && u.status === "active" && can("staff.delete") ? item(t("admin.users.archive"), "lock", async () => {
      if (!(await confirmDialog({ message: t("center-admin.staff.archive_confirm", { name: u.name }), danger: true }))) return;
      await api.post(`/center/staff/${u.id}/archive`, {});
      toastSuccess(t("admin.users.archived"));
      table.reload();
    }, true) : null,
    m && u.status === "archived" && can("staff.edit") ? item(t("admin.users.reactivate"), "refresh", async () => {
      await api.post(`/center/staff/${u.id}/reactivate`, {});
      toastSuccess(t("admin.users.reactivated"));
      table.reload();
    }) : null,
    m && can("staff.delete") ? item(t("center-admin.staff.delete"), "trash", async () => {
      if (!(await confirmDialog({ message: t("center-admin.staff.delete_confirm", { name: u.name }), danger: true }))) return;
      const res = await api.del(`/center/staff/${u.id}`);
      toast(res.deleted ? t("center-admin.staff.deleted") : t("center-admin.staff.archived_instead"),
        { type: res.deleted ? "success" : "warning", duration: res.deleted ? 4000 : 8000 });
      table.reload();
    }, true) : null));
}

function editStaff(u, table) {
  formModal({
    title: t("center-admin.staff.edit_title", { name: u.name }),
    fields: [
      { name: "name", label: t("center-admin.staff.name"), required: true, maxLength: 200 },
      { name: "username", label: t("admin.users.username"), required: true, help: t("admin.users.username_help") },
      { name: "email", label: t("admin.users.email"), type: "email", help: u.email_is_generated ? t("admin.users.generated_email") : t("admin.users.custom_email_note") },
      { name: "reset_email", label: t("admin.users.reset_email"), type: "checkbox" },
      { name: "phone", label: t("admin.users.phone"), type: "tel" },
      { name: "specialty_title", label: t("admin.users.title_field") },
    ],
    values: u,
    submit: async (v) => {
      const body = { ...v, version: u.version };
      if (v.email === u.email) delete body.email;
      try {
        await api.patch(`/center/staff/${u.id}`, body);
      } catch (e) {
        if (e.code === "version_conflict") conflictToast(() => table.reload());
        throw e;
      }
      toastSuccess(t("admin.ui.saved"));
      table.reload();
    },
  });
}

function reassign(u, meta, table) {
  formModal({
    title: t("center-admin.staff.reassign_title", { name: u.name }),
    columns: 1, size: "sm",
    intro: h("div", { class: "alert alert-warning" }, icon("info"), h("div", t("center-admin.staff.reassign_help"))),
    fields: [{ name: "clinic_id", label: t("center-admin.staff.new_clinic"), type: "select", required: true, numeric: true,
      options: clinicOptions(meta).filter((o) => o.value !== u.clinic_id) }],
    submitLabel: t("center-admin.staff.reassign"),
    submit: async (v) => {
      await api.post(`/center/staff/${u.id}/reassign`, { clinic_id: v.clinic_id });
      toastSuccess(t("center-admin.staff.reassigned"));
      table.reload();
    },
  });
}

function editScopes(u, meta, table) {
  const editor = scopeEditor(meta, u.scopes || []);
  openModal({
    title: t("center-admin.staff.scopes_title", { name: u.name }), size: "md",
    body: [h("p", { class: "text-muted" }, t("center-admin.staff.scopes_help")), editor.el],
    actions: [
      { label: t("core.cancel") },
      { label: t("admin.ui.save"), variant: "primary", onClick: async () => {
        try {
          await api.put(`/center/staff/${u.id}/scopes`, { scopes: editor.value() });
        } catch (e) {
          toastApiError(e);
          return false;
        }
        toastSuccess(t("admin.ui.saved"));
        table.reload();
        return true;
      } },
    ],
  });
}
