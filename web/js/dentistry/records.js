// Treatments and treatment-plan items for one patient in one dental clinic.
import {
  api, h, t, icon, can, dataTable, createForm, getActiveDepartment, openModal, confirmDialog, deleteWithUndo, formatDate, formatMoney,
  todayISO, mount,
} from "../core/index.js";
import {
  dentUrl, filterSelect, loadDoctors, mutationError, priorityBadge, priorityOptions, procedureList, savedNotice,
  statusBadge, statusOptions, toothLabel, toothModes,
} from "./common.js";

async function doctorOptions(clinicId) {
  try {
    return (await loadDoctors(clinicId)).map((d) => ({ value: d.id, label: d.name }));
  } catch {
    return [];
  }
}

const commonFields = (meta, doctors, values) => [
  { name: "tooth_mode", label: t("dentistry.field.tooth_mode"), type: "select", options: toothModes(), empty: false },
  { name: "tooth_number", label: t("dentistry.field.tooth_number"), type: "number", min: 1, max: 32,
    help: t("dentistry.tooth_help") },
  { name: "procedure", label: t("dentistry.field.procedure"), maxLength: 150, attrs: { list: values.__list } },
  { name: "fee", label: t("dentistry.field.fee"), type: "money", min: 0 },
  { name: "status", label: t("dentistry.field.status"), type: "select", options: statusOptions(meta), empty: false },
  { name: "doctor_user_id", label: t("dentistry.field.doctor"), type: "select", options: doctors, numeric: true },
];

/** Favorite procedures (center + department) with default prices: picking one fills procedure + fee. */
function procedurePicker(formEl) {
  const sel = h("select", { class: "select", "aria-label": t("dentistry.fav.pick") }, h("option", { value: "" }, t("dentistry.fav.pick")));
  sel.hidden = true;
  let favs = [];
  const dept = getActiveDepartment();
  api.get("/favorites", { query: { kind: "procedure", department_id: dept?.id } }).then((res) => {
    favs = res.items || [];
    sel.append(...favs.map((f) => h("option", { value: f.id }, f.payload?.price ? `${f.title} — ${formatMoney(f.payload.price)}` : f.title)));
    sel.hidden = !favs.length;
  }).catch(() => {});
  sel.addEventListener("change", () => {
    const f = favs.find((x) => String(x.id) === sel.value);
    if (!f) return;
    formEl.elements.namedItem("procedure").value = f.title;
    if (f.payload?.price != null) formEl.elements.namedItem("fee").value = f.payload.price;
    sel.value = "";
  });
  return sel;
}

function cleanTooth(v) {
  if (v.tooth_number != null) v.tooth_number = Number(v.tooth_number);
  return v;
}

// ---------------------------------------------------------------------------- treatments
export function renderTreatments(panel, { patientId, clinicId, meta }) {
  let status = null;
  const canCreate = can("medical_records.create");
  const canEdit = can("medical_records.edit");
  const canDelete = can("medical_records.delete");
  const total = h("div", { class: "dent-total text-sm" });

  const table = dataTable({
    columns: [
      { key: "date", label: t("dentistry.field.date"), render: (r) => h("span", { class: "nowrap" }, formatDate(r.date, { year: "always" })) },
      { key: "tooth", label: t("dentistry.tooth"), render: (r) => h("span", { class: "dent-tooth-chip ltr" }, toothLabel(r)) },
      { key: "procedure", label: t("dentistry.field.procedure"), render: (r) => h("div",
        h("strong", r.procedure || r.description || "—"),
        r.procedure && r.description ? h("div", { class: "text-sm text-muted" }, r.description) : null,
        r.plan_id ? h("div", { class: "text-xs text-muted" }, t("dentistry.from_plan")) : null) },
      { key: "doctor", label: t("dentistry.field.doctor"), render: (r) => r.doctor_name || "—" },
      { key: "fee", label: t("dentistry.field.fee"), class: "num", render: (r) => formatMoney(r.fee) },
      { key: "status", label: t("dentistry.field.status"), render: (r) => (canEdit ? statusSelect(r) : statusBadge(r.status)) },
      { key: "actions", label: "", class: "actions no-print", render: (r) => h("div", { class: "btn-group" },
        canEdit ? h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-label": t("core.edit"), title: t("core.edit"),
          onClick: () => openForm(r) }, icon("edit")) : null,
        canDelete ? h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-label": t("core.delete"), title: t("core.delete"),
          onClick: () => remove(r) }, icon("trash")) : null) },
    ],
    fetch: async (q) => {
      const res = await api.get(dentUrl("/treatments"), { query: { ...q, patient_id: patientId, clinic_id: clinicId, status }, cache: true });
      const sum = (res.items || []).filter((x) => x.status !== "cancelled").reduce((a, x) => a + Number(x.fee || 0), 0);
      mount(total, t("dentistry.page_total", { amount: formatMoney(sum.toFixed(2)) }));
      return res;
    },
    perPage: 50,
    toolbar: [
      filterSelect(t("dentistry.all_statuses"), statusOptions(meta), status, (v) => { status = v; table.reload(); }),
      total,
      canCreate ? h("button", { type: "button", class: "btn btn-primary", onClick: () => openForm(null) }, icon("plus"), t("dentistry.treatment.new")) : null,
    ],
    empty: { icon: "tooth", title: t("dentistry.treatment.empty") },
  });

  function statusSelect(r) {
    const sel = h("select", { class: "select select-sm", "aria-label": t("dentistry.field.status"),
      onChange: async () => {
        try {
          const res = await api.patch(dentUrl(`/treatments/${r.id}`), { status: sel.value, version: r.version },
            { offline: true, label: t("dentistry.treatment.title") });
          savedNotice(res);
          if (!res?.queued) table.reload();
        } catch (e) {
          sel.value = r.status;
          mutationError(e, table.reload);
        }
      } }, statusOptions(meta).map((o) => h("option", { value: o.value }, o.label)));
    sel.value = r.status;
    return sel;
  }

  async function remove(r) {
    if (!(await confirmDialog({ danger: true, message: t("dentistry.treatment.confirm_delete") }))) return;
    await deleteWithUndo(dentUrl(`/treatments/${r.id}`), { message: t("dentistry.deleted"), onDone: table.reload, onUndone: table.reload })
      .catch(() => {});
  }

  async function openForm(row) {
    const doctors = await doctorOptions(clinicId);
    const dl = procedureList(meta);
    const values = row ? { ...row } : { tooth_mode: "permanent", status: "planned", fee: "0.00", date: todayISO(), create_visit: false };
    values.__list = dl.id;
    const fields = [
      ...commonFields(meta, doctors, values),
      { name: "date", label: t("dentistry.field.date"), type: "date", required: true },
      { name: "description", label: t("dentistry.field.description"), type: "textarea", span: 2, maxLength: 5000 },
      !row && canCreate ? { name: "create_visit", label: t("dentistry.create_visit"), type: "checkbox", span: 2,
        help: t("dentistry.create_visit_help") } : null,
      row && !row.visit_id && canCreate ? { name: "create_visit", label: t("dentistry.record_session"), type: "checkbox", span: 2 } : null,
    ].filter(Boolean);
    const form = createForm({
      fields, values,
      onSubmit: async (v) => {
        cleanTooth(v);
        if (!v.create_visit) delete v.create_visit;
        let res;
        if (row) {
          res = await api.patch(dentUrl(`/treatments/${row.id}`), { ...v, version: row.version },
            { offline: true, label: t("dentistry.treatment.title") });
        } else {
          res = await api.post(dentUrl("/treatments"), { ...v, patient_id: patientId, clinic_id: clinicId },
            { offline: !v.create_visit, label: t("dentistry.treatment.new") });
        }
        modal.close();
        savedNotice(res);
        table.reload();
      },
      onCancel: () => modal.close(),
    });
    const modal = openModal({ title: row ? t("dentistry.treatment.edit") : t("dentistry.treatment.new"),
      body: [procedurePicker(form.el), form.el, dl.el], size: "lg" });
  }

  mount(panel, table.el);
  return table;
}

// ---------------------------------------------------------------------------- plans
export function renderPlans(panel, { patientId, clinicId, meta, onConverted }) {
  let priority = null;
  const canCreate = can("medical_records.create");
  const canEdit = can("medical_records.edit");
  const canDelete = can("medical_records.delete");

  const table = dataTable({
    columns: [
      { key: "tooth", label: t("dentistry.tooth"), render: (r) => h("span", { class: "dent-tooth-chip ltr" }, toothLabel(r)) },
      { key: "procedure", label: t("dentistry.field.procedure"), render: (r) => h("div", h("strong", r.procedure || "—"),
        r.diagnosis ? h("div", { class: "text-sm text-muted" }, t("dentistry.field.diagnosis"), ": ", r.diagnosis) : null,
        r.notes ? h("div", { class: "text-xs text-muted" }, r.notes) : null) },
      { key: "priority", label: t("dentistry.field.priority"), render: (r) => priorityBadge(r.priority) },
      { key: "fee", label: t("dentistry.field.fee"), class: "num", render: (r) => formatMoney(r.fee) },
      { key: "status", label: t("dentistry.field.status"), render: (r) => h("div", statusBadge(r.status),
        r.converted_treatment_id ? h("div", { class: "text-xs text-muted" }, t("dentistry.plan.converted")) : null) },
      { key: "actions", label: "", class: "actions no-print", render: (r) => h("div", { class: "btn-group" },
        canCreate && !r.converted_treatment_id && r.status !== "cancelled"
          ? h("button", { type: "button", class: "btn btn-sm", onClick: () => convert(r) }, icon("arrowRight", "flip-rtl"), t("dentistry.plan.convert")) : null,
        canEdit ? h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-label": t("core.edit"), title: t("core.edit"),
          onClick: () => openForm(r) }, icon("edit")) : null,
        canDelete ? h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-label": t("core.delete"), title: t("core.delete"),
          onClick: () => remove(r) }, icon("trash")) : null) },
    ],
    fetch: (q) => api.get(dentUrl("/treatment-plans"), { query: { ...q, patient_id: patientId, clinic_id: clinicId, priority }, cache: true }),
    perPage: 50,
    toolbar: [
      filterSelect(t("dentistry.all_priorities"), priorityOptions(meta), priority, (v) => { priority = v; table.reload(); }),
      canCreate ? h("button", { type: "button", class: "btn btn-primary", onClick: () => openForm(null) }, icon("plus"), t("dentistry.plan.new")) : null,
    ],
    empty: { icon: "clipboard", title: t("dentistry.plan.empty") },
  });

  async function remove(r) {
    if (!(await confirmDialog({ danger: true, message: t("dentistry.plan.confirm_delete") }))) return;
    await deleteWithUndo(dentUrl(`/treatment-plans/${r.id}`), { message: t("dentistry.deleted"), onDone: table.reload, onUndone: table.reload })
      .catch(() => {});
  }

  async function openForm(row) {
    const doctors = await doctorOptions(clinicId);
    const dl = procedureList(meta);
    const values = row ? { ...row } : { tooth_mode: "permanent", status: "planned", priority: "medium", fee: "0.00" };
    values.__list = dl.id;
    const fields = [
      ...commonFields(meta, doctors, values),
      { name: "priority", label: t("dentistry.field.priority"), type: "select", options: priorityOptions(meta), empty: false },
      { name: "diagnosis", label: t("dentistry.field.diagnosis"), type: "textarea", span: 2, maxLength: 5000, rows: 2 },
      { name: "notes", label: t("dentistry.field.notes"), type: "textarea", span: 2, maxLength: 5000, rows: 2 },
    ];
    const form = createForm({
      fields, values,
      onSubmit: async (v) => {
        cleanTooth(v);
        const res = row
          ? await api.patch(dentUrl(`/treatment-plans/${row.id}`), { ...v, version: row.version }, { offline: true, label: t("dentistry.plan.title") })
          : await api.post(dentUrl("/treatment-plans"), { ...v, patient_id: patientId, clinic_id: clinicId }, { offline: true, label: t("dentistry.plan.new") });
        modal.close();
        savedNotice(res);
        table.reload();
      },
      onCancel: () => modal.close(),
    });
    const modal = openModal({ title: row ? t("dentistry.plan.edit") : t("dentistry.plan.new"), body: [form.el, dl.el], size: "lg" });
  }

  function convert(r) {
    const form = createForm({
      columns: 1,
      fields: [
        { name: "date", label: t("dentistry.field.date"), type: "date", required: true },
        { name: "status", label: t("dentistry.field.status"), type: "select", options: statusOptions(meta), empty: false },
        { name: "create_visit", label: t("dentistry.create_visit"), type: "checkbox", help: t("dentistry.create_visit_help") },
      ],
      values: { date: todayISO(), status: "planned" },
      submitLabel: t("dentistry.plan.convert"),
      onSubmit: async (v) => {
        try {
          await api.post(dentUrl(`/treatment-plans/${r.id}/convert`), { ...v, version: r.version });
        } catch (e) {
          if (e.code === "version_conflict" || e.code === "already_converted") {
            modal.close();
            mutationError(e.code === "already_converted" ? { message: e.message } : e, table.reload);
            table.reload();
            return;
          }
          throw e;
        }
        modal.close();
        savedNotice({});
        table.reload();
        if (onConverted) onConverted();
      },
      onCancel: () => modal.close(),
    });
    const modal = openModal({
      title: t("dentistry.plan.convert_title"),
      body: [h("p", { class: "text-sm" }, `${toothLabel(r)} · ${r.procedure || ""} · ${formatMoney(r.fee)}`), form.el],
    });
  }

  mount(panel, table.el);
  return table;
}
