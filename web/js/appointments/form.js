// Create / edit (incl. recurring) and walk-in dialogs.
import {
  api, h, t, mount, field, readValues, setFieldErrors, clearFieldErrors, openModal, toast, toastSuccess,
  toastApiError, patientSearch, patientName, getUser, areaHref, icon, todayISO,
} from "../core/index.js";
import { areaClinics, loadDoctors, addMinutes, minutesBetween, conflictBlock, typeLabel, isoWeekday } from "./common.js";

const DETAIL_MAP = { starts_at: "start", ends_at: "end", duration_minutes: "end", rule: "freq" };

function mapDetails(details) {
  const out = {};
  for (const [k, v] of Object.entries(details || {})) out[DETAIL_MAP[k] || k] = v;
  return out;
}

/** Patient picker: chip with the selected patient + search box. */
function patientPicker({ initial, onChange, allowCreate, ctx, getClinicId }) {
  let selected = initial || null;
  const wrap = h("div", { class: "field span-2", dataset: { field: "patient_id" } });
  function render() {
    if (selected) {
      mount(wrap, h("label", t("appointments.field.patient"), h("span", { class: "req", "aria-hidden": "true" }, "*")),
        h("div", { class: "appt-patient-chip" }, icon("user"),
          h("span", { class: "appt-patient-name" }, patientName(selected)),
          selected.display_code || selected.code ? h("span", { class: "text-muted ltr" }, selected.display_code || selected.code) : null,
          h("button", { class: "btn btn-link btn-sm", type: "button", onClick: () => { selected = null; onChange(null); render(); } },
            t("appointments.patient.change"))));
      return;
    }
    const search = patientSearch({ autofocus: true, onSelect: (p) => { selected = p; onChange(p); render(); } });
    const nodes = [h("label", t("appointments.field.patient"), h("span", { class: "req", "aria-hidden": "true" }, "*")), search.el];
    if (allowCreate) nodes.push(newPatientMini({ ctx, getClinicId, onCreated: (p) => { selected = p; onChange(p); render(); } }));
    mount(wrap, ...nodes);
  }
  render();
  return { el: wrap, get: () => selected };
}

/** Minimal patient registration (full registration lives in the patients module UI). */
function newPatientMini({ ctx, getClinicId, onCreated }) {
  const box = h("div", { class: "appt-newpatient", hidden: true });
  const name = h("input", { class: "input", maxlength: 200, placeholder: t("appointments.patient.full_name"), "aria-label": t("appointments.patient.full_name") });
  const phone = h("input", { class: "input ltr", type: "tel", maxlength: 40, placeholder: t("appointments.patient.phone"), "aria-label": t("appointments.patient.phone") });
  const err = h("div", { class: "field-error", hidden: true });
  const createBtn = h("button", { class: "btn btn-primary btn-sm", type: "button", onClick: async () => {
    err.hidden = true;
    const clinicId = getClinicId();
    if (!clinicId) { err.textContent = t("appointments.patient.need_clinic"); err.hidden = false; return; }
    if (name.value.trim().length < 2) { name.focus(); return; }
    createBtn.disabled = true;
    try {
      const p = await api.post("/patients", { full_name: name.value.trim(), phone: phone.value.trim() || null, clinic_id: Number(clinicId) });
      onCreated(p);
    } catch (e) {
      err.textContent = e.details ? Object.values(e.details).join(" · ") : e.message;
      err.hidden = false;
    } finally { createBtn.disabled = false; }
  } }, icon("plus"), t("appointments.patient.create"));
  box.append(h("div", { class: "row appt-newpatient-row" }, name, phone, createBtn), err,
    h("a", { class: "btn btn-link btn-sm", href: areaHref(ctx, "patients") }, t("appointments.patient.open_patients")));
  const toggle = h("button", { class: "btn btn-link btn-sm", type: "button", onClick: () => { box.hidden = !box.hidden; if (!box.hidden) name.focus(); } },
    icon("plus"), t("appointments.patient.new"));
  return h("div", toggle, box);
}

/** Clinic + doctor pickers (or the fixed "You — clinic" line for doctors). */
function placePickers({ meta, ctx, clinicId, doctorId, onClinic, withNoDoctor = true }) {
  if (meta.is_doctor) {
    const c = (meta.clinics || []).find((x) => x.id === meta.own_clinic_id);
    return { nodes: [h("div", { class: "field span-2" }, h("label", t("appointments.field.doctor")),
      h("div", { class: "appt-fixed" }, t("appointments.you_doctor", { name: getUser()?.name || "", clinic: c?.name || "" })))],
    clinic: () => meta.own_clinic_id, doctor: () => null, clinicObj: () => c };
  }
  const clinics = areaClinics(meta, ctx);
  if (!clinicId && clinics.length === 1) clinicId = clinics[0].id;
  const clinicField = field({ name: "clinic_id", label: t("appointments.field.clinic"), type: "select", required: true,
    options: clinics.map((c) => ({ value: c.id, label: ctx?.area === "department" ? c.name : `${c.name} · ${c.department_name}` })) }, clinicId);
  const doctorField = field({ name: "doctor_id", label: t("appointments.field.doctor"), type: "select",
    placeholder: withNoDoctor ? t("appointments.field.no_doctor") : undefined, options: [] }, doctorId);
  const clinicSel = clinicField.querySelector("select");
  const doctorSel = doctorField.querySelector("select");
  async function fillDoctors(keep) {
    const cid = clinicSel.value;
    const current = keep ?? doctorSel.value;
    mount(doctorSel, h("option", { value: "" }, t("appointments.field.no_doctor")));
    if (current) { doctorSel.append(h("option", { value: String(current) }, "…")); doctorSel.value = String(current); }
    if (!cid) return;
    try {
      const docs = await loadDoctors(cid);
      if (clinicSel.value !== cid) return;
      mount(doctorSel, h("option", { value: "" }, t("appointments.field.no_doctor")),
        docs.map((d) => h("option", { value: String(d.id) }, d.name)));
      if (docs.length === 1 && !keep && current === "") doctorSel.value = String(docs[0].id);
      else doctorSel.value = docs.some((d) => String(d.id) === String(current)) ? String(current) : "";
    } catch (e) { toastApiError(e); }
  }
  clinicSel.addEventListener("change", () => { fillDoctors(""); onClinic?.(clinicObj()); });
  const clinicObj = () => clinics.find((c) => String(c.id) === clinicSel.value);
  fillDoctors(doctorId ? String(doctorId) : "");
  return { nodes: [clinicField, doctorField], clinic: () => (clinicSel.value ? Number(clinicSel.value) : null),
    doctor: () => (doctorSel.value ? Number(doctorSel.value) : null), clinicObj };
}

function typeOptions(meta, current) {
  const types = [...(meta.appointment_types || [])];
  if (current && !types.includes(current)) types.push(current);
  return types.map((x) => ({ value: x, label: typeLabel(x) }));
}

function recurrenceSection(dateInput, enabled) {
  const toggle = h("input", { type: "checkbox", checked: enabled });
  const freq = field({ name: "freq", label: t("appointments.rec.freq"), type: "select", empty: false,
    options: ["weekly", "daily", "monthly"].map((v) => ({ value: v, label: t(`appointments.rec.${v}`) })) }, "weekly");
  const interval = field({ name: "interval", label: t("appointments.rec.interval"), type: "number", min: 1, max: 52 }, 1);
  const wdBoxes = [6, 7, 1, 2, 3, 4, 5].map((d) => h("label", { class: "check appt-wd" },
    h("input", { type: "checkbox", value: String(d) }), t(`appointments.wd.${d}`)));
  const weekdays = h("div", { class: "field span-2", dataset: { field: "weekdays" } }, h("label", t("appointments.rec.weekdays")),
    h("div", { class: "row appt-wd-row" }, wdBoxes));
  const endMode = field({ name: "end_mode", label: t("appointments.rec.end"), type: "select", empty: false,
    options: [{ value: "count", label: t("appointments.rec.end_count") }, { value: "until", label: t("appointments.rec.end_until") }] }, "count");
  const count = field({ name: "count", label: t("appointments.rec.count"), type: "number", min: 1, max: 200 }, 4);
  const until = field({ name: "until", label: t("appointments.rec.until"), type: "date" });
  const body = h("div", { class: "form-grid appt-rec-body" }, freq, interval, weekdays, endMode, count, until,
    h("div", { class: "field-help span-2" }, t("appointments.rec.max", { n: 200 })));
  const sync = () => {
    body.hidden = !toggle.checked;
    weekdays.hidden = freq.querySelector("select").value !== "weekly";
    const m = endMode.querySelector("select").value;
    count.hidden = m !== "count";
    until.hidden = m !== "until";
  };
  const presetWeekday = () => {
    if (!dateInput.value || wdBoxes.some((b) => b.firstChild.checked)) return;
    const wd = isoWeekday(dateInput.value);
    wdBoxes.forEach((b) => { b.firstChild.checked = Number(b.firstChild.value) === wd; });
  };
  [toggle, freq, endMode].forEach((x) => x.addEventListener("change", () => { presetWeekday(); sync(); }));
  dateInput.addEventListener("change", presetWeekday);
  presetWeekday();
  sync();
  const el = h("div", { class: "span-2 appt-rec" }, h("label", { class: "check" }, toggle, t("appointments.rec.enable")), body);
  return {
    el,
    enabled: () => toggle.checked,
    rule() {
      const r = { freq: freq.querySelector("select").value, interval: Number(interval.querySelector("input").value || 1) };
      if (r.freq === "weekly") {
        const days = wdBoxes.filter((b) => b.firstChild.checked).map((b) => Number(b.firstChild.value));
        if (days.length) r.weekdays = days;
      }
      if (endMode.querySelector("select").value === "count") r.count = Number(count.querySelector("input").value || 0) || null;
      else r.until = until.querySelector("input").value || null;
      return r;
    },
  };
}

/** Ask "only this" vs "this and all future" for series members. Resolves "this" | "this_and_future" | null. */
export function askEditScope() {
  return new Promise((resolve) => {
    let result = null;
    openModal({
      title: t("appointments.edit_scope.title"), size: "sm",
      body: h("p", t("appointments.edit_scope.message")),
      actions: [
        { label: t("appointments.edit_scope.this"), onClick: () => { result = "this"; } },
        { label: t("appointments.edit_scope.future"), variant: "primary", onClick: () => { result = "this_and_future"; } },
      ],
      onClose: () => resolve(result),
    });
  });
}

/**
 * openAppointmentForm({ctx, meta, appt?, defaults?: {date, start, clinic_id, doctor_id, patient}, recurring?, onSaved})
 */
export function openAppointmentForm({ ctx, meta, appt = null, defaults = {}, recurring = false, onSaved }) {
  const editing = !!appt;
  const alertBox = h("div", { class: "appt-alerts" });
  const patient = patientPicker({ initial: appt ? appt.patient : defaults.patient, onChange: () => {}, ctx,
    allowCreate: !editing && meta.can?.create, getClinicId: () => place.clinic() });
  const place = placePickers({ meta, ctx, clinicId: appt?.clinic?.id || defaults.clinic_id, doctorId: appt?.doctor?.id || defaults.doctor_id,
    onClinic: (c) => { if (!endTouched) endInput.value = addMinutes(startInput.value, c?.default_duration_minutes || meta.default_duration_minutes); locationInput.placeholder = c?.location || ""; } });
  const defClinic = place.clinicObj?.();
  const defDuration = defClinic?.default_duration_minutes || meta.default_duration_minutes || 15;
  const startDefault = appt?.start_time || defaults.start || "09:00";
  const dateF = field({ name: "date", label: t("appointments.field.date"), type: "date", required: true }, appt?.local_date || defaults.date || todayISO());
  const startF = field({ name: "start", label: t("appointments.field.start"), type: "time", required: true, step: 300 }, startDefault);
  const endF = field({ name: "end", label: t("appointments.field.end"), type: "time", required: true, step: 300 },
    appt?.end_time || addMinutes(startDefault, defDuration));
  const dateInput = dateF.querySelector("input");
  const startInput = startF.querySelector("input");
  const endInput = endF.querySelector("input");
  let endTouched = editing;
  let lastStart = startInput.value;
  startInput.addEventListener("change", () => {
    // Keep the duration when the start moves.
    const dur = Math.max(5, minutesBetween(lastStart, endInput.value) || defDuration);
    endInput.value = addMinutes(startInput.value, dur);
    lastStart = startInput.value;
  });
  endInput.addEventListener("change", () => { endTouched = true; });
  const typeF = field({ name: "appointment_type", label: t("appointments.field.type"), type: "select",
    options: typeOptions(meta, appt?.appointment_type) }, appt?.appointment_type || "");
  const locF = field({ name: "location", label: t("appointments.field.location"), maxLength: 200, help: t("appointments.field.location_help") }, appt?.location || "");
  const locationInput = locF.querySelector("input");
  locationInput.placeholder = defClinic?.location || "";
  const reasonF = field({ name: "reason", label: t("appointments.field.reason"), maxLength: 300, span: 2 }, appt?.reason || "");
  const notesF = field({ name: "notes", label: t("appointments.field.notes"), type: "textarea", maxLength: 5000, span: 2, rows: 3 }, appt?.notes || "");
  const rec = !editing ? recurrenceSection(dateInput, recurring) : null;

  const grid = h("div", { class: "form-grid" }, patient.el, ...place.nodes, dateF, h("div", { class: "row appt-times" }, startF, endF),
    typeF, locF, reasonF, notesF, rec ? rec.el : null);
  const form = h("form", { class: "form", novalidate: true }, alertBox, grid);
  const modal = openModal({ title: editing ? t("appointments.edit") : recurring ? t("appointments.recurring") : t("appointments.new"),
    size: "lg", body: form,
    footer: [h("button", { class: "btn", type: "button", onClick: () => modal.close() }, t("core.cancel")),
      h("button", { class: "btn btn-primary", type: "button", onClick: () => form.requestSubmit() }, icon("check"), t("core.save"))] });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearFieldErrors(form);
    alertBox.replaceChildren();
    const v = readValues(form, [{ name: "date" }, { name: "start" }, { name: "end" }, { name: "appointment_type" },
      { name: "location" }, { name: "reason" }, { name: "notes" }]);
    const missing = {};
    const p = patient.get();
    if (!p) missing.patient_id = t("appointments.patient.required");
    if (!meta.is_doctor && !place.clinic()) missing.clinic_id = t("core.form.required");
    for (const k of ["date", "start", "end"]) if (!v[k]) missing[k] = t("core.form.required");
    if (Object.keys(missing).length) return setFieldErrors(form, missing);
    const body = {
      patient_id: p.id, starts_at: `${v.date}T${v.start}`, ends_at: `${v.date}T${v.end}`,
      appointment_type: v.appointment_type, location: v.location, reason: v.reason, notes: v.notes,
    };
    if (!meta.is_doctor) { body.clinic_id = place.clinic(); body.doctor_id = place.doctor(); }
    const buttons = modal.el.querySelectorAll(".modal-footer .btn");
    buttons.forEach((b) => { b.disabled = true; });
    try {
      if (editing) {
        let mode = "this";
        if (appt.series_id) {
          mode = await askEditScope();
          if (!mode) return;
        }
        const saved = await api.put(`/appointments/${appt.id}`, { ...body, version: appt.version, mode });
        toastSuccess(t("appointments.saved"));
        modal.close();
        onSaved?.(saved);
      } else if (rec?.enabled()) {
        const res = await api.post("/appointments/recurring", { ...body, rule: rec.rule() });
        toastSuccess(t("appointments.rec.created", { n: res.items.length }));
        modal.close();
        onSaved?.(res.items[0]);
      } else {
        const res = await api.post("/appointments", body, { offline: true, label: t("appointments.new") });
        if (res?.queued) toast(t("appointments.saved_offline"), { type: "warning" });
        else toastSuccess(t("appointments.created"));
        modal.close();
        onSaved?.(res?.queued ? null : res);
      }
    } catch (err) {
      showError(err, form, alertBox, editing ? () => { modal.close(); onSaved?.(null, { reload: appt.id }); } : null);
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  });
  return modal;
}

/** Map an API error onto the dialog: conflicts, version conflicts, field errors, others. */
export function showError(err, form, alertBox, onReload) {
  const block = conflictBlock(err);
  if (block) { alertBox.replaceChildren(block); alertBox.scrollIntoView({ block: "nearest" }); return; }
  if (err?.code === "version_conflict") {
    alertBox.replaceChildren(h("div", { class: "alert alert-warning", role: "alert" }, t("appointments.version_conflict"), " ",
      onReload ? h("button", { class: "btn btn-sm", type: "button", onClick: onReload }, icon("refresh"), t("appointments.reload")) : null));
    return;
  }
  if (err?.status === 422 && err.details && typeof err.details === "object") {
    const details = mapDetails(err.details);
    setFieldErrors(form, details);
    const unknown = Object.keys(details).filter((k) => !form.querySelector(`[data-field="${CSS.escape(k)}"]`));
    if (unknown.length || err.code !== "validation_error") {
      alertBox.replaceChildren(h("div", { class: "alert alert-danger", role: "alert" }, err.message,
        unknown.length ? ` (${unknown.map((k) => `${k}: ${details[k]}`).join(" · ")})` : ""));
    }
    return;
  }
  if (err?.status && err.status < 500 && err.status !== 401) {
    alertBox.replaceChildren(h("div", { class: "alert alert-danger", role: "alert" }, err.message));
    return;
  }
  toastApiError(err);
}

/** Walk-in: clinic -> find/register patient -> doctor -> Mark arrived (POST /appointments/walk-in). */
export function openWalkIn({ ctx, meta, onSaved }) {
  const alertBox = h("div", { class: "appt-alerts" });
  const place = placePickers({ meta, ctx, onClinic: () => {} });
  const patient = patientPicker({ onChange: () => {}, ctx, allowCreate: true, getClinicId: () => place.clinic() });
  const durF = field({ name: "duration_minutes", label: t("appointments.field.duration"), type: "number", min: 1, max: 1440,
    help: t("appointments.walkin.duration_help") });
  const typeF = field({ name: "appointment_type", label: t("appointments.field.type"), type: "select", options: typeOptions(meta) });
  const reasonF = field({ name: "reason", label: t("appointments.field.reason"), maxLength: 300, span: 2 });
  const [clinicNode, doctorNode] = place.nodes;
  const grid = h("div", { class: "form-grid" },
    h("div", { class: "form-section-title span-2" }, t("appointments.walkin.step_clinic")), clinicNode,
    meta.is_doctor ? null : h("div"),
    h("div", { class: "form-section-title span-2" }, t("appointments.walkin.step_patient")), patient.el,
    meta.is_doctor ? null : h("div", { class: "form-section-title span-2" }, t("appointments.walkin.step_doctor")),
    doctorNode || null, durF, typeF, reasonF);
  const form = h("form", { class: "form", novalidate: true }, alertBox, grid);
  const modal = openModal({ title: t("appointments.walkin.title"), size: "lg", body: form,
    footer: [h("button", { class: "btn", type: "button", onClick: () => modal.close() }, t("core.cancel")),
      h("button", { class: "btn btn-primary", type: "button", onClick: () => form.requestSubmit() }, icon("check"), t("appointments.walkin.submit"))] });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearFieldErrors(form);
    alertBox.replaceChildren();
    const p = patient.get();
    const missing = {};
    if (!p) missing.patient_id = t("appointments.patient.required");
    if (!meta.is_doctor && !place.clinic()) missing.clinic_id = t("core.form.required");
    if (Object.keys(missing).length) return setFieldErrors(form, missing);
    const v = readValues(form, [{ name: "duration_minutes", type: "number" }, { name: "appointment_type" }, { name: "reason" }]);
    const body = { patient_id: p.id, duration_minutes: v.duration_minutes, appointment_type: v.appointment_type, reason: v.reason };
    if (!meta.is_doctor) { body.clinic_id = place.clinic(); body.doctor_id = place.doctor(); }
    try {
      const res = await api.post("/appointments/walk-in", body);
      toastSuccess(t("appointments.walkin.done"));
      modal.close();
      onSaved?.(res);
    } catch (err) { showError(err, form, alertBox); }
  });
  return modal;
}

