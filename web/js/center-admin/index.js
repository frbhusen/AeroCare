// Center administration module registration
import { h, t, tabs, can, mount, managesDepartment, unavailableState } from "../core/index.js";
import { dict } from "./i18n.js";
import { renderStaff } from "./staff.js";
import { departmentsTab, clinicsTab } from "./org.js";
import { rolePermissionsTab } from "./perms.js";
import { centerDict, centerTab, auditTab, backupTab } from "./center.js";

export function register(registry) {
  registry.i18n(dict);
  registry.i18n(centerDict);

  // Staff route & menu
  registry.route({
    area: "center",
    path: "staff",
    title: "center-admin.staff.title",
    perm: "staff.view",
    render: renderStaff,
  });

  registry.menu({
    area: "center",
    key: "staff",
    path: "staff",
    label: "center-admin.staff.title",
    icon: "users",
    perm: "staff.view",
    order: 50,
  });

  // Department staff route
  registry.route({
    area: "department",
    env: "*",
    path: "staff",
    title: "center-admin.staff.title",
    perm: "staff.view",
    render: renderStaff,
  });

  registry.menu({ area: "department", env: "*", key: "dept-staff", path: "staff", label: "center-admin.staff.title",
    icon: "users", perm: "staff.edit", order: 90 });

  // Department settings (head doctor / managers of this department): department, its clinics, its audit log.
  registry.route({ area: "department", env: "*", path: "dept-settings", title: "center-admin.dept_settings.title",
    perm: "settings.edit", render: renderDepartmentSettings });
  registry.menu({ area: "department", env: "*", key: "dept-settings", path: "dept-settings",
    label: "center-admin.dept_settings.title", icon: "settings", perm: "settings.edit", order: 95 });

  // Settings & Organization routes & menu (Center level)
  registry.route({
    area: "center",
    path: "settings",
    title: "center-admin.org.title",
    perm: "settings.view",
    render: renderOrganization,
  });

  registry.route({
    area: "center",
    path: "organization",
    title: "center-admin.org.title",
    perm: "settings.view",
    render: renderOrganization,
  });

  registry.menu({
    area: "center",
    key: "settings",
    path: "settings",
    label: "core.nav.settings",
    icon: "settings",
    perm: "settings.view",
    order: 70,
  });
}

function renderOrganization(ctx) {
  ctx.setTitle(t("center-admin.org.title"));
  const centerLevel = ctx.area === "center";
  const tabList = [
    centerLevel ? { key: "center", label: t("center-admin.center.tab"), render: (el) => centerTab(el) } : null,
    {
      key: "departments",
      label: t("center-admin.org.tab.departments"),
      render: (el) => departmentsTab(el),
    },
    {
      key: "clinics",
      label: t("center-admin.org.tab.clinics"),
      render: (el) => clinicsTab(el),
    },
    can("permissions.manage") ? {
      key: "permissions",
      label: t("center-admin.org.tab.permissions"),
      render: (el) => rolePermissionsTab(el),
    } : null,
    can("audit.view") ? { key: "audit", label: t("center-admin.audit.tab"), render: (el) => auditTab(el) } : null,
    centerLevel && can("backup.create") ? { key: "backup", label: t("center-admin.backup.tab"), render: (el) => backupTab(el) } : null,
  ].filter(Boolean);

  const tb = tabs(tabList);
  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("center-admin.org.title")),
      h("p", { class: "subtitle" }, t("center-admin.dept.help"))
    ),
    tb.el
  );
}

function renderDepartmentSettings(ctx) {
  ctx.setTitle(t("center-admin.dept_settings.title"));
  if (!managesDepartment(ctx.dept?.id)) return unavailableState();
  const tb = tabs([
    { key: "department", label: t("center-admin.org.tab.departments"), render: (el) => departmentsTab(el, { centerLevel: false }) },
    { key: "clinics", label: t("center-admin.org.tab.clinics"), render: (el) => clinicsTab(el, { deptId: ctx.dept.id }) },
    can("audit.view") ? { key: "audit", label: t("center-admin.audit.tab"), render: (el) => auditTab(el) } : null,
  ].filter(Boolean));
  return h("div", { class: "page" },
    h("div", { class: "page-header" }, h("h1", t("center-admin.dept_settings.title")), h("p", { class: "subtitle" }, ctx.dept?.name)),
    tb.el);
}
