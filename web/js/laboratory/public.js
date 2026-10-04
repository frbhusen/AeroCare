// Public, reusable laboratory UI for other environments (patient pages in dentistry, dermatology, generic,
// ophthalmology, ...). Import from "../laboratory/public.js":
//
//   openLabRequestDialog({patient?, patientId?, clinicId?, departmentId?, onCreated?})  -> modal
//   labResultsPanel({patientId, patient?, clinicId?, departmentId?, allowRequest = true}) -> {el, reload}
//   patientResultsPanel({patientId, patient?, clinicId?, departmentId?})               -> {el, reload}  (Lab + Radiology tabs)
//
// Everything is scoped by the API: finalized lab results show for any staff who can see the patient;
// radiology final reports only for the requesting clinic, radiology, managers and explicit shares.
import {
  api, h, mount, t, can, icon, openModal, openDrawer, createForm, dataTable, patientSearch, patientName, toast,
  toastSuccess, loadingState, errorState, emptyState, tabs, formatDateTime,
} from "../core/index.js";
import { labStatus, priorityPill } from "./common.js";
import { labRequestView } from "./detail.js";
import { radiologyResultsPanel } from "../radiology/public.js";

export async function openLabRequestDialog({ patient, patientId, clinicId, departmentId, onCreated } = {}) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("laboratory.action.new_request"), body, size: "lg" });
  let meta;
  let catalog;
  try {
    [meta, catalog] = await Promise.all([api.get("/lab/meta"), api.get("/lab/tests", { query: { active: true } })]);
  } catch (e) {
    mount(modal.body, errorState(e));
    return modal;
  }
  if (!meta.laboratories.length) return mount(modal.body, emptyState({ icon: "flask", title: t("laboratory.msg.no_lab") })), modal;
  const tests = catalog.items || [];
  if (!tests.length) return mount(modal.body, emptyState({ icon: "flask", title: t("laboratory.msg.no_tests") })), modal;

  let selectedPatient = patient || (patientId ? { id: Number(patientId) } : null);
  const clinics = meta.requesting_clinics;
  const defClinic = clinicId || clinics.find((c) => departmentId && c.department_id === Number(departmentId))?.id || clinics[0]?.id;
  const labs = meta.laboratories.flatMap((d) => (d.clinics.length > 1
    ? d.clinics.map((c) => ({ value: `${d.id}:${c.id}`, label: `${d.name} · ${c.name}` }))
    : [{ value: `${d.id}:`, label: d.name }]));

  const fields = [
    clinics.length > 1 ? { name: "requesting_clinic_id", label: t("laboratory.form.requesting_clinic"), type: "select", required: true, empty: false,
      numeric: true, options: clinics.map((c) => ({ value: c.id, label: c.name })) } : null,
    labs.length > 1 ? { name: "lab", label: t("laboratory.form.laboratory"), type: "select", required: true, empty: false, options: labs } : null,
    { name: "priority", label: t("laboratory.form.priority"), type: "select", empty: false, required: true,
      options: ["routine", "urgent"].map((p) => ({ value: p, label: t(`laboratory.priority.${p}`) })) },
    { name: "clinical_notes", label: t("laboratory.form.clinical_notes"), type: "textarea", span: 2, rows: 2, maxLength: 4000 },
  ].filter(Boolean);

  // Test picker grouped by category, with a quick filter.
  const chosen = new Set();
  const countEl = h("span", { class: "badge" }, t("laboratory.form.selected", { n: 0 }));
  const filter = h("input", { class: "input", type: "search", placeholder: t("laboratory.form.filter_tests") });
  const groups = {};
  for (const tst of tests) (groups[tst.category_name || t("laboratory.catalog.no_category")] ||= []).push(tst);
  const boxes = [];
  const list = h("div", { class: "lab-picker" }, Object.entries(groups).map(([cat, items]) => h("fieldset", { class: "lab-picker-group" },
    h("legend", cat),
    items.map((tst) => {
      const cb = h("input", { type: "checkbox", value: tst.id });
      cb.addEventListener("change", () => {
        (cb.checked ? chosen.add(tst.id) : chosen.delete(tst.id));
        countEl.textContent = t("laboratory.form.selected", { n: chosen.size });
      });
      const lbl = h("label", { class: "check lab-picker-item", dataset: { q: `${tst.code} ${tst.name}`.toLowerCase() } }, cb,
        h("span", tst.name), h("span", { class: "text-xs text-muted ltr" }, tst.code));
      boxes.push(lbl);
      return lbl;
    }))));
  filter.addEventListener("input", () => {
    const q = filter.value.trim().toLowerCase();
    boxes.forEach((b) => { b.hidden = !!q && !b.dataset.q.includes(q); });
    list.querySelectorAll("fieldset").forEach((fs) => { fs.hidden = ![...fs.querySelectorAll("label")].some((l) => !l.hidden); });
  });
  const testsBlock = h("div", { class: "field span-2", dataset: { field: "test_ids" } },
    h("div", { class: "row-between" }, h("label", t("laboratory.form.tests"), h("span", { class: "req" }, "*")), countEl), filter, list);

  const patientBlock = h("div", { class: "field span-2", dataset: { field: "patient_id" } }, h("label", t("laboratory.form.patient")),
    selectedPatient?.full_name || selectedPatient?.name ? h("div", h("strong", patientName(selectedPatient)), " ",
      selectedPatient.code ? h("span", { class: "ltr text-muted" }, selectedPatient.code) : null)
      : selectedPatient ? h("div", `#${selectedPatient.id}`)
        : patientSearch({ onSelect: (p) => { selectedPatient = p; }, autofocus: true }).el);

  const form = createForm({
    fields, values: { requesting_clinic_id: defClinic, priority: "routine", lab: labs[0]?.value },
    submitLabel: t("laboratory.action.new_request"), onCancel: () => modal.close(),
    onSubmit: async (v, f) => {
      if (!selectedPatient) return f.setErrors({ patient_id: t("laboratory.form.choose_patient") });
      if (!chosen.size) return f.setErrors({ test_ids: t("laboratory.form.tests_required") });
      const [labDept, labClinic] = String(v.lab || labs[0].value).split(":");
      const body2 = {
        patient_id: selectedPatient.id, requesting_clinic_id: v.requesting_clinic_id || defClinic, priority: v.priority,
        clinical_notes: v.clinical_notes, test_ids: [...chosen], lab_department_id: Number(labDept),
        lab_clinic_id: labClinic ? Number(labClinic) : null,
      };
      const res = await api.post("/lab/requests", body2, { offline: true, label: t("laboratory.action.new_request") });
      modal.close();
      if (res?.queued) toast(t("laboratory.msg.saved_offline"), { type: "warning" });
      else toastSuccess(t("laboratory.msg.created"));
      if (onCreated) onCreated(res);
    },
  });
  const grid = form.el.firstElementChild;
  grid.prepend(patientBlock);
  grid.append(testsBlock);
  mount(modal.body, form.el);
  return modal;
}

/** Open one lab request in a drawer (read-only or workflow, per API access). */
export function openLabRequestDrawer(id, { onChanged } = {}) {
  const view = labRequestView(id, { onChanged, onDeleted: () => { drawer.close(); if (onChanged) onChanged(); } });
  const drawer = openDrawer({ title: t("laboratory.detail.title", { id }), body: view.el, size: "lg" });
  return drawer;
}

export function labResultsPanel({ patientId, patient, clinicId, departmentId, allowRequest = true } = {}) {
  const table = dataTable({
    columns: [
      { key: "requested_at", label: t("laboratory.col.requested"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.requested_at)) },
      { key: "tests", label: t("laboratory.col.tests"), render: (r) => (r.tests || []).join(", ") },
      { key: "status", label: t("laboratory.col.status"), render: (r) => h("span", { class: "row" }, labStatus(r.status), priorityPill(r.priority),
        r.abnormal_count ? h("span", { class: "pill pill--danger" }, t("laboratory.detail.abnormal_count", { n: r.abnormal_count })) : null) },
      { key: "from", label: t("laboratory.col.from"), render: (r) => r.requesting_clinic?.name || "" },
    ],
    perPage: 10,
    fetch: (q) => api.get(`/lab/patients/${patientId}/requests`, { query: q, cache: true }),
    onRowClick: (r) => openLabRequestDrawer(r.id, { onChanged: () => table.reload() }),
    toolbar: allowRequest && can("lab.request") ? [h("button", { class: "btn btn-sm btn-primary", type: "button",
      onClick: () => openLabRequestDialog({ patient, patientId, clinicId, departmentId, onCreated: () => table.reload() }) },
    icon("plus"), t("laboratory.action.new_request"))] : null,
    empty: { icon: "flask", title: t("laboratory.empty.results") },
  });
  return { el: table.el, reload: table.reload };
}

export function patientResultsPanel(opts = {}) {
  let current = null;
  const tb = tabs([
    { key: "lab", label: t("laboratory.panel.lab"), render: (p) => { current = labResultsPanel(opts); mount(p, current.el); } },
    { key: "rad", label: t("radiology.panel.radiology"), render: (p) => { current = radiologyResultsPanel(opts); mount(p, current.el); } },
  ]);
  const el = h("section", { class: "card lab-results-panel" },
    h("div", { class: "card-header" }, h("h2", icon("flask"), " ", t("laboratory.panel.title"))),
    h("div", { class: "card-body" }, tb.el));
  return { el, reload: () => current && current.reload() };
}
