// Superadmin: users across the platform (filter, edit identity, reset password, archive, new superadmin).
import {
  api, h, t, icon, dataTable, formatDateTime, getUser, toast, toastSuccess, confirmDialog, popover, toastApiError,
} from "../core/index.js";
import { pageHeader, userStatus, formModal, conflictToast } from "./ui.js";

const ROLES = ["superadmin", "center_manager", "department_manager", "doctor", "receptionist"];

export function usersTable({ centerId = null } = {}) {
  const role = h("select", { class: "select", "aria-label": t("admin.users.role") },
    h("option", { value: "" }, t("admin.users.all_roles")),
    ROLES.filter((r) => !centerId || r !== "superadmin").map((r) => h("option", { value: r }, t(`admin.role.${r}`))));
  const status = h("select", { class: "select", "aria-label": t("admin.users.status") },
    h("option", { value: "" }, t("admin.users.all_statuses")),
    ["active", "archived"].map((s) => h("option", { value: s }, t(`core.status.${s}`))));
  const table = dataTable({
    query: centerId ? { center_id: centerId } : {},
    search: { placeholder: t("admin.users.search") },
    toolbar: [role, status],
    columns: [
      { key: "name", label: t("admin.users.name"), render: (u) => h("div", h("strong", u.name),
        h("div", { class: "text-sm text-muted ltr" }, u.username)) },
      { key: "email", label: t("admin.users.email"), render: (u) => h("span", { class: "ltr text-sm" }, u.email) },
      { key: "role", label: t("admin.users.role"), render: (u) => t(`admin.role.${u.role}`) },
      centerId ? null : { key: "center", label: t("admin.users.center"), render: (u) => u.center_name || t("admin.users.platform") },
      { key: "status", label: t("admin.users.status"), render: (u) => userStatus(u.status) },
      { key: "last_login_at", label: t("admin.users.last_login"), render: (u) => formatDateTime(u.last_login_at) || "—" },
      { key: "actions", label: "", class: "actions", render: (u) => h("button", { class: "btn btn-sm btn-ghost", type: "button",
        "aria-label": t("admin.ui.actions"), onClick: (e) => actions(e.currentTarget, u, table) }, icon("menu")) },
    ].filter(Boolean),
    fetch: (q) => api.get("/admin/users", { query: q }),
    empty: { icon: "users", title: t("admin.users.empty") },
  });
  const apply = () => table.setQuery({ role: role.value || null, status: status.value || null });
  role.addEventListener("change", apply);
  status.addEventListener("change", apply);
  return table;
}

function actions(anchor, u, table) {
  const self = getUser()?.id === u.id;
  const item = (label, ic, fn, danger) => h("button", { class: ["menu-item", danger && "text-danger"], type: "button",
    onClick: async () => {
      pop.close();
      try {
        await fn();
      } catch (e) {
        toastApiError(e);
      }
    } }, icon(ic), label);
  const pop = popover(anchor, h("div",
    item(t("admin.users.edit"), "edit", () => editUser(u, table)),
    item(t("admin.users.reset_password"), "key", () => resetPassword(u)),
    self ? null : u.status === "active"
      ? item(t("admin.users.archive"), "lock", async () => {
        if (!(await confirmDialog({ message: t("admin.users.archive_confirm", { name: u.name }), danger: true }))) return;
        await api.post(`/admin/users/${u.id}/archive`, {});
        toastSuccess(t("admin.users.archived"));
        table.reload();
      }, true)
      : item(t("admin.users.reactivate"), "refresh", async () => {
        await api.post(`/admin/users/${u.id}/reactivate`, {});
        toastSuccess(t("admin.users.reactivated"));
        table.reload();
      })));
}

function editUser(u, table) {
  formModal({
    title: t("admin.users.edit_title", { name: u.name }),
    fields: [
      { name: "name", label: t("admin.users.name"), required: true, maxLength: 200 },
      { name: "username", label: t("admin.users.username"), required: true, help: t("admin.users.username_help") },
      { name: "email", label: t("admin.users.email"), type: "email", help: u.email_is_generated ? t("admin.users.generated_email") : null },
      { name: "reset_email", label: t("admin.users.reset_email"), type: "checkbox" },
      { name: "phone", label: t("admin.users.phone"), type: "tel" },
      { name: "specialty_title", label: t("admin.users.title_field") },
    ],
    values: u,
    submit: async (v) => {
      const body = { ...v, version: u.version };
      if (v.email === u.email) delete body.email;
      try {
        await api.patch(`/admin/users/${u.id}`, body);
      } catch (e) {
        if (e.code === "version_conflict") conflictToast(() => table.reload());
        throw e;
      }
      toastSuccess(t("admin.ui.saved"));
      table.reload();
    },
  });
}

export function resetPassword(u, url = `/admin/users/${u.id}/password`) {
  formModal({
    title: t("admin.users.reset_password_for", { name: u.name }),
    size: "sm", columns: 1,
    intro: h("p", { class: "text-muted" }, t("admin.users.reset_password_help")),
    fields: [{ name: "password", label: t("admin.users.new_password"), type: "password", required: true,
      autocomplete: "new-password", help: t("admin.users.password_help") }],
    submitLabel: t("admin.users.reset_password"),
    submit: async (v) => {
      await api.post(url, { password: v.password });
      toast(t("admin.users.password_reset_done"), { type: "success" });
    },
  });
}

export function renderUsers() {
  const table = usersTable();
  const add = h("button", { class: "btn btn-primary", type: "button", onClick: () => formModal({
    title: t("admin.users.new_superadmin"),
    fields: [
      { name: "name", label: t("admin.users.name"), required: true },
      { name: "username", label: t("admin.users.username"), required: true, help: t("admin.users.username_help") },
      { name: "password", label: t("admin.users.password"), type: "password", required: true, autocomplete: "new-password",
        help: t("admin.users.password_help") },
      { name: "email", label: t("admin.users.custom_email"), type: "email", help: t("admin.users.email_help") },
    ],
    submit: async (v) => {
      const u = await api.post("/admin/superadmins", v);
      toast(t("admin.users.created_login", { email: u.email }), { type: "success", duration: 0 });
      table.reload();
    },
  }) }, icon("plus"), t("admin.users.new_superadmin"));
  return h("div", { class: "page" }, pageHeader(t("admin.users.title"), t("admin.users.subtitle"), add), table.el);
}
