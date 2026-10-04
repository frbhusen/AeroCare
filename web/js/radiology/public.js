// Public, reusable Radiology UI for other environments (patient profile, clinics, lab/rad combined tabs).
import {
  api, h, mount, t, can, icon, openModal, openDrawer, createForm, dataTable, patientSearch, patientName, toast,
  toastSuccess, toastApiError, loadingState, errorState, emptyState, formatDateTime, formatNumber,
} from "../core/index.js";
import { dict } from "./i18n.js";
import { openImageViewer } from "../components/image-viewer.js";

export function radStatusPill(status) {
  const map = {
    requested: "neutral",
    scheduled: "info",
    in_progress: "warning",
    reported: "purple",
    finalized: "success",
    cancelled: "danger",
  };
  return h("span", { class: `pill pill--${map[status] || "neutral"}` }, t(`radiology.status.${status}`, status));
}

export function radPriorityPill(p) {
  return p === "urgent" ? h("span", { class: "pill pill--danger" }, t("radiology.priority.urgent")) : null;
}

export async function openRadiologyRequestDialog({ patient, patientId, clinicId, departmentId, onCreated } = {}) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("radiology.action.new_request"), body, size: "lg" });
  let meta;
  try {
    meta = await api.get("/radiology/meta");
  } catch (e) {
    mount(modal.body, errorState(e));
    return modal;
  }

  const requestingClinics = meta.requesting_clinics || [];
  const radiologyDepts = meta.radiology_departments || [];
  if (!radiologyDepts.length) {
    mount(modal.body, emptyState({ icon: "image", title: t("radiology.empty.no_dept") }));
    return modal;
  }

  let selectedPatient = patient || (patientId ? { id: Number(patientId) } : null);
  const defClinic = clinicId || requestingClinics.find((c) => departmentId && c.department_id === Number(departmentId))?.id || requestingClinics[0]?.id;

  const radTargets = radiologyDepts.flatMap((d) => (d.clinics?.length > 1
    ? d.clinics.map((c) => ({ value: `${d.id}:${c.id}`, label: `${d.name} · ${c.name}` }))
    : [{ value: `${d.id}:`, label: d.name }]));

  const examTypes = meta.exam_types || ["x_ray", "ct", "mri", "ultrasound", "other"];

  const fields = [
    requestingClinics.length > 1 ? {
      name: "requesting_clinic_id", label: t("radiology.detail.requesting_clinic"), type: "select", required: true,
      numeric: true, options: requestingClinics.map((c) => ({ value: c.id, label: c.name }))
    } : null,
    radTargets.length > 1 ? {
      name: "rad_target", label: t("radiology.detail.radiology"), type: "select", required: true, options: radTargets
    } : null,
    {
      name: "exam_type", label: t("radiology.col.exam"), type: "select", required: true, empty: false,
      options: examTypes.map((e) => ({ value: e, label: t(`radiology.exam.${e}`, e) }))
    },
    { name: "body_region", label: t("radiology.col.region"), type: "text", maxLength: 100 },
    {
      name: "priority", label: t("radiology.col.priority"), type: "select", required: true, empty: false,
      options: ["routine", "urgent"].map((p) => ({ value: p, label: t(`radiology.priority.${p}`, p) }))
    },
    { name: "clinical_question", label: t("radiology.detail.question"), type: "textarea", span: 2, rows: 3, maxLength: 2000 },
  ].filter(Boolean);

  const patientBlock = h("div", { class: "field span-2", dataset: { field: "patient_id" } },
    h("label", t("radiology.col.patient")),
    selectedPatient?.full_name || selectedPatient?.name
      ? h("div", h("strong", patientName(selectedPatient)), selectedPatient.code ? h("span", { class: "ltr text-muted" }, ` (${selectedPatient.code})`) : null)
      : selectedPatient ? h("div", `#${selectedPatient.id}`)
        : patientSearch({ onSelect: (p) => { selectedPatient = p; }, autofocus: true }).el
  );

  const form = createForm({
    fields,
    values: {
      requesting_clinic_id: defClinic,
      rad_target: radTargets[0]?.value,
      exam_type: "x_ray",
      priority: "routine",
    },
    submitLabel: t("radiology.action.new_request"),
    onCancel: () => modal.close(),
    onSubmit: async (v, f) => {
      if (!selectedPatient) return f.setErrors({ patient_id: t("laboratory.form.choose_patient") });
      const [radDept, radClinic] = String(v.rad_target || radTargets[0].value).split(":");
      const bodyPayload = {
        patient_id: selectedPatient.id,
        requesting_clinic_id: v.requesting_clinic_id || defClinic,
        radiology_department_id: Number(radDept),
        radiology_clinic_id: radClinic ? Number(radClinic) : null,
        exam_type: v.exam_type,
        body_region: v.body_region || null,
        priority: v.priority,
        clinical_question: v.clinical_question || null,
      };
      try {
        const res = await api.post("/radiology/studies", bodyPayload, {
          offline: true,
          label: t("radiology.action.new_request"),
        });
        modal.close();
        if (res?.queued) toast(t("laboratory.msg.saved_offline"), { type: "warning" });
        else toastSuccess(t("core.saved"));
        if (onCreated) onCreated(res);
      } catch (err) {
        toastApiError(err);
      }
    },
  });

  form.el.firstElementChild.prepend(patientBlock);
  mount(modal.body, form.el);
  return modal;
}

export function openRadiologyStudyDrawer(id, { onChanged } = {}) {
  const body = h("div", loadingState());
  const drawer = openDrawer({ title: t("radiology.detail.title", { id }), body, size: "lg" });

  async function load() {
    try {
      const study = await api.get(`/radiology/studies/${id}`);
      render(study);
    } catch (e) {
      mount(body, errorState(e, load));
    }
  }

  function render(s) {
    const isFinal = s.status === "finalized";
    const images = s.images || [];

    const imgGrid = h("div", { class: "rad-images-grid row gap-sm wrap mt-sm" });
    if (images.length) {
      mount(imgGrid, images.map((img) => h("div", {
        class: "rad-thumb card",
        style: "cursor: pointer; width: 120px; text-align: center; padding: 4px;",
        onClick: () => openImageViewer({
          src: `/api/v1/files/${img.id}/content`,
          title: img.display_name,
          annotations: img.annotations || [],
        }),
      },
        h("img", { src: `/api/v1/files/${img.id}/content`, alt: img.display_name, style: "max-width: 100%; height: 90px; object-fit: cover;" }),
        h("div", { class: "text-xs text-truncate", title: img.display_name }, img.display_name)
      )));
    } else {
      mount(imgGrid, h("p", { class: "text-muted text-sm" }, t("radiology.detail.no_images")));
    }

    const pdfBtn = isFinal ? h("a", {
      class: "btn btn-sm btn-secondary",
      href: `/api/v1/radiology/studies/${s.id}/report?format=pdf`,
      target: "_blank",
    }, icon("download"), t("core.print")) : null;

    mount(body,
      h("div", { class: "stack gap-md" },
        h("div", { class: "row-between" },
          h("div", { class: "row gap-sm" }, radStatusPill(s.status), radPriorityPill(s.priority)),
          pdfBtn
        ),
        h("div", { class: "card card-body" },
          h("dl", { class: "grid-2col" },
            h("dt", t("radiology.col.patient")), h("dd", s.patient?.full_name || s.patient?.name || `Patient #${s.patient_id}`),
            h("dt", t("radiology.col.exam")), h("dd", `${t(`radiology.exam.${s.exam_type}`, s.exam_type)} ${s.body_region ? `(${s.body_region})` : ""}`),
            h("dt", t("radiology.detail.requesting_clinic")), h("dd", s.requesting_clinic?.name || "—"),
            h("dt", t("radiology.detail.requested_at")), h("dd", formatDateTime(s.requested_at)),
            s.scheduled_at ? [h("dt", t("radiology.detail.scheduled_at")), h("dd", formatDateTime(s.scheduled_at))] : null,
            s.clinical_question ? [h("dt", t("radiology.detail.question")), h("dd", { class: "span-2" }, s.clinical_question)] : null
          )
        ),
        isFinal ? h("div", { class: "card card-body" },
          h("h3", t("radiology.detail.report")),
          h("div", { class: "mt-sm" },
            h("strong", t("radiology.detail.findings")),
            h("p", { class: "mt-xs pre-wrap" }, s.findings || "—")
          ),
          h("div", { class: "mt-sm" },
            h("strong", t("radiology.detail.impression")),
            h("p", { class: "mt-xs pre-wrap" }, s.impression || "—")
          ),
          h("div", { class: "text-xs text-muted mt-md" },
            t("radiology.detail.finalized_by"), ": ", s.radiologist?.name || "—", " · ", formatDateTime(s.finalized_at)
          )
        ) : h("div", { class: "card card-body text-muted" }, t("radiology.detail.pending")),
        h("div", { class: "card card-body" },
          h("h3", t("radiology.detail.images")),
          imgGrid
        )
      )
    );
  }

  load();
  return drawer;
}

export function radiologyResultsPanel({ patientId, patient, clinicId, departmentId, allowRequest = true } = {}) {
  const table = dataTable({
    columns: [
      { key: "requested_at", label: t("radiology.col.requested"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.requested_at)) },
      { key: "exam", label: t("radiology.col.exam"), render: (r) => `${t(`radiology.exam.${r.exam_type}`, r.exam_type)} ${r.body_region ? `(${r.body_region})` : ""}` },
      { key: "status", label: t("radiology.col.status"), render: (r) => h("span", { class: "row gap-xs" }, radStatusPill(r.status), radPriorityPill(r.priority)) },
      { key: "from", label: t("radiology.col.from"), render: (r) => r.requesting_clinic?.name || "" },
    ],
    perPage: 10,
    fetch: (q) => api.get(`/radiology/patients/${patientId}/studies`, { query: q, cache: true }),
    onRowClick: (r) => openRadiologyStudyDrawer(r.id, { onChanged: () => table.reload() }),
    toolbar: allowRequest && can("radiology.request") ? [
      h("button", {
        class: "btn btn-sm btn-primary",
        type: "button",
        onClick: () => openRadiologyRequestDialog({ patient, patientId, clinicId, departmentId, onCreated: () => table.reload() }),
      }, icon("plus"), t("radiology.action.new_request"))
    ] : null,
    empty: { icon: "image", title: t("radiology.detail.no_images") },
  });
  return { el: table.el, reload: table.reload };
}
