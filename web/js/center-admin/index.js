// Center administration module registration
import { h, t, tabs, can, mount } from "../core/index.js";
import { dict } from "./i18n.js";
import { renderStaff } from "./staff.js";
import { departmentsTab, clinicsTab } from "./org.js";
import { rolePermissionsTab } from "./perms.js";

export function register(registry) {
  registry.i18n(dict);

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
  const tabList = [
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
