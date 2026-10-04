// Radiology module entry point
import {
  api, h, mount, t, can, icon, dataTable, tabs, formatDateTime,
} from "../core/index.js";
import { dict } from "./i18n.js";
import { radStatusPill, radPriorityPill, openRadiologyStudyDrawer, openRadiologyRequestDialog } from "./public.js";

export function register(registry) {
  registry.i18n(dict);

  // Department routes for radiology
  registry.route({
    area: "department",
    env: ["radiology"],
    path: "worklist",
    title: "radiology.worklist.title",
    perm: "radiology.process",
    render: renderRadiologyWorklist,
  });

  registry.menu({
    area: "department",
    env: ["radiology"],
    key: "radiology-worklist",
    path: "worklist",
    label: "radiology.menu.worklist",
    icon: "layers",
    perm: "radiology.process",
    order: 10,
  });

  registry.route({
    area: "department",
    env: "*",
    path: "radiology/requests",
    title: "radiology.sent.title",
    perm: "radiology.request",
    render: renderSentRequests,
  });

  registry.menu({
    area: "department",
    env: "*",
    key: "radiology-requests",
    path: "radiology/requests",
    label: "radiology.menu.sent",
    icon: "image",
    perm: "radiology.request",
    order: 35,
  });
}

function renderRadiologyWorklist(ctx) {
  ctx.setTitle(t("radiology.worklist.title"));
  const table = dataTable({
    columns: [
      { key: "requested_at", label: t("radiology.col.requested"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.requested_at)) },
      { key: "patient", label: t("radiology.col.patient"), render: (r) => h("strong", r.patient?.full_name || r.patient?.name || `Patient #${r.patient_id}`) },
      { key: "exam", label: t("radiology.col.exam"), render: (r) => `${t(`radiology.exam.${r.exam_type}`, r.exam_type)} ${r.body_region ? `(${r.body_region})` : ""}` },
      { key: "status", label: t("radiology.col.status"), render: (r) => h("span", { class: "row gap-xs" }, radStatusPill(r.status), radPriorityPill(r.priority)) },
      { key: "from", label: t("radiology.col.from"), render: (r) => r.requesting_clinic?.name || "" },
    ],
    fetch: (q) => api.get("/radiology/worklist", { query: q }),
    onRowClick: (r) => openRadiologyStudyDrawer(r.id, { onChanged: () => table.reload() }),
    empty: { icon: "image", title: t("radiology.detail.no_images") },
  });

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("radiology.worklist.title")),
      h("p", { class: "subtitle" }, ctx.dept?.name)
    ),
    table.el
  );
}

function renderSentRequests(ctx) {
  ctx.setTitle(t("radiology.sent.title"));
  const table = dataTable({
    columns: [
      { key: "requested_at", label: t("radiology.col.requested"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.requested_at)) },
      { key: "patient", label: t("radiology.col.patient"), render: (r) => h("strong", r.patient?.full_name || r.patient?.name || `Patient #${r.patient_id}`) },
      { key: "exam", label: t("radiology.col.exam"), render: (r) => `${t(`radiology.exam.${r.exam_type}`, r.exam_type)} ${r.body_region ? `(${r.body_region})` : ""}` },
      { key: "status", label: t("radiology.col.status"), render: (r) => h("span", { class: "row gap-xs" }, radStatusPill(r.status), radPriorityPill(r.priority)) },
    ],
    fetch: (q) => api.get("/radiology/studies", { query: { ...q, clinic_id: ctx.query.clinic_id || undefined } }),
    onRowClick: (r) => openRadiologyStudyDrawer(r.id, { onChanged: () => table.reload() }),
    toolbar: can("radiology.request") ? [
      h("button", {
        class: "btn btn-primary",
        type: "button",
        onClick: () => openRadiologyRequestDialog({
          departmentId: ctx.dept?.id,
          onCreated: () => table.reload(),
        }),
      }, icon("plus"), t("radiology.action.new_request"))
    ] : null,
    empty: { icon: "image", title: t("radiology.detail.no_images") },
  });

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("radiology.sent.title")),
      h("p", { class: "subtitle" }, ctx.dept?.name)
    ),
    table.el
  );
}
