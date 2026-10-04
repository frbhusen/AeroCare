// Billing module registration
import { en, ar } from "./i18n.js";
import { renderOverview, renderInvoices, renderOutstanding } from "./home.js";
import { renderInvoice } from "./invoice.js";
import { renderEditor } from "./editor.js";
import { renderServices } from "./services.js";

export function register(registry) {
  registry.i18n({ en, ar });

  // Center area (Financial)
  const centerRoutes = [
    { path: "financial", title: "billing.financial", render: renderOverview },
    { path: "financial/invoices", title: "billing.tab.invoices", render: renderInvoices },
    { path: "financial/outstanding", title: "billing.tab.outstanding", render: renderOutstanding },
    { path: "financial/services", title: "billing.tab.services", render: renderServices },
    { path: "financial/new", title: "billing.new_invoice", render: renderEditor },
    { path: "financial/invoices/:id", title: "billing.invoice", render: renderInvoice },
    { path: "financial/invoices/:id/edit", title: "billing.invoice", render: renderEditor },
  ];
  for (const r of centerRoutes) {
    registry.route({ area: "center", path: r.path, title: r.title, perm: "billing.view", render: r.render });
  }
  registry.menu({
    area: "center",
    key: "financial",
    path: "financial",
    label: "billing.financial",
    icon: "wallet",
    perm: "billing.view",
    order: 40,
  });

  // Department area (Billing)
  const deptRoutes = [
    { path: "billing", title: "billing.title", render: renderOverview },
    { path: "billing/invoices", title: "billing.tab.invoices", render: renderInvoices },
    { path: "billing/outstanding", title: "billing.tab.outstanding", render: renderOutstanding },
    { path: "billing/services", title: "billing.tab.services", render: renderServices },
    { path: "billing/new", title: "billing.new_invoice", render: renderEditor },
    { path: "billing/invoices/:id", title: "billing.invoice", render: renderInvoice },
    { path: "billing/invoices/:id/edit", title: "billing.invoice", render: renderEditor },
  ];
  for (const r of deptRoutes) {
    registry.route({ area: "department", env: "*", path: r.path, title: r.title, perm: "billing.view", render: r.render });
  }
  registry.menu({
    area: "department",
    env: "*",
    key: "billing",
    path: "billing",
    label: "billing.menu",
    icon: "wallet",
    perm: "billing.view",
    order: 40,
  });
}
