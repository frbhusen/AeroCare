// Reports module UI: center portal slot "reports" + a Reports page inside every department environment.
// Everything is driven by GET /reports (catalog); the API enforces permissions and scope.
import { loadStylesheet } from "../core/index.js";
import { dict } from "./i18n.js";
import { renderReports } from "./page.js";

export function register(registry) {
  registry.i18n(dict);
  loadStylesheet(new URL("./reports.css", import.meta.url));
  registry.route({ area: "center", path: "reports", title: "reports.title", perm: "reports.view", render: renderReports });
  registry.menu({ area: "center", key: "reports", path: "reports", label: "core.nav.reports", icon: "chart",
    perm: "reports.view", order: 60 });
  registry.route({ area: "department", env: "*", path: "reports", title: "reports.title", perm: "reports.view",
    render: renderReports });
  registry.menu({ area: "department", env: "*", key: "reports", path: "reports", label: "reports.menu", icon: "chart",
    perm: "reports.view", order: 90 });
}
