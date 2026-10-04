// Ophthalmology environment: structured OD/OS eye examinations + glasses prescription.
// Backend: /api/v1/ophthalmology (meta-driven form: GET /meta lists every field, type, range and choice).
import {
  api, h, mount, t, can, icon, dataTable, formatDateTime, openModal, openDrawer, toastSuccess, toastApiError,
  deleteWithUndo, confirmDialog, loadingState, errorState, emptyState, patientSearch, loadStylesheet, printPdf,
  field,
} from "../core/index.js";
import { dict } from "./i18n.js";
import { registerVisitOpener, registerVisitCreator } from "../patients/hooks.js";
import { prescriptionsPanel } from "../patients/prescriptions.js";
import { filesPanel } from "../files/panel.js";

const ENV = ["ophthalmology"];
const TEXT_FIELDS = ["chief_complaint", "history", "diagnosis", "treatment", "follow_up", "notes"];
const EYES = [["right_eye", "ophthalmology.od"], ["left_eye", "ophthalmology.os"]];
// Clinical examination order (the API returns field catalogs with alphabetically sorted keys).
const BLOCK_ORDER = {
  visual_acuity: ["uncorrected", "best_corrected", "pinhole", "near"],
  refraction: ["sphere", "cylinder", "axis", "add"],
  iop: ["value", "method"],
  pupils: ["size_mm", "shape", "reaction", "rapd"],
  motility: ["status", "notes"],
  slit_lamp: ["lids", "conjunctiva", "cornea", "anterior_chamber", "iris", "lens"],
  fundus: ["dilated", "optic_disc", "cup_disc_ratio", "macula", "vessels", "periphery"],
  notes: null,
};
/** [[block, [[key, spec], ...]], ...] in clinical order; leaf blocks (notes) get key "". */
function orderedBlocks(eyeFields) {
  const blocks = [...Object.keys(BLOCK_ORDER).filter((b) => b in eyeFields),
    ...Object.keys(eyeFields).filter((b) => !(b in BLOCK_ORDER))];
  return blocks.map((b) => {
    const f = eyeFields[b];
    if (f.type) return [b, [["", f]]];
    const keys = [...(BLOCK_ORDER[b] || []).filter((k) => k in f), ...Object.keys(f).filter((k) => !(BLOCK_ORDER[b] || []).includes(k))];
    return [b, keys.map((k) => [k, f[k]])];
  });
}
let metaPromise = null;
const loadMeta = () => (metaPromise ||= api.get("/ophthalmology/meta").catch((e) => { metaPromise = null; throw e; }));

export function register(registry) {
  loadStylesheet(new URL("./ophthalmology.css", import.meta.url));
  registry.i18n(dict);
  registry.route({ area: "department", env: ENV, path: "exams", title: "ophthalmology.tab.exams",
    perm: "medical_records.view", render: renderExamsPage });
  registry.menu({ area: "department", env: ENV, key: "oph-exams", path: "exams", label: "ophthalmology.tab.exams",
    icon: "eye", perm: "medical_records.view", order: 20 });

  // Patient profile "Visits" tab (patients module) delegates to these.
  registerVisitOpener("ophthalmology", (ctx, visit) => {
    api.get(`/ophthalmology/patients/${visit.patient_id}/exams`, { query: { per_page: 100 } }).then((res) => {
      const exam = (res.items || []).find((e) => e.visit_id === visit.id);
      if (exam) openExamDrawer(exam.id, { ctx });
      else openExamEditor({ ctx, visitId: visit.id, patient: { id: visit.patient_id } });
    }).catch(toastApiError);
    return false;
  });
  registerVisitCreator("ophthalmology", (ctx, patient, { onDone } = {}) => openExamEditor({ ctx, patient, onDone }));
}

// ---------------------------------------------------------------- helpers
const fLabel = (k) => t(`ophthalmology.f.${k}`, { default: k.replace(/_/g, " ") });
const choice = (v) => t(`ophthalmology.c.${v}`, { default: v });
const dig = (o, path) => path.split(".").reduce((x, k) => (x == null ? undefined : x[k]), o);

function vaIop(exam) {
  const va = (e) => dig(exam, `${e}.visual_acuity.best_corrected`) || dig(exam, `${e}.visual_acuity.uncorrected`) || "–";
  const iop = (e) => dig(exam, `${e}.iop.value`) ?? "–";
  return { va: `${va("right_eye")} / ${va("left_eye")}`, iop: `${iop("right_eye")} / ${iop("left_eye")}` };
}

// ---------------------------------------------------------------- list page
function renderExamsPage(ctx) {
  ctx.setTitle(t("ophthalmology.tab.exams"));
  const newBtn = can("medical_records.create") ? h("button", { class: "btn btn-primary", type: "button",
    onClick: () => openExamEditor({ ctx, onDone: () => table.reload() }) }, icon("plus"), t("ophthalmology.exam.new")) : null;
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("ophthalmology.col.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
      { key: "patient", label: t("ophthalmology.col.patient"), render: (r) => h("span", h("strong", r.patient?.full_name || "—"), " ",
        h("span", { class: "muted ltr" }, r.patient?.display_code || "")) },
      { key: "va", label: t("ophthalmology.col.va"), render: (r) => h("span", { class: "ltr" }, vaIop(r).va) },
      { key: "iop", label: t("ophthalmology.col.iop"), render: (r) => h("span", { class: "ltr" }, vaIop(r).iop) },
      { key: "diagnosis", label: t("ophthalmology.col.diagnosis"), render: (r) => r.diagnosis || "—" },
      { key: "author", label: t("ophthalmology.col.author"), render: (r) => r.author_name || "—" },
    ],
    query: { department_id: ctx.dept?.id },
    fetch: (q) => api.get("/ophthalmology/exams", { query: q }),
    onRowClick: (r) => openExamDrawer(r.id, { ctx, onChanged: () => table.reload() }),
    empty: { icon: "eye", title: t("ophthalmology.exam.empty") },
  });
  return h("div", { class: "page" },
    h("div", { class: "page-header row-between" },
      h("div", h("h1", t("ophthalmology.tab.exams")), h("p", { class: "subtitle" }, ctx.dept?.name)), newBtn),
    table.el);
}

// ---------------------------------------------------------------- editor
function inputFor(spec, name, value) {
  if (spec.type === "enum") {
    const sel = h("select", { class: "select", name },
      h("option", { value: "" }, "—"), spec.choices.map((c) => h("option", { value: c }, choice(c))));
    sel.value = value ?? "";
    return sel;
  }
  if (spec.type === "boolean") {
    const sel = h("select", { class: "select", name }, h("option", { value: "" }, "—"),
      h("option", { value: "true" }, t("ophthalmology.yes")), h("option", { value: "false" }, t("ophthalmology.no")));
    sel.value = value == null ? "" : String(value);
    return sel;
  }
  const attrs = { class: "input", name, dir: spec.type === "text" ? "auto" : "ltr" };
  if (spec.type === "number") Object.assign(attrs, { type: "number", min: spec.min, max: spec.max, step: spec.step, inputmode: "decimal" });
  else Object.assign(attrs, { type: "text", maxlength: spec.max_length || (spec.type === "visual_acuity" ? 10 : null),
    placeholder: spec.type === "visual_acuity" ? "6/9" : null, title: spec.type === "visual_acuity" ? t("ophthalmology.va_help") : null });
  const el = h("input", attrs);
  el.value = value ?? "";
  return el;
}

/** Two-column OD/OS grid: one row per field, grouped by block. */
function eyeGrid(meta, exam) {
  const rows = [];
  for (const [block, specs] of orderedBlocks(meta.eye_fields)) {
    rows.push(h("div", { class: "oph-grid-block" }, t(`ophthalmology.block.${block}`)));
    for (const [key, spec] of specs) {
      const path = key ? `${block}.${key}` : block;
      rows.push(h("div", { class: "oph-grid-row", dataset: { field: path } },
        h("div", { class: "oph-grid-label" }, key ? fLabel(key) : t("ophthalmology.f.notes")),
        EYES.map(([eye]) => h("div", { class: "oph-grid-cell", dataset: { field: `${eye}.${path}` } },
          inputFor(spec, `${eye}.${path}`, dig(exam, `${eye}.${path}`)),
          h("div", { class: "field-error" })))));
    }
  }
  return h("div", { class: "oph-grid" },
    h("div", { class: "oph-grid-row oph-grid-head" }, h("div"), EYES.map(([, lbl]) => h("div", t(lbl)))),
    rows);
}

function glassesGrid(meta, glasses) {
  const g = meta.glasses_fields;
  const refr = BLOCK_ORDER.refraction.filter((k) => k in g.right);
  return h("div", { class: "oph-grid" },
    h("div", { class: "oph-grid-row oph-grid-head" }, h("div"), h("div", t("ophthalmology.right")), h("div", t("ophthalmology.left"))),
    refr.map((k) => h("div", { class: "oph-grid-row" }, h("div", { class: "oph-grid-label" }, fLabel(k)),
      ["right", "left"].map((side) => h("div", { class: "oph-grid-cell", dataset: { field: `glasses.${side}.${k}` } },
        inputFor(g[side][k], `glasses.${side}.${k}`, dig(glasses, `${side}.${k}`)), h("div", { class: "field-error" }))))),
    ["pd_mm", "lens_type", "notes"].map((k) => h("div", { class: "oph-grid-row" }, h("div", { class: "oph-grid-label" }, fLabel(k)),
      h("div", { class: "oph-grid-cell oph-grid-wide", dataset: { field: `glasses.${k}` } },
        inputFor(g[k], `glasses.${k}`, dig(glasses, k)), h("div", { class: "field-error" })))));
}

function collect(formEl, meta) {
  const out = { right_eye: {}, left_eye: {}, glasses: {} };
  for (const el of formEl.querySelectorAll("[name]")) {
    const name = el.name;
    if (!/^(right_eye|left_eye|glasses)\./.test(name)) continue;
    const raw = el.value.trim();
    if (raw === "") continue;
    const parts = name.split(".");
    const spec = parts[0] === "glasses" ? dig(meta.glasses_fields, parts.slice(1).join(".")) : dig(meta.eye_fields, parts.slice(1).join("."));
    let val = raw;
    if (spec?.type === "number") val = Number(raw);
    else if (spec?.type === "boolean") val = raw === "true";
    let o = out;
    for (const p of parts.slice(0, -1)) o = (o[p] ||= {});
    o[parts[parts.length - 1]] = val;
  }
  for (const k of TEXT_FIELDS) {
    const el = formEl.elements.namedItem(k);
    if (el) out[k] = el.value.trim() || null;
  }
  return out;
}

function showErrors(formEl, details) {
  formEl.querySelectorAll(".field-error").forEach((e) => { e.textContent = ""; });
  formEl.querySelectorAll(".has-error").forEach((e) => e.classList.remove("has-error"));
  let first = null;
  for (const [path, msg] of Object.entries(details || {})) {
    const cell = formEl.querySelector(`[data-field="${CSS.escape(path)}"]`);
    if (!cell) continue;
    cell.classList.add("has-error");
    const err = cell.querySelector(".field-error");
    if (err) err.textContent = typeof msg === "string" ? msg : JSON.stringify(msg);
    first ||= cell;
  }
  first?.scrollIntoView({ block: "center", behavior: "smooth" });
  return !!first;
}

async function openExamEditor({ ctx, patient = null, exam = null, visitId = null, onDone } = {}) {
  const creating = !exam;
  const body = h("div", loadingState());
  const modal = openModal({ title: creating ? t("ophthalmology.exam.new") : t("ophthalmology.exam.edit"), body, size: "xl" });
  let meta;
  try {
    meta = await loadMeta();
  } catch (e) {
    mount(modal.body, errorState(e));
    return;
  }
  const deptIds = new Set((ctx?.dept?.clinics || []).map((c) => c.id));
  const clinics = deptIds.size ? meta.clinics.filter((c) => deptIds.has(c.id)) : meta.clinics;
  let chosen = patient;
  const patientBox = h("div");
  const renderPatient = () => mount(patientBox, chosen?.full_name
    ? h("div", { class: "card card-body" }, h("strong", chosen.full_name), " ", h("span", { class: "muted ltr" }, chosen.display_code || ""))
    : chosen ? null : patientSearch({ autofocus: true, onSelect: (p) => { chosen = p; renderPatient(); } }).el);
  renderPatient();

  const generalErr = h("div", { class: "alert alert-danger", hidden: true });
  const textField = (k, rows = 2) => field({ name: k, label: t(`ophthalmology.field.${k}`), type: k === "follow_up" ? "text" : "textarea",
    rows, span: 2, maxLength: k === "follow_up" ? 200 : 10000 }, exam?.[k]);
  const clinicSel = creating && !visitId && clinics.length > 1
    ? field({ name: "clinic_id", label: t("ophthalmology.field.clinic"), type: "select", required: true, empty: false,
      options: clinics.map((c) => ({ value: c.id, label: c.name })) }, clinics[0]?.id) : null;
  const submit = h("button", { class: "btn btn-primary", type: "submit" }, t("core.save"));
  const formEl = h("form", { class: "form oph-form", novalidate: true },
    generalErr,
    h("div", { class: "form-grid" }, clinicSel, textField("chief_complaint"), textField("history")),
    h("h3", { class: "form-section-title" }, t("ophthalmology.section.eyes")),
    eyeGrid(meta, exam),
    h("h3", { class: "form-section-title" }, t("ophthalmology.section.assessment")),
    h("div", { class: "form-grid" }, textField("diagnosis"), textField("treatment"), textField("follow_up"), textField("notes")),
    h("h3", { class: "form-section-title" }, t("ophthalmology.section.glasses")),
    glassesGrid(meta, exam?.glasses),
    h("div", { class: "form-actions" }, h("button", { class: "btn", type: "button", onClick: () => modal.close() }, t("core.cancel")), submit));

  formEl.addEventListener("submit", async (e) => {
    e.preventDefault();
    generalErr.hidden = true;
    const data = collect(formEl, meta);
    try {
      submit.disabled = true;
      if (creating) {
        if (!chosen && !visitId) { generalErr.textContent = t("ophthalmology.exam.pick_patient"); generalErr.hidden = false; return; }
        const clinicId = Number(formEl.elements.namedItem("clinic_id")?.value) || clinics[0]?.id;
        const payload = visitId ? { visit_id: visitId, ...data } : { patient_id: chosen.id, clinic_id: clinicId, ...data };
        await api.post("/ophthalmology/exams", payload, { offline: true, label: t("ophthalmology.exam.new") });
      } else {
        await api.patch(`/ophthalmology/exams/${exam.id}`, { ...data, version: exam.version });
      }
      modal.close();
      toastSuccess(t("ophthalmology.exam.saved"));
      onDone && onDone();
    } catch (err) {
      if (err?.code === "version_conflict") { generalErr.textContent = t("core.error.version_conflict"); generalErr.hidden = false; }
      else if (err?.status === 422 && showErrors(formEl, err.details)) { /* shown inline */ }
      else if (err?.status && err.status < 500) { generalErr.textContent = err.message; generalErr.hidden = false; }
      else toastApiError(err);
    } finally {
      submit.disabled = false;
    }
  });
  mount(modal.body, h("div", { class: "stack gap-md" }, creating && !visitId ? patientBox : null, formEl));
}

// ---------------------------------------------------------------- drawer
function eyeTable(meta, exam) {
  const rows = [];
  for (const [block, specs] of orderedBlocks(meta.eye_fields)) {
    const blockRows = specs.map(([key]) => {
      const path = key ? `${block}.${key}` : block;
      const vals = EYES.map(([eye]) => dig(exam, `${eye}.${path}`));
      if (vals.every((v) => v == null || v === "")) return null;
      const fmt = (v) => (v == null || v === "" ? "–" : typeof v === "boolean" ? t(v ? "ophthalmology.yes" : "ophthalmology.no")
        : (dig(meta.eye_fields, path)?.type === "enum" ? choice(v) : String(v)));
      return h("tr", h("th", key ? fLabel(key) : t("ophthalmology.f.notes")), vals.map((v) => h("td", { dir: "auto" }, fmt(v))));
    }).filter(Boolean);
    if (blockRows.length) rows.push(h("tr", { class: "oph-table-block" }, h("th", { colspan: 3 }, t(`ophthalmology.block.${block}`))), ...blockRows);
  }
  if (!rows.length) return h("p", { class: "muted" }, "—");
  return h("table", { class: "table oph-table" },
    h("thead", h("tr", h("th"), EYES.map(([, lbl]) => h("th", t(lbl))))), h("tbody", rows));
}

function glassesTable(g) {
  const keys = ["sphere", "cylinder", "axis", "add"];
  return h("div", { class: "stack gap-sm" },
    h("table", { class: "table oph-table" },
      h("thead", h("tr", h("th"), keys.map((k) => h("th", fLabel(k))))),
      h("tbody", ["right", "left"].map((side) => h("tr", h("th", t(`ophthalmology.${side}`)),
        keys.map((k) => h("td", { class: "ltr" }, dig(g, `${side}.${k}`) ?? "–")))))),
    h("div", { class: "row gap-md wrap muted" },
      g.pd_mm ? h("span", `${fLabel("pd_mm")}: ${g.pd_mm}`) : null,
      g.lens_type ? h("span", `${fLabel("lens_type")}: ${choice(g.lens_type)}`) : null),
    g.notes ? h("p", { dir: "auto" }, g.notes) : null);
}

function openExamDrawer(id, { ctx, onChanged } = {}) {
  const body = h("div", loadingState());
  const drawer = openDrawer({ title: t("ophthalmology.exam.title"), body, size: "lg" });
  async function load() {
    let exam, meta;
    try {
      [exam, meta] = await Promise.all([api.get(`/ophthalmology/exams/${id}`), loadMeta()]);
    } catch (e) {
      mount(body, errorState(e, load));
      return;
    }
    const changed = () => { load(); onChanged && onChanged(); };
    const patient = { id: exam.patient_id, full_name: exam.patient?.full_name, display_code: exam.patient?.display_code };
    const hasGlasses = !!(exam.glasses && (exam.glasses.right || exam.glasses.left));
    const text = TEXT_FIELDS.filter((k) => exam[k]).map((k) => h("div", h("h4", t(`ophthalmology.field.${k}`)), h("p", { class: "pre-wrap", dir: "auto" }, exam[k])));
    mount(body, h("div", { class: "stack gap-md" },
      h("div", { class: "card card-body stack gap-sm" },
        h("div", { class: "muted" }, `${formatDateTime(exam.visit_at)} · ${exam.clinic_name || ""} · ${exam.author_name || ""}`),
        h("div", { class: "row gap-sm wrap" },
          can("medical_records.edit") ? h("button", { class: "btn btn-sm", type: "button",
            onClick: () => openExamEditor({ ctx, exam, onDone: changed }) }, icon("edit"), t("core.edit")) : null,
          hasGlasses ? h("button", { class: "btn btn-sm", type: "button",
            onClick: () => printPdf(`/ophthalmology/exams/${exam.id}/glasses.pdf`, { lang: document.documentElement.lang }) },
          icon("printer"), t("ophthalmology.print_glasses")) : null,
          can("medical_records.delete") ? h("button", { class: "btn btn-sm btn-danger", type: "button", onClick: async () => {
            if (!(await confirmDialog({ danger: true, message: t("ophthalmology.exam.delete_confirm") }))) return;
            await deleteWithUndo(`/ophthalmology/exams/${exam.id}`, { message: t("ophthalmology.exam.deleted"),
              onDone: () => { drawer.close(); onChanged && onChanged(); }, onUndone: () => onChanged && onChanged() }).catch(() => {});
          } }, icon("trash"), t("core.delete")) : null)),
      text.length ? h("section", { class: "card card-body stack gap-sm" }, text) : null,
      h("section", { class: "card card-body" }, h("h3", t("ophthalmology.section.eyes")), eyeTable(meta, exam)),
      hasGlasses ? h("section", { class: "card card-body" }, h("h3", t("ophthalmology.section.glasses")), glassesTable(exam.glasses)) : null,
      h("section", { class: "stack gap-sm" }, h("h3", t("ophthalmology.section.prescriptions")),
        prescriptionsPanel({ ctx, patient, visit: { id: exam.visit_id, clinic_id: exam.clinic_id }, compact: true })),
      can("files.view") ? h("section", { class: "stack gap-sm" }, h("h3", t("ophthalmology.section.files")),
        filesPanel({ ctx, patient, visit: { id: exam.visit_id, clinic_id: exam.clinic_id }, compact: true })) : null,
    ));
  }
  load();
}
