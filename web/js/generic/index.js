// Generic clinical environment module entry point
import {
  api, h, mount, t, can, icon, dataTable, tabs, formatDateTime,
  openModal, openDrawer, createForm, toastSuccess, toastApiError, emptyState, loadingState, errorState,
} from "../core/index.js";
import { dict } from "./i18n.js";
import { registerPatientTab, registerVisitOpener, registerVisitCreator } from "../patients/hooks.js";

export function register(registry) {
  registry.i18n(dict);

  // Department visits route & menu for generic clinical environments (General Medicine, Pediatrics, Cardiology, etc.)
  registry.route({
    area: "department",
    env: ["generic"],
    path: "visits",
    title: "generic.tab.visits",
    perm: "medical_records.view",
    render: renderDepartmentGenericVisits,
  });

  registry.menu({
    area: "department",
    env: ["generic"],
    key: "generic-visits",
    path: "visits",
    label: "generic.tab.visits",
    icon: "clipboard",
    perm: "medical_records.view",
    order: 20,
  });

  // Visit opener & creator for generic clinical environments
  registerVisitOpener("generic", (ctx, visit) => {
    openGenericVisitDrawer(visit.id);
    return null; // drawer handled directly
  });

  registerVisitCreator("generic", (ctx, patient, { onDone } = {}) => {
    openGenericVisitModal({ ctx, patient, onDone });
  });

  // Patient profile tab
  registerPatientTab({
    key: "generic",
    label: "generic.tab.visits",
    env: ["generic"],
    order: 28,
    perm: "medical_records.view",
    render: (panelEl, { patient }) => {
      mount(panelEl, renderPatientGenericVisitsTable(patient.id));
    },
  });
}

function renderDepartmentGenericVisits(ctx) {
  ctx.setTitle(t("generic.tab.visits"));
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("patients.visit.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
      { key: "patient", label: t("patients.field.full_name"), render: (r) => h("strong", r.patient?.full_name || r.patient?.name || `Patient #${r.patient_id}`) },
      { key: "title", label: t("patients.visit.title"), render: (r) => r.title || "—" },
      { key: "clinic", label: t("patients.field.clinic"), render: (r) => r.clinic_name || "" },
      { key: "author", label: t("patients.visit.author"), render: (r) => r.author_name || "—" },
    ],
    fetch: (q) => api.get("/patients/visits", { query: { ...q, department_id: ctx.dept?.id } }),
    onRowClick: (r) => openGenericVisitDrawer(r.id),
    empty: { icon: "clipboard", title: t("patients.visit.none") },
  });

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("generic.tab.visits")),
      h("p", { class: "subtitle" }, ctx.dept?.name)
    ),
    table.el
  );
}

function renderPatientGenericVisitsTable(patientId) {
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("patients.visit.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
      { key: "chief_complaint", label: t("generic.field.chief_complaint"), render: (r) => r.record?.chief_complaint || r.title || "—" },
      { key: "diagnosis", label: t("generic.field.diagnosis"), render: (r) => r.record?.diagnosis || "—" },
      { key: "author", label: t("patients.visit.author"), render: (r) => r.author_name || "—" },
    ],
    fetch: (q) => api.get(`/generic/patients/${patientId}/visits`, { query: q }),
    onRowClick: (r) => openGenericVisitDrawer(r.id),
    empty: { icon: "clipboard", title: t("patients.visit.none") },
  });
  return table.el;
}

function openGenericVisitDrawer(visitId) {
  const body = h("div", loadingState());
  const drawer = openDrawer({ title: t("generic.visit.title", { id: visitId }), body, size: "lg" });

  api.get(`/generic/visits/${visitId}`).then((v) => {
    const rec = v.record || {};
    const vitals = rec.vitals || {};

    const vitalsList = Object.entries(vitals).filter(([, val]) => val != null).map(([k, val]) =>
      h("div", { class: "pill pill--info" }, `${t(`generic.vitals.${k}`, k)}: ${val}`)
    );

    mount(body,
      h("div", { class: "stack gap-md" },
        h("div", { class: "card card-body" },
          h("h3", t("patients.visit.date")),
          h("p", formatDateTime(v.visit_at)),
          h("h3", { class: "mt-sm" }, t("patients.visit.author")),
          h("p", v.author_name || "—")
        ),
        vitalsList.length ? h("div", { class: "card card-body" },
          h("h3", t("generic.vitals.title")),
          h("div", { class: "row gap-sm wrap mt-sm" }, vitalsList)
        ) : null,
        h("div", { class: "card card-body" },
          rec.chief_complaint ? [h("h3", t("generic.field.chief_complaint")), h("p", rec.chief_complaint)] : null,
          rec.hpi ? [h("h3", { class: "mt-sm" }, t("generic.field.hpi")), h("p", rec.hpi)] : null,
          rec.examination ? [h("h3", { class: "mt-sm" }, t("generic.field.examination")), h("p", rec.examination)] : null,
          rec.diagnosis ? [h("h3", { class: "mt-sm" }, t("generic.field.diagnosis")), h("p", rec.diagnosis)] : null,
          rec.treatment_plan ? [h("h3", { class: "mt-sm" }, t("generic.field.treatment_plan")), h("p", rec.treatment_plan)] : null,
          rec.notes ? [h("h3", { class: "mt-sm" }, t("generic.field.notes")), h("p", rec.notes)] : null
        )
      )
    );
  }).catch((e) => {
    mount(body, errorState(e));
  });
}

async function openGenericVisitModal({ ctx, patient, onDone }) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("generic.visit.new"), body, size: "lg" });
  let meta;
  try {
    meta = await api.get("/generic/meta");
  } catch (e) {
    mount(modal.body, errorState(e));
    return;
  }

  const clinics = ctx.dept?.clinics || meta.clinics || [];
  const form = createForm({
    fields: [
      clinics.length > 1 ? {
        name: "clinic_id", label: t("patients.field.clinic"), type: "select", required: true,
        numeric: true, options: clinics.map((c) => ({ value: c.id, label: c.name }))
      } : null,
      { name: "title", label: t("patients.visit.title"), maxLength: 200 },
      { name: "chief_complaint", label: t("generic.field.chief_complaint"), type: "textarea", rows: 2 },
      { name: "hpi", label: t("generic.field.hpi"), type: "textarea", rows: 2 },
      { name: "examination", label: t("generic.field.examination"), type: "textarea", rows: 2 },
      { name: "diagnosis", label: t("generic.field.diagnosis"), type: "textarea", rows: 2 },
      { name: "treatment_plan", label: t("generic.field.treatment_plan"), type: "textarea", rows: 2 },
    ].filter(Boolean),
    values: { clinic_id: clinics[0]?.id },
    submitLabel: t("core.save"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      try {
        const payload = {
          patient_id: patient.id,
          clinic_id: v.clinic_id,
          title: v.title || null,
          chief_complaint: v.chief_complaint || null,
          hpi: v.hpi || null,
          examination: v.examination || null,
          diagnosis: v.diagnosis || null,
          treatment_plan: v.treatment_plan || null,
        };
        await api.post("/generic/visits", payload, {
          offline: true,
          label: t("generic.visit.new"),
        });
        modal.close();
        toastSuccess(t("core.saved"));
        if (onDone) onDone();
      } catch (err) {
        toastApiError(err);
      }
    },
  });

  mount(modal.body, form.el);
}
