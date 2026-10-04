// Ophthalmology module entry point
import {
  api, h, mount, t, can, icon, dataTable, tabs, formatDateTime,
  openModal, openDrawer, createForm, toastSuccess, toastApiError, emptyState, loadingState, errorState,
} from "../core/index.js";
import { dict } from "./i18n.js";
import { registerPatientTab, registerVisitOpener, registerVisitCreator } from "../patients/hooks.js";

export function register(registry) {
  registry.i18n(dict);

  // Department routes
  registry.route({
    area: "department",
    env: ["ophthalmology"],
    path: "exams",
    title: "ophthalmology.tab.exams",
    perm: "medical_records.view",
    render: renderExamsList,
  });

  registry.menu({
    area: "department",
    env: ["ophthalmology"],
    key: "oph-exams",
    path: "exams",
    label: "ophthalmology.tab.exams",
    icon: "eye",
    perm: "medical_records.view",
    order: 20,
  });

  // Patient profile tab
  registerPatientTab({
    key: "ophthalmology",
    label: "ophthalmology.tab.exams",
    env: ["ophthalmology"],
    order: 27,
    perm: "medical_records.view",
    render: (panelEl, { patient }) => {
      mount(panelEl, renderPatientExamsTable(patient.id));
    },
  });

  // Visit opener & creator
  registerVisitOpener("ophthalmology", (ctx, visit) => {
    return `#/d/${ctx.dept.id}/exams?visit_id=${visit.id}`;
  });

  registerVisitCreator("ophthalmology", (ctx, patient, { onDone } = {}) => {
    openExamModal({ ctx, patient, onDone });
  });
}

function renderExamsList(ctx) {
  ctx.setTitle(t("ophthalmology.tab.exams"));
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("patients.visit.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
      { key: "patient", label: t("patients.field.full_name"), render: (r) => h("strong", r.patient?.full_name || r.patient?.name || `Patient #${r.patient_id}`) },
      { key: "diagnosis", label: t("ophthalmology.exam.diagnosis"), render: (r) => r.diagnosis || "—" },
      {
        key: "od_os", label: "OD / OS", render: (r) => {
          const od = r.right_eye?.visual_acuity?.uncorrected || r.right_eye?.iop?.value;
          const os = r.left_eye?.visual_acuity?.uncorrected || r.left_eye?.iop?.value;
          return `OD: ${od || "—"} · OS: ${os || "—"}`;
        }
      },
      { key: "clinic", label: t("patients.field.clinic"), render: (r) => r.clinic_name || "" },
    ],
    fetch: (q) => api.get("/ophthalmology/exams", { query: { ...q, department_id: ctx.dept?.id } }),
    onRowClick: (r) => openExamDetailDrawer(r.id),
    empty: { icon: "eye", title: t("ophthalmology.exam.empty") },
  });

  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("h1", t("ophthalmology.tab.exams")),
      h("p", { class: "subtitle" }, ctx.dept?.name)
    ),
    table.el
  );
}

function renderPatientExamsTable(patientId) {
  const table = dataTable({
    columns: [
      { key: "visit_at", label: t("patients.visit.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.visit_at)) },
      { key: "diagnosis", label: t("ophthalmology.exam.diagnosis"), render: (r) => r.diagnosis || "—" },
      {
        key: "va", label: t("ophthalmology.exam.va"), render: (r) => {
          const od = r.right_eye?.visual_acuity?.uncorrected || "—";
          const os = r.left_eye?.visual_acuity?.uncorrected || "—";
          return `OD: ${od} | OS: ${os}`;
        }
      },
      {
        key: "iop", label: t("ophthalmology.exam.iop"), render: (r) => {
          const od = r.right_eye?.iop?.value || "—";
          const os = r.left_eye?.iop?.value || "—";
          return `OD: ${od} | OS: ${os}`;
        }
      },
    ],
    fetch: (q) => api.get(`/ophthalmology/patients/${patientId}/exams`, { query: q }),
    onRowClick: (r) => openExamDetailDrawer(r.id),
    empty: { icon: "eye", title: t("ophthalmology.exam.empty") },
  });
  return table.el;
}

function openExamDetailDrawer(id) {
  const body = h("div", loadingState());
  const drawer = openDrawer({ title: t("ophthalmology.exam.title", { id }), body, size: "lg" });

  api.get(`/ophthalmology/exams/${id}`).then((exam) => {
    const hasGlasses = !!(exam.glasses?.right || exam.glasses?.left);
    const glassesPdfBtn = hasGlasses ? h("a", {
      class: "btn btn-sm btn-secondary",
      href: `/api/v1/ophthalmology/exams/${exam.id}/glasses.pdf`,
      target: "_blank",
    }, icon("printer"), t("ophthalmology.glasses.print")) : null;

    mount(body,
      h("div", { class: "stack gap-md" },
        glassesPdfBtn ? h("div", { class: "row-end" }, glassesPdfBtn) : null,
        h("div", { class: "card card-body" },
          h("h3", t("ophthalmology.exam.chief_complaint")),
          h("p", exam.chief_complaint || "—"),
          h("h3", { class: "mt-sm" }, t("ophthalmology.exam.diagnosis")),
          h("p", exam.diagnosis || "—"),
          h("h3", { class: "mt-sm" }, t("ophthalmology.exam.treatment")),
          h("p", exam.treatment || "—")
        ),
        h("div", { class: "grid-2col gap-md" },
          renderEyeBlock(t("ophthalmology.exam.od"), exam.right_eye),
          renderEyeBlock(t("ophthalmology.exam.os"), exam.left_eye)
        ),
        hasGlasses ? renderGlassesBlock(exam.glasses) : null
      )
    );
  }).catch((e) => {
    mount(body, errorState(e));
  });
}

function renderEyeBlock(title, data) {
  if (!data) return h("div", { class: "card card-body" }, h("h3", title), h("p", { class: "text-muted" }, "—"));
  return h("div", { class: "card card-body" },
    h("h3", title),
    h("dl", { class: "kv mt-sm" },
      h("dt", t("ophthalmology.exam.va")), h("dd", data.visual_acuity?.uncorrected || "—"),
      h("dt", t("ophthalmology.exam.iop")), h("dd", data.iop?.value ? `${data.iop.value} ${t("ophthalmology.exam.iop_mmhg")}` : "—"),
      h("dt", t("ophthalmology.exam.pupils")), h("dd", data.pupils?.reaction || "—"),
      h("dt", t("ophthalmology.exam.slit_lamp")), h("dd", data.slit_lamp?.cornea || "—"),
      h("dt", t("ophthalmology.exam.fundus")), h("dd", data.fundus?.optic_disc || "—")
    )
  );
}

function renderGlassesBlock(glasses) {
  return h("div", { class: "card card-body" },
    h("h3", t("ophthalmology.glasses.title")),
    glasses.pd_mm ? h("p", `${t("ophthalmology.glasses.pd")}: ${glasses.pd_mm} mm`) : null,
    glasses.lens_type ? h("p", `${t("ophthalmology.glasses.lens_type")}: ${t(`ophthalmology.lens.${glasses.lens_type}`, glasses.lens_type)}`) : null
  );
}

async function openExamModal({ ctx, patient, onDone }) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("ophthalmology.exam.new"), body, size: "lg" });
  let meta;
  try {
    meta = await api.get("/ophthalmology/meta");
  } catch (e) {
    mount(modal.body, errorState(e));
    return;
  }

  const clinics = ctx.dept?.clinics || meta.clinics || [];
  const defaultClinicId = clinics[0]?.id;

  function normalizeVA(v) {
    if (!v) return null;
    let s = String(v).trim().toUpperCase();
    if (/^\d+$/.test(s)) {
      const n = parseInt(s, 10);
      if (n === 6) return "6/6";
      if (n === 20) return "20/20";
      if (n <= 2) return `${n}.0`;
      if (n > 2 && n <= 60) return `6/${n}`;
    }
    return s;
  }

  let form;
  form = createForm({
    fields: [
      clinics.length > 1 ? {
        name: "clinic_id", label: t("patients.field.clinic"), type: "select", required: true,
        numeric: true, options: clinics.map((c) => ({ value: c.id, label: c.name })), span: 2,
      } : { name: "clinic_id", type: "hidden" },
      { name: "chief_complaint", label: t("ophthalmology.exam.chief_complaint"), type: "textarea", rows: 2, span: 2 },
      { type: "section", label: t("ophthalmology.exam.bilateral_findings") },
      {
        name: "od_va",
        label: `${t("ophthalmology.exam.va")} — ${t("ophthalmology.exam.od")}`,
        type: "text",
        placeholder: "6/6, 6/9, 20/20, 1.0",
        help: t("ophthalmology.exam.va_help"),
      },
      {
        name: "os_va",
        label: `${t("ophthalmology.exam.va")} — ${t("ophthalmology.exam.os")}`,
        type: "text",
        placeholder: "6/6, 6/9, 20/20, 1.0",
        help: t("ophthalmology.exam.va_help"),
      },
      {
        name: "od_iop",
        label: `${t("ophthalmology.exam.iop")} — ${t("ophthalmology.exam.od")} (${t("ophthalmology.exam.iop_mmhg")})`,
        type: "number",
        step: 0.1,
        placeholder: "10 - 21",
      },
      {
        name: "os_iop",
        label: `${t("ophthalmology.exam.iop")} — ${t("ophthalmology.exam.os")} (${t("ophthalmology.exam.iop_mmhg")})`,
        type: "number",
        step: 0.1,
        placeholder: "10 - 21",
      },
      { type: "section", label: t("ophthalmology.exam.assessment") },
      { name: "diagnosis", label: t("ophthalmology.exam.diagnosis"), type: "textarea", rows: 2, required: true, span: 2 },
      { name: "treatment", label: t("ophthalmology.exam.treatment"), type: "textarea", rows: 2, span: 2 },
    ].filter(Boolean),
    values: { clinic_id: defaultClinicId },
    submitLabel: t("core.save"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      const odVa = normalizeVA(v.od_va);
      const osVa = normalizeVA(v.os_va);
      try {
        const payload = {
          patient_id: patient.id,
          clinic_id: v.clinic_id || defaultClinicId,
          chief_complaint: v.chief_complaint || null,
          diagnosis: v.diagnosis,
          treatment: v.treatment || null,
          right_eye: {
            visual_acuity: odVa ? { uncorrected: odVa } : undefined,
            iop: (v.od_iop != null && v.od_iop !== "") ? { value: Number(v.od_iop) } : undefined,
          },
          left_eye: {
            visual_acuity: osVa ? { uncorrected: osVa } : undefined,
            iop: (v.os_iop != null && v.os_iop !== "") ? { value: Number(v.os_iop) } : undefined,
          },
        };
        await api.post("/ophthalmology/exams", payload, {
          offline: true,
          label: t("ophthalmology.exam.new"),
        });
        modal.close();
        toastSuccess(t("core.saved"));
        if (onDone) onDone();
      } catch (err) {
        if (err?.details && typeof err.details === "object") {
          const mapped = { ...err.details };
          if (mapped["right_eye.visual_acuity.uncorrected"]) {
            mapped.od_va = mapped["right_eye.visual_acuity.uncorrected"];
          }
          if (mapped["left_eye.visual_acuity.uncorrected"]) {
            mapped.os_va = mapped["left_eye.visual_acuity.uncorrected"];
          }
          if (mapped["right_eye.iop.value"]) {
            mapped.od_iop = mapped["right_eye.iop.value"];
          }
          if (mapped["left_eye.iop.value"]) {
            mapped.os_iop = mapped["left_eye.iop.value"];
          }
          form.setErrors(mapped);
        } else {
          toastApiError(err);
        }
      }
    },
  });

  mount(modal.body, form.el);
}
