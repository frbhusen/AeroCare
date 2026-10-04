// Generic medical environment: General Medicine, Pediatrics, Cardiology, Neurology, Nutrition and
// Superadmin-defined custom departments. Backend: /api/v1/generic (+ /visits, /prescriptions, /files).
import {
  api, h, mount, t, can, icon, dataTable, formatDateTime, openModal, openDrawer, createForm, handleFormError,
  toastSuccess, toastApiError, deleteWithUndo, confirmDialog, loadingState, errorState, emptyState, statusPill,
  patientSearch,
} from "../core/index.js";
import { dict } from "./i18n.js";
import { registerVisitOpener, registerVisitCreator } from "../patients/hooks.js";
import { prescriptionsPanel } from "../patients/prescriptions.js";
import { filesPanel } from "../files/panel.js";
import { patientResultsPanel } from "../laboratory/public.js";

const ENV = ["generic"];
let metaPromise = null;
const loadMeta = () => (metaPromise ||= api.get("/generic/meta").catch((e) => { metaPromise = null; throw e; }));

export function register(registry) {
  registry.i18n(dict);
  registry.route({ area: "department", env: ENV, path: "visits", title: "generic.tab.visits",
    perm: "medical_records.view", render: renderVisitsPage });
  registry.menu({ area: "department", env: ENV, key: "generic-visits", path: "visits", label: "generic.tab.visits",
    icon: "clipboard", perm: "medical_records.view", order: 20 });

  registerVisitOpener("generic", (ctx, visit) => { openVisitDrawer(visit.id, { ctx }); return false; });
  registerVisitCreator("generic", (ctx, patient, { onDone } = {}) => openVisitEditor({ ctx, patient, onDone }));
  // The patients module's own "Visits" tab lists visits and uses the opener/creator above.
}

// ---------------------------------------------------------------- lists
function visitColumns(withPatient) {
  return [
    { key: "visit_at", label: t("generic.col.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
    withPatient ? { key: "patient", label: t("generic.col.patient"),
      render: (r) => h("span", h("strong", r.patient?.full_name || "—"), " ", h("span", { class: "muted" }, r.patient?.display_code || "")) } : null,
    { key: "title", label: t("generic.field.chief_complaint"), render: (r) => r.record?.chief_complaint || r.title || "—" },
    { key: "clinic", label: t("generic.col.clinic"), render: (r) => r.clinic_name || "" },
    { key: "author", label: t("generic.col.author"), render: (r) => r.author_name || "—" },
    { key: "status", label: t("generic.col.status"), render: (r) => statusPill(r.status, "generic.status") },
  ].filter(Boolean);
}

function renderVisitsPage(ctx) {
  ctx.setTitle(t("generic.tab.visits"));
  const clinics = (ctx.dept?.clinics || []);
  const clinicFilter = clinics.length > 1 ? h("select", { class: "select", style: "max-width:220px",
    onChange: (e) => table.setQuery({ clinic_id: e.target.value || undefined }) },
  h("option", { value: "" }, t("generic.filter.all_clinics")), clinics.map((c) => h("option", { value: c.id }, c.name))) : null;
  const newBtn = can("medical_records.create") ? h("button", { class: "btn btn-primary", type: "button",
    onClick: () => openVisitEditor({ ctx, onDone: () => table.reload() }) }, icon("plus"), t("generic.visit.new")) : null;
  const table = dataTable({
    columns: visitColumns(true),
    query: { department_id: ctx.dept?.id },
    fetch: (q) => api.get("/visits", { query: q }),
    onRowClick: (r) => openVisitDrawer(r.id, { ctx, onChanged: () => table.reload() }),
    toolbar: [clinicFilter].filter(Boolean),
    empty: { icon: "clipboard", title: t("patients.visit.none") },
  });
  return h("div", { class: "page" },
    h("div", { class: "page-header row-between" },
      h("div", h("h1", t("generic.tab.visits")), h("p", { class: "subtitle" }, ctx.dept?.name)), newBtn),
    table.el);
}

// ---------------------------------------------------------------- editor (create + edit)
function recordFields(meta, clinics, { creating }) {
  const vitals = meta.vitals.map((v) => ({
    name: `vital_${v.key}`, label: t(`generic.vitals.${v.key}`), type: "number", min: v.min, max: v.max,
    step: v.decimals ? String(10 ** -v.decimals) : "1",
  }));
  return [
    creating && clinics.length > 1 ? { name: "clinic_id", label: t("generic.field.clinic"), type: "select", required: true,
      numeric: true, empty: false, options: clinics.map((c) => ({ value: c.id, label: c.name })) } : null,
    creating ? { name: "visit_type", label: t("generic.field.visit_type"), type: "select", empty: false,
      options: meta.visit_types.map((k) => ({ value: k, label: t(`patients.visit_type.${k}`, { default: k }) })) } : null,
    { type: "section", label: t("generic.section.vitals") },
    ...vitals,
    { type: "section", label: t("generic.section.clinical") },
    ...meta.text_fields.map((k) => ({ name: k, label: t(`generic.field.${k}`), type: "textarea", rows: 2, span: 2,
      maxLength: 10000 })),
  ].filter(Boolean);
}

function splitValues(v, meta) {
  const vitals = {};
  for (const m of meta.vitals) {
    const val = v[`vital_${m.key}`];
    if (val != null && !Number.isNaN(val)) vitals[m.key] = val;
  }
  const record = { vitals };
  for (const k of meta.text_fields) record[k] = v[k] ?? null;
  return record;
}

function recordValues(rec) {
  const out = { ...(rec || {}) };
  for (const [k, val] of Object.entries(rec?.vitals || {})) out[`vital_${k}`] = val;
  return out;
}

/** Errors come back as record.vitals.<key> / record.<field>: map them onto form field names. */
function mapErrors(err) {
  if (!err?.details || typeof err.details !== "object") return err;
  const d = {};
  for (const [k, msg] of Object.entries(err.details)) {
    if (k === "record" && typeof msg === "object") {
      for (const [rk, rv] of Object.entries(msg)) {
        if (rk === "vitals" && typeof rv === "object") Object.entries(rv).forEach(([vk, vm]) => { d[`vital_${vk}`] = vm; });
        else d[rk] = rv;
      }
    } else d[k] = msg;
  }
  return Object.assign(Object.create(Object.getPrototypeOf(err)), err, { details: d });
}

async function openVisitEditor({ ctx, patient = null, visit = null, onDone } = {}) {
  const creating = !visit;
  const body = h("div", loadingState());
  const modal = openModal({ title: creating ? t("generic.visit.new") : t("generic.visit.edit"), body, size: "lg" });
  let meta;
  try {
    meta = await loadMeta();
  } catch (e) {
    mount(modal.body, errorState(e));
    return;
  }
  const deptClinicIds = new Set((ctx?.dept?.clinics || []).map((c) => c.id));
  const clinics = deptClinicIds.size ? meta.clinics.filter((c) => deptClinicIds.has(c.id)) : meta.clinics;
  let chosen = patient;
  const patientBox = h("div");
  const renderPatient = () => mount(patientBox, chosen
    ? h("div", { class: "card card-body row-between" },
      h("div", h("strong", chosen.full_name), " ", h("span", { class: "muted" }, chosen.display_code || "")),
      creating && !patient ? h("button", { class: "btn btn-sm", type: "button", onClick: () => { chosen = null; renderPatient(); } }, t("core.change", { default: "Change" })) : null)
    : patientSearch({ autofocus: true, onSelect: (p) => { chosen = p; renderPatient(); } }).el);
  renderPatient();

  const fields = recordFields(meta, clinics, { creating });
  const form = createForm({
    fields,
    values: creating ? { clinic_id: clinics[0]?.id, visit_type: "consultation" } : recordValues(visit.record),
    submitLabel: t("core.save"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      const record = splitValues(v, meta);
      try {
        if (creating) {
          if (!chosen) { toastApiError({ message: t("generic.visit.pick_patient") }); return; }
          const clinicId = v.clinic_id || clinics[0]?.id;
          await api.post("/generic/visits", {
            patient_id: chosen.id, clinic_id: clinicId, visit_type: v.visit_type || "consultation",
            title: record.chief_complaint ? record.chief_complaint.slice(0, 200) : null, record,
          }, { offline: true, label: t("generic.visit.new") });
        } else {
          if (visit.record) record.version = visit.record.version;
          await api.put(`/generic/visits/${visit.id}/record`, record);
        }
        modal.close();
        toastSuccess(t("generic.visit.saved"));
        onDone && onDone();
      } catch (err) {
        handleFormError(form, mapErrors(err));
      }
    },
  });
  mount(modal.body, h("div", { class: "stack gap-md" }, creating ? patientBox : null, form.el));
}

// ---------------------------------------------------------------- drawer
function vitalsView(vitals, bmi) {
  const pills = [];
  if (vitals.bp_systolic != null || vitals.bp_diastolic != null) {
    pills.push(h("span", { class: "pill pill--info" }, `${t("generic.vitals.bp")}: ${vitals.bp_systolic ?? "–"}/${vitals.bp_diastolic ?? "–"}`));
  }
  for (const [k, val] of Object.entries(vitals)) {
    if (k.startsWith("bp_") || val == null) continue;
    pills.push(h("span", { class: "pill pill--info" }, `${t(`generic.vitals.${k}`)}: ${val}`));
  }
  if (bmi) pills.push(h("span", { class: "pill pill--info" }, `${t("generic.vitals.bmi")}: ${bmi}`));
  return pills.length ? h("div", { class: "row gap-sm wrap" }, pills) : null;
}

function openVisitDrawer(visitId, { ctx, onChanged } = {}) {
  const body = h("div", loadingState());
  const drawer = openDrawer({ title: t("generic.visit.title"), body, size: "lg" });

  async function load() {
    let v;
    try {
      v = await api.get(`/generic/visits/${visitId}`);
    } catch (e) {
      mount(body, errorState(e, load));
      return;
    }
    const rec = v.record;
    const meta = await loadMeta().catch(() => ({ text_fields: [] }));
    const patient = { id: v.patient_id, full_name: v.patient?.full_name, display_code: v.patient?.display_code };
    const changed = () => { load(); onChanged && onChanged(); };

    const actions = h("div", { class: "row gap-sm wrap" },
      can("medical_records.edit") || (!rec && can("medical_records.create")) ? h("button", { class: "btn btn-sm", type: "button",
        onClick: () => openVisitEditor({ ctx, visit: v, onDone: changed }) }, icon("edit"), t("generic.visit.edit")) : null,
      can("medical_records.edit") ? h("button", { class: "btn btn-sm", type: "button", onClick: async () => {
        try {
          await api.post(`/visits/${v.id}/${v.status === "completed" ? "reopen" : "complete"}`, { version: v.version });
          changed();
        } catch (e) { toastApiError(e); }
      } }, v.status === "completed" ? t("generic.action.reopen") : t("generic.action.complete")) : null,
      can("medical_records.delete") ? h("button", { class: "btn btn-sm btn-danger", type: "button", onClick: async () => {
        if (!(await confirmDialog({ danger: true, message: t("patients.visit.delete_confirm") }))) return;
        await deleteWithUndo(`/visits/${v.id}`, { message: t("generic.deleted"),
          onDone: () => { drawer.close(); onChanged && onChanged(); }, onUndone: () => onChanged && onChanged() }).catch(() => {});
      } }, icon("trash"), t("core.delete")) : null);

    const clinical = rec ? meta.text_fields.filter((k) => rec[k]).map((k) =>
      h("div", h("h4", t(`generic.field.${k}`)), h("p", { class: "pre-wrap" }, rec[k]))) : [];

    mount(body, h("div", { class: "stack gap-md" },
      h("div", { class: "card card-body stack gap-sm" },
        h("div", { class: "row-between" },
          h("div", h("strong", v.patient?.full_name || ""), " ", h("span", { class: "muted" }, v.patient?.display_code || "")),
          statusPill(v.status, "generic.status")),
        h("div", { class: "muted" }, `${formatDateTime(v.visit_at)} · ${v.clinic_name || ""} · ${v.author_name || ""}`),
        rec?.last_edited_name ? h("div", { class: "muted small" }, t("generic.last_edited", { name: rec.last_edited_name })) : null,
        actions),
      h("section", { class: "card card-body stack gap-sm" }, h("h3", t("generic.section.vitals")),
        rec ? (vitalsView(rec.vitals || {}, rec.bmi) || h("p", { class: "muted" }, "—")) : h("p", { class: "muted" }, t("generic.visit.no_record"))),
      h("section", { class: "card card-body stack gap-sm" }, h("h3", t("generic.section.clinical")),
        clinical.length ? clinical : h("p", { class: "muted" }, t("generic.visit.no_record"))),
      h("section", { class: "stack gap-sm" }, h("h3", t("generic.section.prescriptions")),
        prescriptionsPanel({ ctx, patient, visit: v, compact: true })),
      can("files.view") ? h("section", { class: "stack gap-sm" }, h("h3", t("generic.section.files")),
        filesPanel({ ctx, patient, visit: v, compact: true })) : null,
      patientResultsPanel({ patientId: v.patient_id, patient, clinicId: v.clinic_id, departmentId: v.department_id }).el,
    ));
  }
  load();
}
