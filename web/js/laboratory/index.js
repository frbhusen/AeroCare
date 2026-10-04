// Laboratory environment UI (backend: /api/v1/lab). Public helpers for other modules: ./public.js
import { loadStylesheet } from "../core/index.js";
import { dict } from "./i18n.js";
import { renderQueue, renderSent, renderWidget } from "./lists.js";
import { renderRequestPage } from "./detail.js";
import { renderCatalog } from "./catalog.js";

const OTHER_ENVS = ["dentistry", "dermatology", "ophthalmology", "generic", "radiology", "pharmacy"];

export function register(registry) {
  loadStylesheet(new URL("./laboratory.css", import.meta.url));
  registry.i18n(dict);
  // Laboratory environment
  registry.menu({ area: "department", env: ["laboratory"], key: "lab-queue", path: "lab/queue", label: "laboratory.menu.queue",
    icon: "flask", perm: "lab.process", order: 30 });
  registry.menu({ area: "department", env: ["laboratory"], key: "lab-catalog", path: "lab/catalog", label: "laboratory.menu.catalog",
    icon: "clipboard", perm: ["lab.manage_tests", "lab.process"], order: 40 });
  registry.route({ area: "department", env: ["laboratory"], path: "lab/queue", title: "laboratory.queue.title", perm: "lab.process", render: renderQueue });
  registry.route({ area: "department", env: ["laboratory"], path: "lab/catalog", title: "laboratory.catalog.title",
    perm: ["lab.manage_tests", "lab.process"], render: renderCatalog });
  registry.widget({ area: "department", env: ["laboratory"], key: "lab-today", title: "laboratory.widget.title", perm: "lab.process",
    render: renderWidget, order: 10 });
  // Requesting side (every other environment) + request detail everywhere (API decides access).
  registry.menu({ area: "department", env: OTHER_ENVS, key: "lab-sent", path: "lab/sent", label: "laboratory.menu.sent",
    icon: "flask", perm: ["lab.request", "medical_records.view"], order: 85 });
  registry.route({ area: "department", env: "*", path: "lab/sent", title: "laboratory.sent.title",
    perm: ["lab.request", "medical_records.view"], render: renderSent });
  registry.route({ area: "department", env: "*", path: "lab/requests/:id", title: "laboratory.sent.title", render: renderRequestPage });
}
