// Visits timeline (per patient) + plain visit create / detail drawer (edit, complete/reopen, delete+undo,
// prescriptions and files of the visit). Environments with their own UI register openers/creators (hooks.js).
import { api, h, t, mount, icon, can, toast, toastApiError, createForm, openModal, openDrawer, confirmDialog,
  deleteWithUndo, dataTable, statusPill, formatDateTime, toDateTimeInput, navigate, withBusy } from "../core/index.js";
import { conflictOr } from "./util.js";
import { visitOpener, visitCreator } from "./hooks.js";
import { loadMeta } from "./meta.js";
import { prescriptionsPanel } from "./prescriptions.js";
import { ordersPanel } from "./orders.js";
import { referralsPanel } from "./referrals.js";
import { filesPanel } from "../files/panel.js";


const visitTypeLabel = (vt) => {
  const k = `patients.visit_type.${vt}`;
  const s = t(k);
  if (s && s !== k) return s;
  return String(vt || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
};

/** visitsTimeline({ctx, patient}) -> element */
export function visitsTimeline({ ctx, patient }) {
  const inDept = ctx.area === "department";
  const creator = inDept ? visitCreator(ctx.dept.environment) : null;
  const newBtn = can("medical_records.create") ? h("button", { class: "btn btn-primary", type: "button",
    onClick: () => (creator ? creator(ctx, patient, { onDone: () => table.reload() })
      : openNewVisit(ctx, patient, { onCreated: () => table.reload() })) }, icon("plus"), t("patients.visit.new")) : null;
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("patients.visit.date"), render: (v) => h("span", { class: "nowrap" }, formatDateTime(v.visit_at, { year: "always" })) },
      { key: "clinic", label: t("patients.field.clinic"), render: (v) => h("div",
        h("div", v.clinic_name), h("div", { class: "text-xs text-muted" }, v.department_name)) },
      { key: "visit_type", label: t("patients.visit.type"), render: (v) => visitTypeLabel(v.visit_type) },
      { key: "title", label: t("patients.visit.title"), render: (v) => v.title || "" },
      { key: "author_name", label: t("patients.visit.author") },
      { key: "status", label: t("patients.visit.status"), render: (v) => statusPill(v.status, "patients.visit_status") },
    ],
    fetch: (q) => api.get(`/patients/${patient.id}/visits`, { query: { ...q, department_id: inDept ? ctx.dept.id : null }, cache: true }),
    onRowClick: (v) => openVisit(ctx, v, { onChange: () => table.reload() }),
    toolbar: newBtn ? [h("div", { class: "spacer" }), newBtn] : null,
    empty: { icon: "calendar", title: t("patients.visit.none") },
  });
  return table.el;
}

/** Open a visit in its environment UI if one is registered, else in the generic drawer. */
export function openVisit(ctx, visit, { onChange } = {}) {
  const opener = visitOpener(visit.environment);
  const target = opener ? opener(ctx, visit) : null;
  if (target === false) return; // the environment opened its own view
  if (target) return navigate(target);
  return openVisitDrawer(ctx, visit, { onChange });
}

export async function openNewVisit(ctx, patient, { onCreated, clinicId } = {}) {
  let meta;
  try { meta = await loadMeta(); } catch (e) { return toastApiError(e); }
  const clinics = meta.clinics.filter((c) => (ctx.area !== "department" || c.department_id === ctx.dept.id));
  if (!clinics.length) return toast(t("patients.register.no_clinic"), { type: "warning" });
  const form = createForm({
    fields: [
      { name: "clinic_id", label: t("patients.field.clinic"), type: "select", required: true, numeric: true,
        options: clinics.map((c) => ({ value: c.id, label: ctx.area === "department" ? c.name : `${c.department_name} — ${c.name}` })) },
      { name: "visit_type", label: t("patients.visit.type"), type: "select", required: true, empty: false,
        options: meta.visit_types.map((v) => ({ value: v, label: visitTypeLabel(v) })) },
      { name: "visit_at", label: t("patients.visit.date"), type: "datetime", required: true },
      { name: "title", label: t("patients.visit.title"), maxLength: 200 },
      { name: "notes", label: t("patients.visit.notes"), type: "textarea", span: 2 },
    ],
    values: { clinic_id: clinicId || (clinics.length === 1 ? clinics[0].id : ""), visit_type: "consultation",
      visit_at: toDateTimeInput(new Date()) },
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      const res = await api.post("/visits", { ...v, patient_id: patient.id }, { offline: true, label: t("patients.visit.new") });
      modal.close();
      if (res?.queued) toast(t("patients.saved_offline"), { type: "warning" });
      else toast(t("core.saved"), { type: "success" });
      onCreated?.(res);
    },
  });
  const modal = openModal({ title: t("patients.visit.new"), body: form.el });
}

/** Generic visit drawer (any environment without its own visit screen). */
export function openVisitDrawer(ctx, visit, { onChange } = {}) {
  const body = h("div", { class: "stack" });
  const drawer = openDrawer({ title: `${visitTypeLabel(visit.visit_type)} — ${formatDateTime(visit.visit_at)}`, size: "lg", body });
  let v = visit;

  function render() {
    const editable = can("medical_records.edit");
    const info = h("dl", { class: "kv" },
      h("dt", t("patients.field.clinic")), h("dd", `${v.department_name || ""} — ${v.clinic_name || ""}`),
      h("dt", t("patients.visit.author")), h("dd", v.author_name || "—"),
      h("dt", t("patients.visit.status")), h("dd", statusPill(v.status, "patients.visit_status")));
    const form = createForm({
      fields: [
        { name: "visit_type", label: t("patients.visit.type"), type: "select", empty: false,
          options: ["consultation", "follow_up", "treatment", "procedure", "session", "examination", "other"]
            .map((x) => ({ value: x, label: visitTypeLabel(x) })), disabled: !editable },
        { name: "visit_at", label: t("patients.visit.date"), type: "datetime", required: true, disabled: !editable },
        { name: "title", label: t("patients.visit.title"), maxLength: 200, span: 2, disabled: !editable },
        { name: "notes", label: t("patients.visit.notes"), type: "textarea", span: 2, disabled: !editable },
      ],
      values: { ...v, visit_at: toDateTimeInput(v.visit_at) },
      actions: editable,
      onSubmit: async (vals) => {
        let res;
        try {
          res = await api.patch(`/visits/${v.id}`, { ...vals, version: v.version }, { offline: true, label: t("patients.visit.edit") });
        } catch (err) {
          return conflictOr(form, err, reload);
        }
        if (res?.queued) return toast(t("patients.saved_offline"), { type: "warning" });
        v = res;
        toast(t("core.saved"), { type: "success" });
        onChange?.();
        render();
      },
    });
    const statusBtn = editable ? h("button", { class: "btn", type: "button", onClick: (e) => withBusy(e.currentTarget, async () => {
      try {
        v = await api.post(`/visits/${v.id}/${v.status === "completed" ? "reopen" : "complete"}`, { version: v.version });
        onChange?.();
        render();
      } catch (err) {
        if (err.code === "version_conflict") await reload();
        toastApiError(err);
      }
    }) }, icon(v.status === "completed" ? "undo" : "check"), t(v.status === "completed" ? "patients.visit.reopen" : "patients.visit.complete")) : null;
    const delBtn = can("medical_records.delete") ? h("button", { class: "btn btn-danger", type: "button", onClick: async () => {
      if (!(await confirmDialog({ danger: true, message: t("patients.visit.delete_confirm") }))) return;
      try {
        await deleteWithUndo(`/visits/${v.id}`, { message: t("patients.visit.deleted"),
          onDone: () => { drawer.close(); onChange?.(); }, onUndone: () => onChange?.() });
      } catch { /* toast shown */ }
    } }, icon("trash"), t("core.delete")) : null;
    const patient = { id: v.patient_id, full_name: v.patient_name };
    mount(body, info, h("div", { class: "row" }, statusBtn, delBtn), form.el,
      can("medical_records.view") ? h("section", h("h3", t("patients.orders.title")),
        ordersPanel({ ctx, patient, visit: v, compact: true })) : null,
      can("medical_records.view") ? h("section", h("h3", t("patients.tab.prescriptions")),
        prescriptionsPanel({ ctx, patient, visit: v, compact: true })) : null,
      can("medical_records.view") ? h("section", h("h3", t("patients.referrals.title")),
        referralsPanel({ ctx, patient, visit: v, compact: true })) : null,
      can("files.view") ? h("section", h("h3", t("patients.tab.files")), filesPanel({ ctx, patient, visit: v, compact: true })) : null);

  }

  async function reload() {
    try { v = await api.get(`/visits/${v.id}`); render(); } catch (e) { toastApiError(e); }
  }

  render();
  return drawer;
}
