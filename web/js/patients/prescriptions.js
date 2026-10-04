// Reusable prescriptions UI (exported for every specialty):
//   prescriptionsPanel({ctx, patient: {id}, visit?: {id, clinic_id}, compact?}) -> element (list + "New")
//   openPrescriptionEditor({ctx, patient, visit?, rx?, onSaved(rx)})            -> modal (create / edit while pending)
//   printPrescription(rx)                                                        -> PDF (GET /prescriptions/<id>/pdf)
import { api, h, t, mount, icon, can, toast, toastApiError, openModal, confirmDialog, deleteWithUndo, statusPill,
  formatDateTime, printPdf, getLang, loadingState, errorState, emptyState, withBusy, setFieldErrors } from "../core/index.js";

let metaCache = null;
const loadRxMeta = () => (metaCache ||= api.get("/prescriptions/meta", { cache: true }).catch((e) => { metaCache = null; throw e; }));

export function printPrescription(rx) {
  printPdf(`/prescriptions/${rx.id}/pdf`, { lang: getLang() });
}

export function prescriptionsPanel({ ctx, patient, visit = null, compact = false }) {
  const list = h("div", { class: "stack" });
  const newBtn = can("medical_records.create") ? h("button", { class: "btn btn-primary btn-sm", type: "button",
    onClick: () => openPrescriptionEditor({ ctx, patient, visit, onSaved: load }) }, icon("plus"), t("patients.rx.new")) : null;

  async function load() {
    mount(list, loadingState());
    try {
      const res = await api.get("/prescriptions", { query: { patient_id: patient.id, visit_id: visit?.id, per_page: 50 }, cache: true });
      const items = res.items || [];
      if (!items.length) return mount(list, emptyState({ icon: "rx", title: t("patients.rx.none") }));
      mount(list, items.map((rx) => rxCard(rx)));
    } catch (e) {
      mount(list, errorState(e, load));
    }
  }

  function rxCard(rx) {
    const pending = rx.status === "pending";
    const actions = [
      h("button", { class: "btn btn-sm", type: "button", onClick: () => printPrescription(rx) }, icon("printer"), t("core.print")),
      pending && can("medical_records.edit") ? h("button", { class: "btn btn-sm", type: "button",
        onClick: () => openPrescriptionEditor({ ctx, patient, visit, rx, onSaved: load }) }, icon("edit"), t("core.edit")) : null,
      ["pending", "partially_dispensed"].includes(rx.status) && can("medical_records.edit") ? h("button", { class: "btn btn-sm", type: "button",
        onClick: (e) => cancel(e.currentTarget, rx) }, icon("x"), t("patients.rx.cancel")) : null,
      ["pending", "cancelled"].includes(rx.status) && can("medical_records.delete") ? h("button", { class: "btn btn-sm btn-ghost", type: "button",
        "aria-label": t("core.delete"), title: t("core.delete"), onClick: () => remove(rx) }, icon("trash")) : null,
    ];
    return h("article", { class: "card pat-rx" },
      h("div", { class: "card-header row-between" },
        h("div", h("strong", formatDateTime(rx.prescribed_at, { year: "always" })), " ",
          h("span", { class: "text-sm text-muted" }, [rx.clinic_name, rx.author_name].filter(Boolean).join(" · "))),
        statusPill(rx.status, "patients.rx_status")),
      h("div", { class: "card-body" }, rxItemsTable(rx.items),
        rx.notes ? h("p", { class: "text-sm" }, h("strong", t("patients.rx.notes"), ": "), rx.notes) : null),
      h("div", { class: "card-footer row no-print" }, actions));
  }

  async function cancel(btn, rx) {
    if (!(await confirmDialog({ message: t("patients.rx.cancel_confirm"), danger: true }))) return;
    await withBusy(btn, async () => {
      try {
        await api.post(`/prescriptions/${rx.id}/cancel`, { version: rx.version });
        toast(t("patients.rx.cancelled"), { type: "success" });
      } catch (e) { toastApiError(e); }
      load();
    });
  }

  async function remove(rx) {
    if (!(await confirmDialog({ danger: true, message: t("patients.rx.delete_confirm") }))) return;
    try {
      await deleteWithUndo(`/prescriptions/${rx.id}`, { message: t("patients.rx.deleted"), onDone: load, onUndone: load });
    } catch { /* toast shown */ }
  }

  load();
  return h("div", { class: ["pat-rx-panel", compact && "is-compact"] },
    newBtn ? h("div", { class: "row-between", style: "margin-bottom:12px" }, h("span"), newBtn) : null, list);
}

export function rxItemsTable(items = []) {
  const cols = ["#", t("patients.rx.medication"), t("patients.rx.dose"), t("patients.rx.frequency"), t("patients.rx.duration"), t("patients.rx.quantity")];
  return h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
    h("thead", h("tr", cols.map((c) => h("th", c)))),
    h("tbody", items.map((i, n) => h("tr",
      h("td", { "data-label": "#" }, n + 1),
      h("td", { "data-label": cols[1] }, h("strong", i.medication_name), i.instructions ? h("div", { class: "text-xs text-muted" }, i.instructions) : null),
      h("td", { "data-label": cols[2] }, i.dose || ""), h("td", { "data-label": cols[3] }, i.frequency || ""),
      h("td", { "data-label": cols[4] }, i.duration || ""),
      h("td", { "data-label": cols[5], class: "num" }, i.quantity != null ? String(Number(i.quantity)) : ""))))));
}

const ITEM_FIELDS = [
  ["medication_name", 200], ["dose", 100], ["frequency", 100], ["duration", 100], ["quantity", null], ["instructions", 2000],
];

/** Create (rx omitted) or edit a pending prescription (items replaced). */
export async function openPrescriptionEditor({ ctx, patient, visit = null, rx = null, onSaved } = {}) {
  let clinics = [];
  if (!rx && !visit) {
    try {
      const meta = await loadRxMeta();
      clinics = (meta.clinics || []).filter((c) => ctx?.area !== "department" || c.department_id === ctx.dept.id);
    } catch (e) { return toastApiError(e); }
    if (!clinics.length) return toast(t("patients.register.no_clinic"), { type: "warning" });
  }
  const rows = h("div", { class: "stack-sm pat-rx-rows" });
  const errorBox = h("div");
  const clinicSel = clinics.length ? h("select", { class: "select", name: "clinic_id", required: true },
    clinics.length > 1 ? h("option", { value: "" }, t("core.select_placeholder")) : null,
    clinics.map((c) => h("option", { value: c.id }, ctx?.area === "department" ? c.name : `${c.department_name} — ${c.name}`))) : null;
  const notes = h("textarea", { class: "textarea", name: "notes", rows: 2, maxlength: 5000 });
  notes.value = rx?.notes || "";

  function addRow(item = {}) {
    const inputs = ITEM_FIELDS.map(([k, max]) => {
      const el = h("input", { class: "input", name: k, placeholder: t(`patients.rx.${k === "medication_name" ? "medication" : k}`),
        "aria-label": t(`patients.rx.${k === "medication_name" ? "medication" : k}`), maxlength: max,
        type: k === "quantity" ? "number" : "text", min: k === "quantity" ? 0 : null, step: k === "quantity" ? "0.01" : null,
        required: k === "medication_name" });
      el.value = item[k] != null ? (k === "quantity" ? String(Number(item[k])) : item[k]) : "";
      return el;
    });
    const row = h("div", { class: "pat-rx-row" }, inputs,
      h("button", { class: "btn btn-ghost btn-icon btn-sm", type: "button", "aria-label": t("core.delete"),
        onClick: () => { row.remove(); if (!rows.children.length) addRow(); } }, icon("x")));
    rows.append(row);
    inputs[0].focus?.();
  }
  (rx?.items?.length ? rx.items : [{}]).forEach((i) => addRow(i));
  rows.querySelector("input")?.blur?.();

  // Favorite prescription sets (center-wide + this department): load into the rows, or save the rows as a set.
  const deptId = ctx?.dept?.id || visit?.department_id || null;
  const setSel = h("select", { class: "select", "aria-label": t("patients.rx.sets") }, h("option", { value: "" }, t("patients.rx.load_set")));
  let sets = [];
  api.get("/favorites", { query: { kind: "rx_set", department_id: deptId || undefined } }).then((res) => {
    sets = res.items || [];
    setSel.append(...sets.map((f) => h("option", { value: f.id }, f.title)));
    setSel.hidden = !sets.length;
  }).catch(() => { setSel.hidden = true; });
  setSel.addEventListener("change", () => {
    const f = sets.find((x) => String(x.id) === setSel.value);
    if (!f) return;
    const empty = [...rows.children].filter((r) => !r.querySelector('[name="medication_name"]').value.trim());
    empty.forEach((r) => r.remove());
    (f.payload.items || []).forEach((i) => addRow(i));
    setSel.value = "";
  });
  const saveSetBtn = deptId && can("medical_records.create") ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: async () => {
    const items = collect().items.filter((i) => i.medication_name);
    if (!items.length) return;
    const title = window.prompt(t("patients.rx.set_name"), items.map((i) => i.medication_name).join(" + ").slice(0, 80));
    if (!title) return;
    try {
      await api.post("/favorites", { kind: "rx_set", department_id: deptId, title, payload: { items } });
      toast(t("patients.rx.set_saved"), { type: "success" });
    } catch (e) { toastApiError(e); }
  } }, icon("plus"), t("patients.rx.save_set")) : null;

  const form = h("form", { class: "form", novalidate: true },
    errorBox,
    h("div", { class: "row gap-sm wrap" }, setSel, saveSetBtn),
    clinicSel ? h("div", { class: "field", dataset: { field: "clinic_id" } }, h("label", t("patients.field.clinic")), clinicSel) : null,
    h("div", { class: "field", dataset: { field: "items" } }, h("label", t("patients.rx.items")), rows,
      h("button", { class: "btn btn-sm", type: "button", onClick: () => addRow() }, icon("plus"), t("patients.rx.add_item"))),
    h("div", { class: "field", dataset: { field: "notes" } }, h("label", t("patients.rx.notes")), notes));

  const collect = () => ({
    items: [...rows.children].map((r) => {
      const o = {};
      for (const [k] of ITEM_FIELDS) {
        const v = r.querySelector(`[name="${k}"]`).value.trim();
        if (v !== "") o[k] = v;
      }
      return o;
    }).filter((o) => Object.keys(o).length),
    notes: notes.value.trim() || null,
  });

  async function save() {
    mount(errorBox);
    const body = collect();
    if (!body.items.length || body.items.some((i) => !i.medication_name)) {
      mount(errorBox, h("div", { class: "form-error-summary", role: "alert" }, t("patients.rx.need_medication")));
      return false;
    }
    try {
      let res;
      if (rx) res = await api.put(`/prescriptions/${rx.id}`, { ...body, version: rx.version }, { offline: true, label: t("patients.rx.edit") });
      else {
        const clinicId = visit ? visit.clinic_id : Number(clinicSel.value);
        if (!clinicId) {
          setFieldErrors(form, { clinic_id: t("core.form.required") });
          return false;
        }
        res = await api.post("/prescriptions", { ...body, patient_id: patient.id, clinic_id: clinicId, visit_id: visit?.id || null },
          { offline: true, label: t("patients.rx.new") });
      }
      toast(res?.queued ? t("patients.saved_offline") : t("core.saved"), { type: res?.queued ? "warning" : "success" });
      onSaved?.(res);
      return true;
    } catch (e) {
      const msg = e.code === "version_conflict" ? t("core.error.version_conflict")
        : e.details ? Object.entries(e.details).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ") : e.message;
      mount(errorBox, h("div", { class: "form-error-summary", role: "alert" }, msg));
      return false;
    }
  }

  openModal({
    title: rx ? t("patients.rx.edit") : t("patients.rx.new"), size: "xl", body: form,
    actions: [{ label: t("core.cancel") }, { label: t("core.save"), variant: "primary", onClick: save }],
  });
}
