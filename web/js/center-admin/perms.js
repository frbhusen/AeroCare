// Permission customization: role overrides for this center + per-user grants/revokes.
import { api, h, t, mount, icon, openModal, toastSuccess, toastApiError, loadingState, errorState } from "../core/index.js";
import { hasKey } from "../core/i18n.js";

const EDITABLE = ["department_manager", "doctor", "receptionist"];
let catalogCache = null;

async function catalog(force) {
  if (!catalogCache || force) catalogCache = await api.get("/center/permissions");
  return catalogCache;
}

const permLabel = (p) => hasKey(`center-admin.perm.${p.code}`) ? t(`center-admin.perm.${p.code}`) : p.label;
const groupLabel = (g) => hasKey(`center-admin.perm_group.${g}`) ? t(`center-admin.perm_group.${g}`) : g;

/**
 * Editable list: rows of {code, state} where state ∈ "default" | "allow" | "deny".
 * base: Set of permissions granted before this layer; forbidden: Set never allowed.
 */
function permEditor(perms, { base, forbidden, overrides }) {
  const changes = {};
  const groups = {};
  perms.forEach((p) => { (groups[p.group] = groups[p.group] || []).push(p); });
  const el = h("div", { class: "adm-perm-grid" }, Object.entries(groups).map(([g, list]) => [
    h("div", { class: "adm-perm-group" }, groupLabel(g)),
    list.map((p) => {
      const blocked = forbidden.has(p.code);
      const initial = p.code in overrides ? (overrides[p.code] ? "allow" : "deny") : "default";
      const sel = h("select", { class: "select", disabled: blocked, "aria-label": permLabel(p) },
        h("option", { value: "default" }, base.has(p.code) ? t("center-admin.perms.default_on") : t("center-admin.perms.default_off")),
        h("option", { value: "allow" }, t("center-admin.perms.allow")),
        h("option", { value: "deny" }, t("center-admin.perms.deny")));
      sel.value = blocked ? "default" : initial;
      const row = h("div", { class: "adm-perm-row" },
        h("div", h("div", permLabel(p)), h("div", { class: "text-xs text-muted ltr" }, p.code),
          blocked ? h("div", { class: "text-xs text-danger" }, t("center-admin.perms.forbidden")) : null), sel);
      sel.addEventListener("change", () => {
        if (sel.value === initial) delete changes[p.code];
        else changes[p.code] = sel.value === "default" ? null : sel.value === "allow";
        row.classList.toggle("is-changed", p.code in changes);
      });
      return row;
    })]));
  return { el, changes: () => ({ ...changes }) };
}

/** Center-level tab: role defaults for this center. */
export async function rolePermissionsTab(el) {
  mount(el, loadingState());
  let cat;
  try {
    cat = await catalog(true);
  } catch (e) {
    return mount(el, errorState(e, () => rolePermissionsTab(el)));
  }
  const roleSel = h("select", { class: "select", "aria-label": t("center-admin.staff.role") },
    EDITABLE.map((r) => h("option", { value: r }, t(`admin.role.${r}`))));
  const body = h("div");
  let editor;
  const show = () => {
    const r = cat.roles[roleSel.value];
    editor = permEditor(cat.permissions, { base: new Set(r.defaults), forbidden: new Set(r.forbidden), overrides: r.overrides });
    mount(body, r.editable ? null : h("div", { class: "alert alert-warning" }, icon("lock"), h("div", t("center-admin.perms.read_only"))), editor.el);
  };
  roleSel.addEventListener("change", show);
  const save = h("button", { class: "btn btn-primary", type: "button", onClick: async (e) => {
    const changes = editor.changes();
    if (!Object.keys(changes).length) return;
    e.currentTarget.classList.add("is-loading");
    try {
      await api.put(`/center/permissions/roles/${roleSel.value}`, { changes });
      toastSuccess(t("center-admin.perms.saved_role"));
      cat = await catalog(true);
      show();
    } catch (err) {
      toastApiError(err);
    } finally {
      save.classList.remove("is-loading");
    }
  } }, icon("save"), t("admin.ui.save"));
  show();
  mount(el, h("div", { class: "card card-body stack" },
    h("p", { class: "text-muted" }, t("center-admin.perms.role_help")),
    h("div", { class: "row" }, h("label", { class: "row" }, t("center-admin.staff.role"), roleSel), h("span", { class: "spacer" }), save),
    body));
}

/** Per-user overrides (modal), opened from the staff list. */
export async function openUserPermissions(u) {
  const body = h("div", loadingState());
  let editor;
  const modal = openModal({
    title: t("center-admin.perms.user_for", { name: u.name }), size: "lg", body,
    actions: [
      { label: t("core.cancel") },
      { label: t("admin.ui.save"), variant: "primary", onClick: async () => {
        const changes = editor?.changes() || {};
        if (!Object.keys(changes).length) return true;
        try {
          await api.put(`/center/staff/${u.id}/permissions`, { changes });
        } catch (e) {
          toastApiError(e);
          return false;
        }
        toastSuccess(t("center-admin.perms.saved_user"));
        return true;
      } },
    ],
  });
  try {
    const [cat, up] = await Promise.all([catalog(), api.get(`/center/staff/${u.id}/permissions`)]);
    const overrides = Object.fromEntries(up.overrides.map((o) => [o.permission, o.allowed]));
    editor = permEditor(cat.permissions, { base: new Set(up.role_permissions), forbidden: new Set(up.forbidden), overrides });
    mount(body, h("p", { class: "text-muted" }, t("center-admin.perms.user_help", { role: t(`admin.role.${u.role}`) })),
      h("div", { class: "text-sm" }, t("center-admin.perms.effective_count", { count: up.effective.length })), editor.el);
  } catch (e) {
    mount(body, errorState(e));
    if (e.status === 403) modal.close();
  }
}
