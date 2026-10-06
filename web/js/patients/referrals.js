// Internal Referrals & Cross-Department Consultations (spec §44)
import { api, h, t, mount, icon, can, toast, toastApiError, openModal, createForm, confirmDialog,
  formatDateTime, loadingState, errorState, emptyState, getDepartments, clinicsOf } from "../core/index.js";

/**
 * Renders the Internal Referrals panel for a patient.
 * @param {object} options
 * @param {object} options.ctx App context
 * @param {object} options.patient Patient object
 * @param {object} [options.visit] Optional linked visit
 * @param {boolean} [options.compact]
 * @param {function} [options.onUpdated]
 */
export function referralsPanel({ ctx, patient, visit, compact = false, onUpdated } = {}) {
  const root = h("div", { class: "referrals-panel stack gap-sm" }, loadingState());

  async function load() {
    mount(root, loadingState());
    try {
      const data = await api.get(`/patients/${patient.id}/referrals`);
      render(data.items || data || []);
    } catch (e) {
      mount(root, errorState(e, load));
    }
  }

  function render(items) {
    const actions = h("div", { class: "row gap-xs no-print" },
      can("medical_records.create") || can("medical_records.edit") ? h("button", {
        class: "btn btn-sm btn-primary",
        type: "button",
        onClick: () => openNewReferralModal({ ctx, patient, visit, onSaved: () => { load(); onUpdated?.(); } })
      }, icon("send"), t("patients.referrals.new", { default: "Refer Patient" })) : null
    );

    if (!items.length) {
      mount(root,
        h("div", { class: "row-between" },
          h("h4", { class: "m-0 text-sm font-semibold" }, t("patients.referrals.title", { default: "Internal Referrals & Consults" })),
          actions),
        emptyState({
          icon: "send",
          title: t("patients.referrals.none", { default: "No internal referrals recorded for this patient" }),
          compact: true
        })
      );
      return;
    }

    const cards = items.map((ref) => {
      // Referrals of other departments are shown as "exists" only; the server hides their reason and
      // rejects actions on them, so no buttons either.
      const canManage = can("medical_records.edit") && !ref.restricted;
      const isPending = ref.status === "pending";
      const isAccepted = ref.status === "accepted";

      const statusActions = [];
      if (canManage && isPending) {
        statusActions.push(h("button", {
          class: "btn btn-xs btn-outline",
          type: "button",
          onClick: () => changeStatus(ref.id, "accepted", ref.version)
        }, icon("check"), t("patients.referrals.accept", { default: "Accept" })));
      }
      if (canManage && (isPending || isAccepted)) {
        statusActions.push(h("button", {
          class: "btn btn-xs btn-primary",
          type: "button",
          onClick: () => changeStatus(ref.id, "completed", ref.version)
        }, icon("check"), t("patients.referrals.complete", { default: "Complete" })));
        statusActions.push(h("button", {
          class: "btn btn-xs btn-ghost text-danger",
          type: "button",
          onClick: () => changeStatus(ref.id, "cancelled", ref.version)
        }, icon("x"), t("patients.referrals.cancel", { default: "Cancel" })));
      }

      return h("div", { class: "referral-card" },
        h("div", { class: "referral-header" },
          h("div", { class: "referral-route" },
            icon("send"),
            h("span", `${ref.from_department_name || "—"}`),
            h("span", { class: "text-muted" }, "➔"),
            h("strong", `${ref.to_department_name}${ref.to_clinic_name ? ` (${ref.to_clinic_name})` : ""}`)
          ),
          h("div", { class: "row gap-xs align-center" },
            urgencyBadge(ref.urgency),
            refStatusBadge(ref.status))
        ),
        ref.restricted
          ? h("div", { class: "referral-reason text-muted" }, icon("lock"), " ",
            t("patients.referrals.restricted", { default: "Details are restricted to the departments involved." }))
          : h("div", { class: "referral-reason" },
            h("strong", t("patients.referrals.reason", { default: "Reason:" }), " "),
            h("span", ref.reason)),
        ref.clinical_notes ? h("div", { class: "referral-notes" }, ref.clinical_notes) : null,
        h("div", { class: "row-between align-center mt-xs text-xs text-muted" },
          h("span", `${t("patients.referrals.from")}: ${ref.referrer_name || "—"} · ${formatDateTime(ref.created_at)}`),
          statusActions.length ? h("div", { class: "row gap-xs" }, statusActions) : null)
      );
    });

    mount(root,
      h("div", { class: "row-between mb-xs" },
        h("h4", { class: "m-0 text-sm font-semibold" }, t("patients.referrals.title", { default: "Internal Referrals & Consults" })),
        actions),
      h("div", { class: "referrals-list" }, cards)
    );
  }

  async function changeStatus(refId, newStatus, version) {
    try {
      await api.post(`/referrals/${refId}/status`, { status: newStatus, version });
      toast(t("core.saved", { default: "Status updated" }), { type: "success" });
      load();
      onUpdated?.();
    } catch (e) {
      toastApiError(e);
    }
  }

  load();
  return root;
}

function urgencyBadge(u) {
  if (!u || u === "routine") return null;
  const isStat = u === "stat";
  return h("span", {
    class: `pill pill--${isStat ? "danger" : "warning"} text-xs`,
    title: t(`patients.referrals.urgency.${u}`, { default: u })
  }, icon(isStat ? "alert" : "activity"), t(`patients.referrals.urgency.${u}`, { default: u }));
}

function refStatusBadge(s) {
  const map = {
    pending: "warning",
    accepted: "info",
    completed: "success",
    cancelled: "muted"
  };
  const variant = map[s] || "muted";
  return h("span", { class: `pill pill--${variant} text-xs` }, t(`patients.referrals.status.${s}`, { default: s }));
}

/**
 * Open modal to create a new internal referral for the patient.
 */
export function openNewReferralModal({ ctx, patient, visit, onSaved } = {}) {
  const depts = (getDepartments() || []).filter((d) => d.id !== ctx.dept?.id);

  if (!depts.length) {
    return toast(t("patients.referrals.no_other_departments", { default: "No other departments found to refer to." }), { type: "warning" });
  }

  const deptOptions = depts.map((d) => ({ value: d.id, label: d.name }));
  let clinicOptions = [{ value: "", label: t("patients.all_clinics", { default: "Any Clinic" }) }];

  const form = createForm({
    fields: [
      { name: "to_department_id", label: t("patients.referrals.to_dept", { default: "Target Department" }), type: "select",
        options: deptOptions, required: true, empty: false },
      { name: "urgency", label: t("patients.referrals.urgency", { default: "Urgency" }), type: "select",
        options: [
          { value: "routine", label: t("patients.referrals.urgency.routine", { default: "Routine" }) },
          { value: "urgent", label: t("patients.referrals.urgency.urgent", { default: "Urgent" }) },
          { value: "stat", label: t("patients.referrals.urgency.stat", { default: "Emergency / STAT" }) },
        ],
        required: true, empty: false },
      { name: "reason", label: t("patients.referrals.reason", { default: "Clinical Reason for Consultation" }),
        placeholder: "e.g. Comprehensive dermatological evaluation of persistent rash",
        maxLength: 300, span: 2, required: true },
      { name: "clinical_notes", label: t("patients.visit.notes", { default: "Clinical Summary & Notes" }),
        type: "textarea", span: 2 }
    ],
    values: { to_department_id: deptOptions[0]?.value, urgency: "routine" },
    submitLabel: t("patients.referrals.new", { default: "Send Referral" }),
    onSubmit: async (vals) => {
      try {
        await api.post(`/patients/${patient.id}/referrals`, {
          patient_id: patient.id,
          to_department_id: Number(vals.to_department_id),
          visit_id: visit?.id || null,
          urgency: vals.urgency,
          reason: vals.reason,
          clinical_notes: vals.clinical_notes || null
        });
        toast(t("patients.referrals.created", { default: "Referral submitted successfully" }), { type: "success" });
        modal.close();
        onSaved?.();
      } catch (err) {
        toastApiError(err);
      }
    }
  });

  const modal = openModal({
    title: `${t("patients.referrals.new", { default: "Refer Patient" })} — ${patient.full_name}`,
    size: "md",
    body: form.el
  });
}
