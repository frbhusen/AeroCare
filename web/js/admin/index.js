// Superadmin portal pages: fills the core admin slots (centers, modules, plans, users, storage, audit, settings).
import { loadStylesheet } from "../core/index.js";
import { ADMIN_I18N } from "./i18n.js";
import { renderCenters, renderCenter } from "./centers.js";
import { renderTypes, renderPlans } from "./catalog.js";
import { renderUsers } from "./users.js";
import { renderStorage, renderAudit, renderSettings } from "./platform.js";

export function register(registry) {
  loadStylesheet(new URL("./admin.css", import.meta.url));
  registry.i18n(ADMIN_I18N);
  const area = "admin";
  const pages = [
    { key: "centers", path: "centers", label: "core.admin.centers", icon: "building", order: 10, render: renderCenters },
    { key: "modules", path: "modules", label: "core.admin.modules", icon: "layers", order: 20, render: renderTypes },
    { key: "plans", path: "plans", label: "core.admin.plans", icon: "tag", order: 30, render: renderPlans },
    { key: "users", path: "users", label: "core.admin.users", icon: "users", order: 40, render: renderUsers },
    { key: "storage", path: "storage", label: "core.admin.storage", icon: "database", order: 50, render: renderStorage },
    { key: "audit", path: "audit", label: "core.admin.audit", icon: "clipboard", order: 60, render: renderAudit },
    { key: "settings", path: "settings", label: "core.admin.settings", icon: "sliders", order: 70, render: renderSettings },
  ];
  for (const p of pages) {
    registry.route({ area, path: p.path, title: p.label, render: p.render });
    registry.menu({ area, key: p.key, path: p.path, label: p.label, icon: p.icon, order: p.order });
  }
  registry.route({ area, path: "centers/:id", title: "core.admin.centers", render: renderCenter });
}
