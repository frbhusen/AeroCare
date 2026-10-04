// Dermatology module entry point
import {
  api, h, mount, t, can, icon, dataTable, tabs, formatDateTime, formatDate, getLang,
  openModal, createForm, toastSuccess, toastApiError, emptyState, loadingState, errorState, loadStylesheet,
} from "../core/index.js";
import { dict } from "./i18n.js";
import { registerPatientTab, registerVisitOpener, registerVisitCreator } from "../patients/hooks.js";
import { renderBody2D, getRegionLabel } from "./body2d.js";
import { patientSearch } from "../components/patient-search.js";

export function register(registry) {
  loadStylesheet(new URL("./dermatology.css", import.meta.url));
  registry.i18n(dict);

  // Department routes
  registry.route({
    area: "department",
    env: ["dermatology"],
    path: "visits",
    title: "dermatology.tab.visits",
    perm: "medical_records.view",
    render: renderVisitsList,
  });

  registry.menu({
    area: "department",
    env: ["dermatology"],
    key: "derm-visits",
    path: "visits",
    label: "dermatology.tab.visits",
    icon: "clipboard",
    perm: "medical_records.view",
    order: 20,
  });

  registry.route({
    area: "department",
    env: ["dermatology"],
    path: "laser",
    title: "dermatology.tab.laser",
    perm: "medical_records.view",
    render: renderLaserSessionsList,
  });

  registry.menu({
    area: "department",
    env: ["dermatology"],
    key: "derm-laser",
    path: "laser",
    label: "dermatology.tab.laser",
    icon: "zap",
    perm: "medical_records.view",
    order: 30,
  });

  // Patient profile tab
  registerPatientTab({
    key: "dermatology",
    label: "dermatology.title",
    env: ["dermatology"],
    order: 26,
    perm: "medical_records.view",
    render: (panelEl, { patient, ctx }) => {
      const tb = tabs([
        {
          key: "visits",
          label: t("dermatology.tab.visits"),
          render: (el) => mount(el, renderPatientVisitsTable(patient.id)),
        },
        {
          key: "laser",
          label: t("dermatology.tab.laser"),
          render: (el) => mount(el, renderPatientLaserTable(patient.id)),
        },
      ]);
      mount(panelEl, tb.el);
    },
  });

  // Visit opener & creator
  registerVisitOpener("dermatology", (ctx, visit) => {
    return `#/d/${ctx.dept?.id || visit.department_id}/visits?visit_id=${visit.id}`;
  });

  registerVisitCreator("dermatology", (ctx, patient, { onDone } = {}) => {
    openDermVisitModal({ ctx, patient, onDone });
  });
}

function renderVisitsList(ctx) {
  ctx.setTitle(t("dermatology.tab.visits"));
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("patients.visit.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
      { key: "patient", label: t("patients.field.full_name"), render: (r) => h("strong", r.patient?.full_name || r.patient?.name || `Patient #${r.patient_id}`) },
      { key: "condition", label: t("dermatology.visit.condition"), render: (r) => r.condition || r.diagnosis || "—" },
      { key: "severity", label: t("dermatology.visit.severity"), render: (r) => r.severity ? h("span", { class: `pill pill--${r.severity === "severe" ? "danger" : "info"}` }, t(`dermatology.visit.severity.${r.severity}`, r.severity)) : "—" },
      { key: "clinic", label: t("patients.field.clinic"), render: (r) => r.clinic_name || "" },
    ],
    fetch: (q) => api.get("/dermatology/visits", { query: { ...q, department_id: ctx.dept?.id } }),
    empty: { icon: "clipboard", title: t("dermatology.visit.empty") },
  });

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("dermatology.tab.visits")),
      h("p", { class: "subtitle" }, ctx.dept?.name)
    ),
    table.el
  );
}

function renderLaserSessionsList(ctx) {
  ctx.setTitle(t("dermatology.tab.laser"));
  const table = dataTable({
    columns: [
      { key: "session_date", label: t("dermatology.laser.session_date"), render: (r) => h("span", { class: "nowrap" }, formatDate(r.session_date)) },
      { key: "session_number", label: t("dermatology.laser.session_number"), render: (r) => h("span", { class: "badge" }, `#${r.session_number}`) },
      { key: "patient", label: t("patients.field.full_name"), render: (r) => h("strong", r.patient?.full_name || r.patient?.name || `Patient #${r.patient_id}`) },
      { key: "areas", label: t("dermatology.laser.areas"), render: (r) => (r.areas || []).map((a) => getRegionLabel(a.region || a)).join(getLang() === "ar" ? "، " : ", ") || "—" },
      { key: "next_session_at", label: t("dermatology.laser.next_session"), render: (r) => r.next_session_at ? formatDate(r.next_session_at) : "—" },
    ],
    fetch: (q) => api.get("/dermatology/laser/sessions", { query: { ...q, department_id: ctx.dept?.id } }),
    empty: { icon: "zap", title: t("dermatology.laser.empty") },
  });

  const addBtn = can("medical_records.create") ? h("button", {
    class: "btn btn-primary",
    type: "button",
    onClick: () => openLaserSessionModal({ ctx, onDone: () => table.reload() }),
  }, icon("plus"), " ", t("dermatology.laser.new_session")) : null;

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("div",
        h("h1", t("dermatology.tab.laser")),
        h("p", { class: "subtitle" }, ctx.dept?.name)
      ),
      addBtn
    ),
    table.el
  );
}

function renderPatientVisitsTable(patientId) {
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("patients.visit.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
      { key: "condition", label: t("dermatology.visit.condition"), render: (r) => r.condition || r.diagnosis || "—" },
      { key: "severity", label: t("dermatology.visit.severity"), render: (r) => r.severity ? h("span", { class: `pill pill--${r.severity === "severe" ? "danger" : "info"}` }, t(`dermatology.visit.severity.${r.severity}`, r.severity)) : "—" },
      { key: "treatment", label: t("dermatology.visit.treatment"), render: (r) => r.treatment || "—" },
    ],
    fetch: (q) => api.get(`/dermatology/patients/${patientId}/visits`, { query: q }),
    empty: { icon: "clipboard", title: t("dermatology.visit.empty") },
  });
  return table.el;
}

function renderPatientLaserTable(patientId) {
  const wrap = h("div", { class: "stack gap-md" });
  const table = dataTable({
    columns: [
      { key: "session_date", label: t("dermatology.laser.session_date"), render: (r) => h("span", { class: "nowrap" }, formatDate(r.session_date)) },
      { key: "session_number", label: t("dermatology.laser.session_number"), render: (r) => h("span", { class: "badge" }, `#${r.session_number}`) },
      { key: "areas", label: t("dermatology.laser.areas"), render: (r) => (r.areas || []).map((a) => getRegionLabel(a.region || a)).join(getLang() === "ar" ? "، " : ", ") || "—" },
      { key: "next_session_at", label: t("dermatology.laser.next_session"), render: (r) => r.next_session_at ? formatDate(r.next_session_at) : "—" },
    ],
    fetch: (q) => api.get(`/dermatology/laser/patients/${patientId}/sessions`, { query: q }),
    empty: { icon: "zap", title: t("dermatology.laser.empty") },
  });

  const addBtn = can("medical_records.create") ? h("div", { class: "row-end" },
    h("button", {
      class: "btn btn-sm btn-primary",
      type: "button",
      onClick: () => openLaserSessionModal({ patient: { id: patientId }, onDone: () => table.reload() }),
    }, icon("plus"), " ", t("dermatology.laser.new_session"))
  ) : null;

  mount(wrap, addBtn, table.el);
  return wrap;
}

export async function openLaserSessionModal({ ctx, patient = null, onDone } = {}) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("dermatology.laser.new_session"), body, size: "xl" });

  let meta;
  try {
    meta = await api.get("/dermatology/laser/meta");
  } catch (e) {
    mount(modal.body, errorState(e));
    return;
  }

  const clinics = ctx?.dept?.clinics || meta.clinics || [];
  let selectedPatient = patient;
  const selectedAreas = new Set();
  const mapEl = renderBody2D({
    selected: selectedAreas,
  });

  const BACK_ONLY = new Set(["upper_back", "lower_back", "buttocks"]);

  const formFields = [
    !selectedPatient ? {
      name: "patient_search",
      label: t("patients.title"),
      type: "custom",
      render: () => {
        const container = h("div", { class: "pat-search-wrap" });
        function update() {
          container.innerHTML = "";
          if (selectedPatient) {
            const name = selectedPatient.full_name || `${selectedPatient.first_name || ""} ${selectedPatient.last_name || ""}`.trim();
            const card = h("div", { class: "selected-patient-card" },
              h("div", { class: "selected-patient-info" },
                h("strong", name),
                h("span", { class: "text-muted text-xs ltr" }, selectedPatient.display_code || selectedPatient.code || "")
              ),
              h("button", {
                class: "btn btn-ghost btn-sm",
                type: "button",
                onClick: () => { selectedPatient = null; update(); }
              }, "×")
            );
            container.append(card);
          } else {
            const ps = patientSearch({
              onSelect: (p) => {
                selectedPatient = p;
                update();
              },
            });
            container.append(ps.el);
          }
        }
        update();
        return container;
      },
    } : null,
    clinics.length > 1 ? {
      name: "clinic_id",
      label: t("patients.field.clinic"),
      type: "select",
      required: true,
      numeric: true,
      options: clinics.map((c) => ({ value: c.id, label: c.name })),
    } : null,
    {
      name: "session_date",
      label: t("dermatology.laser.session_date"),
      type: "date",
      required: true,
    },
    {
      name: "next_session_at",
      label: t("dermatology.laser.next_session"),
      type: "date",
    },
    {
      name: "notes",
      label: t("dermatology.laser.notes"),
      type: "textarea",
      rows: 2,
    },
  ].filter(Boolean);

  const form = createForm({
    fields: formFields,
    values: {
      clinic_id: clinics[0]?.id,
      session_date: new Date().toISOString().slice(0, 10),
    },
    submitLabel: t("dermatology.laser.new_session"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      if (!selectedPatient?.id) {
        toastApiError(new Error(t("core.patient_search.placeholder", { default: "Please select a patient first." })));
        return;
      }
      if (selectedAreas.size === 0) {
        toastApiError(new Error(t("dermatology.bodymap.selected", { count: 0 })));
        return;
      }
      try {
        const payload = {
          patient_id: selectedPatient.id,
          clinic_id: v.clinic_id || clinics[0]?.id,
          session_date: v.session_date,
          next_session_at: v.next_session_at || null,
          notes: v.notes || null,
          areas: [...selectedAreas].map((reg) => ({
            region: reg,
            side: BACK_ONLY.has(reg) ? "back" : "front"
          })),
        };
        await api.post("/dermatology/laser/sessions", payload, {
          offline: true,
          label: t("dermatology.laser.new_session"),
        });
        modal.close();
        toastSuccess(t("core.saved"));
        if (onDone) onDone();
      } catch (err) {
        toastApiError(err);
      }
    },
  });

  mount(modal.body,
    h("div", { class: "derm-session-layout" },
      mapEl,
      form.el
    )
  );
}

async function openDermVisitModal({ ctx, patient, onDone }) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("dermatology.visit.new"), body, size: "xl" });
  let meta;
  try {
    meta = await api.get("/dermatology/meta");
  } catch (e) {
    mount(modal.body, errorState(e));
    return;
  }

  const clinics = ctx.dept?.clinics || meta.clinics || [];
  const selectedAreas = new Set();
  const mapEl = renderBody2D({
    selected: selectedAreas,
  });

  const form = createForm({
    fields: [
      clinics.length > 1 ? {
        name: "clinic_id", label: t("patients.field.clinic"), type: "select", required: true,
        numeric: true, options: clinics.map((c) => ({ value: c.id, label: c.name }))
      } : null,
      { name: "condition", label: t("dermatology.visit.condition"), required: true, maxLength: 200 },
      {
        name: "severity", label: t("dermatology.visit.severity"), type: "select",
        options: ["mild", "moderate", "severe"].map((s) => ({ value: s, label: t(`dermatology.visit.severity.${s}`, s) }))
      },
      { name: "symptoms", label: t("dermatology.visit.symptoms"), type: "textarea", rows: 2 },
      { name: "examination_findings", label: t("dermatology.visit.findings"), type: "textarea", rows: 2 },
      { name: "diagnosis", label: t("dermatology.visit.diagnosis"), type: "textarea", rows: 2 },
      { name: "treatment", label: t("dermatology.visit.treatment"), type: "textarea", rows: 2 },
      { name: "notes", label: t("dermatology.visit.notes"), type: "textarea", rows: 2 },
    ].filter(Boolean),
    values: { clinic_id: clinics[0]?.id, severity: "moderate" },
    submitLabel: t("patients.visit.new"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      try {
        const payload = {
          ...v,
          patient_id: patient.id,
          affected_areas: [...selectedAreas],
        };
        await api.post("/dermatology/visits", payload, {
          offline: true,
          label: t("dermatology.visit.new"),
        });
        modal.close();
        toastSuccess(t("core.saved"));
        if (onDone) onDone();
      } catch (err) {
        toastApiError(err);
      }
    },
  });

  mount(modal.body,
    h("div", { class: "derm-session-layout" },
      mapEl,
      form.el
    )
  );
}
