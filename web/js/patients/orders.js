// Integrated Laboratory & Radiology Orders from Clinical Visits (spec §40, §41)
import { api, h, t, mount, icon, can, toast, toastApiError, openModal, createForm,
  formatDateTime, loadingState, errorState, emptyState } from "../core/index.js";

/**
 * Renders the Orders & Investigations panel for a specific visit.
 * @param {object} options
 * @param {object} options.ctx App context
 * @param {object} options.patient Patient object
 * @param {object} options.visit Visit object
 * @param {boolean} [options.compact] Whether to show compact view for drawers
 * @param {function} [options.onUpdated] Callback when orders change
 */
export function ordersPanel({ ctx, patient, visit, compact = false, onUpdated } = {}) {
  const root = h("div", { class: "orders-panel stack gap-sm" }, loadingState());

  async function load() {
    mount(root, loadingState());
    try {
      const data = await api.get(`/visits/${visit.id}/orders`);
      render(data);
    } catch (e) {
      mount(root, errorState(e, load));
    }
  }

  function render(data) {
    const labs = data.lab_requests || [];
    const rads = data.radiology_studies || [];

    const actions = h("div", { class: "row gap-xs no-print" },
      can("lab.request") ? h("button", {
        class: "btn btn-sm btn-primary",
        type: "button",
        onClick: () => openOrderLabModal({ ctx, patient, visit, onSaved: () => { load(); onUpdated?.(); } })
      }, icon("plus"), t("patients.orders.order_lab", { default: "Order Lab Tests" })) : null,
      can("radiology.request") ? h("button", {
        class: "btn btn-sm",
        type: "button",
        onClick: () => openOrderRadModal({ ctx, patient, visit, onSaved: () => { load(); onUpdated?.(); } })
      }, icon("plus"), t("patients.orders.order_rad", { default: "Order Radiology Scan" })) : null
    );

    if (!labs.length && !rads.length) {
      mount(root,
        h("div", { class: "row-between" },
          h("h4", { class: "m-0 text-sm font-semibold" }, t("patients.orders.title", { default: "Diagnostic Orders" })),
          actions),
        emptyState({
          icon: "activity",
          title: t("patients.orders.none", { default: "No investigations ordered for this visit" }),
          compact: true
        })
      );
      return;
    }

    const items = [];

    // Laboratory section
    if (labs.length) {
      items.push(h("div", { class: "orders-subhead text-xs font-semibold text-muted uppercase tracking-wide" },
        t("patients.orders.lab_requests", { default: "Laboratory Requests" })));
      labs.forEach((lr) => {
        const tests = (lr.items || []).map((x) => x.test_name).join(", ") || t("laboratory.tests", { default: "Tests" });
        items.push(h("div", { class: "order-item-card" },
          h("div", { class: "order-item-main" },
            h("div", { class: "row gap-xs align-center" },
              h("strong", { class: "order-item-title" }, tests),
              priorityBadge(lr.priority),
              statusBadge(lr.status)),
            lr.clinical_notes ? h("div", { class: "order-item-sub" }, lr.clinical_notes) : null,
            h("div", { class: "order-item-sub text-muted" },
              `${t("patients.referrals.from")}: ${lr.author_name || "—"} · ${formatDateTime(lr.requested_at)}`)),
          lr.status === "finalized" || lr.status === "completed" ? h("a", {
            class: "btn btn-sm btn-ghost",
            href: `#/d/${lr.lab_department_id}/lab/requests/${lr.id}`,
            target: "_blank"
          }, icon("fileText"), t("laboratory.action.view_report", { default: "Report" })) : null
        ));
      });
    }

    // Radiology section
    if (rads.length) {
      items.push(h("div", { class: "orders-subhead text-xs font-semibold text-muted uppercase tracking-wide mt-sm" },
        t("patients.orders.rad_studies", { default: "Radiology Studies" })));
      rads.forEach((rs) => {
        items.push(h("div", { class: "order-item-card" },
          h("div", { class: "order-item-main" },
            h("div", { class: "row gap-xs align-center" },
              h("strong", { class: "order-item-title" }, `${(rs.exam_type || "").toUpperCase()} ${rs.body_region ? `— ${rs.body_region}` : ""}`),
              priorityBadge(rs.priority),
              statusBadge(rs.status)),
            rs.clinical_question ? h("div", { class: "order-item-sub" }, rs.clinical_question) : null,
            h("div", { class: "order-item-sub text-muted" },
              `${t("patients.referrals.from")}: ${rs.author_name || "—"} · ${formatDateTime(rs.requested_at)}`)),
          rs.status === "reported" || rs.status === "completed" ? h("a", {
            class: "btn btn-sm btn-ghost",
            href: `#/d/${rs.radiology_department_id}/radiology/studies/${rs.id}`,
            target: "_blank"
          }, icon("fileText"), t("radiology.action.view_report", { default: "Report" })) : null
        ));
      });
    }

    mount(root,
      h("div", { class: "row-between mb-xs" },
        h("h4", { class: "m-0 text-sm font-semibold" }, t("patients.orders.title", { default: "Diagnostic Orders" })),
        actions),
      h("div", { class: "orders-list" }, items)
    );
  }

  load();
  return root;
}

function priorityBadge(p) {
  if (!p || p === "routine") return null;
  const isStat = p === "stat";
  return h("span", {
    class: `pill pill--${isStat ? "danger" : "warning"} text-xs`,
    title: t(`patients.referrals.urgency.${p}`, { default: p })
  }, icon(isStat ? "alert" : "activity"), t(`patients.referrals.urgency.${p}`, { default: p }));
}

function statusBadge(s) {
  const map = {
    requested: "warning",
    in_progress: "info",
    completed: "success",
    finalized: "success",
    reported: "success",
    cancelled: "muted"
  };
  const variant = map[s] || "muted";
  return h("span", { class: `pill pill--${variant} text-xs` }, s);
}

/**
 * Open modal dialog to order laboratory tests linked to the visit.
 */
export async function openOrderLabModal({ ctx, patient, visit, onSaved } = {}) {
  let tests = [];
  try {
    const res = await api.get("/lab/tests", { query: { is_active: true } });
    tests = res.items || res || [];
  } catch {
    // If center has no lab catalog yet, notify user
    return toast(t("laboratory.no_tests_available", { default: "No active laboratory tests found in catalog." }), { type: "warning" });
  }

  const selectedTestIds = new Set();
  const searchInput = h("input", {
    class: "input mb-sm",
    type: "search",
    placeholder: t("laboratory.search_tests", { default: "Search lab tests…" })
  });

  const testListContainer = h("div", {
    class: "test-picker-list",
    style: "max-height: 220px; overflow-y: auto; border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 8px;"
  });

  function renderTestCheckboxes(filter = "") {
    testListContainer.innerHTML = "";
    const needle = filter.toLowerCase().trim();
    const filtered = tests.filter((t) => !needle || t.name.toLowerCase().includes(needle) || (t.code && t.code.toLowerCase().includes(needle)));

    if (!filtered.length) {
      testListContainer.append(h("div", { class: "text-muted text-xs p-xs text-center" }, t("laboratory.no_matching_tests", { default: "No tests found" })));
      return;
    }

    filtered.forEach((test) => {
      const cb = h("input", {
        type: "checkbox",
        value: test.id,
        checked: selectedTestIds.has(test.id),
        onChange: (e) => {
          if (e.target.checked) selectedTestIds.add(test.id);
          else selectedTestIds.delete(test.id);
        }
      });
      const lbl = h("label", { class: "row gap-xs align-center text-sm py-xxs", style: "cursor: pointer;" },
        cb,
        h("span", { class: "font-medium" }, test.name),
        test.code ? h("span", { class: "text-muted text-xs ltr" }, `(${test.code})`) : null
      );
      testListContainer.append(lbl);
    });
  }

  searchInput.addEventListener("input", (e) => renderTestCheckboxes(e.target.value));
  renderTestCheckboxes();

  const form = createForm({
    fields: [
      { name: "priority", label: t("patients.referrals.urgency", { default: "Urgency / Priority" }), type: "select",
        options: [
          { value: "routine", label: t("patients.referrals.urgency.routine", { default: "Routine" }) },
          { value: "urgent", label: t("patients.referrals.urgency.urgent", { default: "Urgent" }) },
          { value: "stat", label: t("patients.referrals.urgency.stat", { default: "Emergency / STAT" }) },
        ],
        required: true,
        empty: false
      },
      { name: "clinical_notes", label: t("patients.visit.notes", { default: "Clinical Notes / Reason" }), type: "textarea", span: 2 }
    ],
    values: { priority: "routine" },
    submitLabel: t("patients.orders.order_lab", { default: "Submit Lab Request" }),
    onSubmit: async (vals) => {
      if (!selectedTestIds.size) {
        return toast(t("laboratory.select_at_least_one", { default: "Please select at least one test" }), { type: "warning" });
      }
      try {
        await api.post("/lab/requests", {
          patient_id: patient.id,
          visit_id: visit.id,
          requesting_clinic_id: visit.clinic_id,
          test_ids: Array.from(selectedTestIds),
          priority: vals.priority,
          clinical_notes: vals.clinical_notes || null
        });
        toast(t("laboratory.request_created", { default: "Lab request submitted successfully" }), { type: "success" });
        modal.close();
        onSaved?.();
      } catch (err) {
        toastApiError(err);
      }
    }
  });

  const modalBody = h("div", { class: "stack gap-sm" },
    h("div", { class: "field" },
      h("label", { class: "label" }, t("laboratory.tests", { default: "Select Tests" })),
      searchInput,
      testListContainer),
    form.el
  );

  const modal = openModal({
    title: `${t("patients.orders.order_lab", { default: "Order Lab Tests" })} — ${patient.full_name}`,
    size: "md",
    body: modalBody
  });
}

/**
 * Open modal dialog to order radiology imaging study linked to the visit.
 */
export function openOrderRadModal({ ctx, patient, visit, onSaved } = {}) {
  const form = createForm({
    fields: [
      { name: "exam_type", label: t("radiology.field.exam_type", { default: "Exam Type" }), type: "select",
        options: [
          { value: "xray", label: "X-Ray" },
          { value: "ultrasound", label: "Ultrasound" },
          { value: "ct", label: "CT Scan" },
          { value: "mri", label: "MRI" },
          { value: "mammography", label: "Mammography" },
          { value: "dexa", label: "DEXA" },
          { value: "other", label: "Other" },
        ],
        required: true,
        empty: false
      },
      { name: "body_region", label: t("radiology.field.body_region", { default: "Body Region / Anatomical Site" }),
        placeholder: "e.g. Chest PA, Left Knee, Brain",
        required: true,
        maxLength: 150
      },
      { name: "priority", label: t("patients.referrals.urgency", { default: "Urgency / Priority" }), type: "select",
        options: [
          { value: "routine", label: t("patients.referrals.urgency.routine", { default: "Routine" }) },
          { value: "urgent", label: t("patients.referrals.urgency.urgent", { default: "Urgent" }) },
          { value: "stat", label: t("patients.referrals.urgency.stat", { default: "Emergency / STAT" }) },
        ],
        required: true,
        empty: false
      },
      { name: "clinical_question", label: t("radiology.field.clinical_question", { default: "Clinical Question / Indication" }),
        type: "textarea",
        placeholder: "e.g. Rule out fracture, evaluate persistent cough",
        span: 2,
        required: true
      }
    ],
    values: { exam_type: "xray", priority: "routine" },
    submitLabel: t("patients.orders.order_rad", { default: "Submit Radiology Request" }),
    onSubmit: async (vals) => {
      try {
        await api.post("/radiology/studies", {
          patient_id: patient.id,
          visit_id: visit.id,
          requesting_clinic_id: visit.clinic_id,
          exam_type: vals.exam_type,
          body_region: vals.body_region,
          clinical_question: vals.clinical_question,
          priority: vals.priority
        });
        toast(t("radiology.study_requested", { default: "Radiology study requested successfully" }), { type: "success" });
        modal.close();
        onSaved?.();
      } catch (err) {
        toastApiError(err);
      }
    }
  });

  const modal = openModal({
    title: `${t("patients.orders.order_rad", { default: "Order Radiology Scan" })} — ${patient.full_name}`,
    size: "md",
    body: form.el
  });
}
