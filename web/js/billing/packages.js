// Treatment Packages & Installment Payment Plans (spec §48)
import { api, h, t, mount, icon, can, toast, toastApiError, openModal, createForm, confirmDialog,
  formatDate, formatDateTime, formatMoney, loadingState, errorState, emptyState, getDepartments, clinicsOf } from "../core/index.js";

/**
 * Packages & Installments panel for a patient profile.
 * @param {object} options
 * @param {object} options.ctx App context
 * @param {object} options.patient Patient object
 * @param {function} [options.onUpdated] Callback when package data changes
 */
export function packagesPanel({ ctx, patient, onUpdated } = {}) {
  const root = h("div", { class: "packages-panel stack gap-md" }, loadingState());

  async function load() {
    mount(root, loadingState());
    try {
      const res = await api.get("/billing/packages", { query: { patient_id: patient.id } });
      render(res.items || res || []);
    } catch (e) {
      mount(root, errorState(e, load));
    }
  }

  function render(packages) {
    const actions = h("div", { class: "row gap-xs no-print" },
      can("billing.create") ? h("button", {
        class: "btn btn-sm btn-primary",
        type: "button",
        onClick: () => openNewPackageModal({ ctx, patient, onSaved: () => { load(); onUpdated?.(); } })
      }, icon("plus"), t("billing.packages.new", { default: "New Package / Plan" })) : null
    );

    if (!packages.length) {
      mount(root,
        h("div", { class: "row-between" },
          h("h3", { class: "m-0 font-semibold" }, t("billing.packages.title", { default: "Treatment Packages & Installments" })),
          actions),
        emptyState({
          icon: "package",
          title: t("billing.packages.empty", { default: "No treatment packages or installment plans recorded." }),
          compact: true
        })
      );
      return;
    }

    const cards = packages.map((pkg) => {
      const total = Number(pkg.total_sessions || 0);
      const used = Number(pkg.used_sessions || 0);
      const remaining = Math.max(0, total - used);
      const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
      const canEdit = can("billing.edit");
      const isActive = pkg.status === "active";

      // Session pills representation
      const pills = [];
      for (let i = 1; i <= Math.min(total, 30); i++) {
        pills.push(h("div", { class: `pkg-session-pill ${i <= used ? "used" : ""}` },
          i <= used ? icon("check") : String(i)));
      }

      // Installments table
      const instList = pkg.installments || [];
      const instRows = instList.map((inst, idx) => {
        const isPaid = inst.status === "paid";
        const dueDate = inst.due_date ? formatDate(inst.due_date) : "—";
        const paidDate = inst.paid_date ? formatDate(inst.paid_date) : "—";
        return h("tr",
          h("td", `${t("billing.packages.installment_num", { num: idx + 1, default: `Installment #${idx + 1}` })}`),
          h("td", { class: "ltr" }, dueDate),
          h("td", { class: "num ltr font-semibold" }, formatMoney(inst.amount)),
          h("td", h("span", { class: `pill pill--${isPaid ? "success" : "warning"} text-xs` },
            isPaid ? t("billing.history.paid", { default: "Paid" }) : t("billing.remaining", { default: "Pending" }))),
          h("td", isPaid ? h("span", { class: "text-muted text-xs ltr" }, paidDate) : (
            canEdit ? h("button", {
              class: "btn btn-xs btn-outline",
              type: "button",
              onClick: () => markInstallmentPaid(pkg, idx)
            }, icon("check"), t("billing.packages.mark_paid", { default: "Mark Paid" })) : null
          ))
        );
      });

      return h("div", { class: "package-card" },
        h("div", { class: "row-between align-start" },
          h("div",
            h("h3", { class: "m-0 font-bold text-lg" }, pkg.name),
            h("div", { class: "text-sm text-muted mt-xxs" },
              `${pkg.department_name || ""}${pkg.clinic_name ? ` · ${pkg.clinic_name}` : ""}`)),
          h("div", { class: "row gap-xs align-center" },
            h("span", { class: `pill pill--${pkg.status === "completed" ? "success" : (isActive ? "info" : "muted")}` },
              pkg.status),
            isActive && remaining > 0 && canEdit ? h("button", {
              class: "btn btn-sm btn-primary",
              type: "button",
              onClick: () => recordSession(pkg)
            }, icon("check"), t("billing.packages.use_session", { default: "Use Session" })) : null
          )
        ),

        // Progress bar
        h("div", { class: "pkg-progress-wrap" },
          h("div", { class: "row-between text-sm mb-xxs" },
            h("span", { class: "font-medium" },
              t("billing.packages.sessions_progress", { used, total, default: `${used} of ${total} sessions used` })),
            h("span", { class: "text-muted" },
              t("billing.packages.sessions_left", { count: remaining, default: `${remaining} sessions remaining` }))
          ),
          h("div", { class: "pkg-progress-bar" },
            h("div", { class: "pkg-progress-fill", style: `width: ${pct}%;` })),
          pills.length ? h("div", { class: "pkg-session-pills" }, pills) : null
        ),

        // Financial totals strip
        h("div", { class: "grid-3 gap-sm my-sm p-sm", style: "background: var(--surface-2); border-radius: var(--radius-sm);" },
          h("div",
            h("div", { class: "text-xs text-muted" }, t("billing.total")),
            h("div", { class: "font-bold text-md ltr" }, formatMoney(pkg.total_price))),
          h("div",
            h("div", { class: "text-xs text-muted" }, t("billing.history.paid")),
            h("div", { class: "font-bold text-md text-success ltr" }, formatMoney(pkg.paid_amount || 0))),
          h("div",
            h("div", { class: "text-xs text-muted" }, t("billing.balance")),
            h("div", { class: "font-bold text-md text-danger ltr" }, formatMoney(pkg.balance || 0)))
        ),

        // Installments
        instList.length ? h("div", { class: "mt-sm" },
          h("h4", { class: "text-sm font-semibold mb-xs" }, t("billing.packages.installments", { default: "Installment Schedule" })),
          h("div", { class: "table-wrap" },
            h("table", { class: "table table-compact" },
              h("thead", h("tr",
                h("th", t("billing.packages.installment_num", { num: "#" })),
                h("th", t("billing.packages.due_date")),
                h("th", { class: "num" }, t("billing.detail.amount")),
                h("th", t("billing.detail.receipt_no")),
                h("th", t("billing.packages.paid_date")))),
              h("tbody", instRows)))
        ) : null,

        pkg.notes ? h("div", { class: "text-xs text-muted mt-sm" }, pkg.notes) : null
      );
    });

    mount(root,
      h("div", { class: "row-between mb-sm" },
        h("h3", { class: "m-0 font-semibold" }, t("billing.packages.title", { default: "Treatment Packages & Installments" })),
        actions),
      h("div", { class: "stack gap-md" }, cards)
    );
  }

  async function recordSession(pkg) {
    const ok = await confirmDialog({
      title: t("billing.packages.use_session_title", { default: "Record Completed Session" }),
      message: t("billing.packages.use_session_confirm", { default: `Record 1 completed session for "${pkg.name}"?` }),
      confirmLabel: t("billing.packages.use_session", { default: "Record Session" })
    });
    if (!ok) return;

    try {
      const res = await api.post(`/billing/packages/${pkg.id}/session`, { delta: 1 });
      toast(t("billing.packages.session_recorded", { default: "Session recorded successfully" }), { type: "success" });
      if (res.status === "completed") {
        toast(t("billing.packages.all_completed", { default: "All sessions completed for this package!" }), { type: "info" });
      }
      load();
      onUpdated?.();
    } catch (e) {
      toastApiError(e);
    }
  }

  async function markInstallmentPaid(pkg, instIndex) {
    const installments = JSON.parse(JSON.stringify(pkg.installments || []));
    if (!installments[instIndex]) return;

    installments[instIndex].status = "paid";
    installments[instIndex].paid_date = new Date().toISOString().slice(0, 10);

    try {
      await api.patch(`/billing/packages/${pkg.id}`, { installments });
      toast(t("billing.packages.installment_paid", { default: "Installment marked as paid" }), { type: "success" });
      load();
      onUpdated?.();
    } catch (e) {
      toastApiError(e);
    }
  }

  load();
  return root;
}

/**
 * Open modal to create a new treatment package and installment plan.
 */
export function openNewPackageModal({ ctx, patient, onSaved } = {}) {
  const depts = getDepartments() || [];
  const deptOptions = depts.map((d) => ({ value: d.id, label: d.name }));
  const initialDeptId = ctx.dept?.id || deptOptions[0]?.value;

  let currentClinics = initialDeptId ? clinicsOf(initialDeptId) : [];
  let clinicOptions = currentClinics.map((c) => ({ value: c.id, label: c.name }));

  const form = createForm({
    fields: [
      { name: "name", label: t("billing.packages.name", { default: "Package Name" }),
        placeholder: "e.g. Full Body Laser - 6 Sessions, Orthodontic Treatment Plan",
        required: true, maxLength: 200, span: 2 },
      { name: "department_id", label: t("billing.department"), type: "select",
        options: deptOptions, required: true, empty: false },
      { name: "clinic_id", label: t("billing.clinic"), type: "select",
        options: [{ value: "", label: t("patients.all_clinics") }, ...clinicOptions] },
      { name: "total_sessions", label: t("billing.packages.total_sessions", { default: "Total Sessions" }),
        type: "number", min: 1, max: 100, required: true },
      { name: "total_price", label: t("billing.total"), type: "money", required: true, min: "0.00" },
      { name: "split_count", label: t("billing.packages.split_count", { default: "Number of Installments" }),
        type: "select", empty: false,
        options: [
          { value: "1", label: "1 (Full Upfront)" },
          { value: "2", label: "2 Installments" },
          { value: "3", label: "3 Installments" },
          { value: "4", label: "4 Installments" },
          { value: "6", label: "6 Installments" },
          { value: "12", label: "12 Installments" },
        ]
      },
      { name: "notes", label: t("billing.notes"), type: "textarea", span: 2 }
    ],
    values: {
      department_id: initialDeptId,
      total_sessions: 6,
      total_price: "1000.00",
      split_count: "3"
    },
    submitLabel: t("billing.packages.new", { default: "Create Package" }),
    onSubmit: async (vals) => {
      const split = parseInt(vals.split_count || "1", 10);
      const totalAmount = parseFloat(vals.total_price || "0");
      const perInstallment = (totalAmount / split).toFixed(2);

      // Generate schedule
      const installments = [];
      const now = new Date();
      for (let i = 0; i < split; i++) {
        const d = new Date(now.getFullYear(), now.getMonth() + i, now.getDate());
        installments.push({
          due_date: d.toISOString().slice(0, 10),
          amount: perInstallment,
          status: i === 0 ? "paid" : "pending",
          paid_date: i === 0 ? now.toISOString().slice(0, 10) : null
        });
      }

      try {
        await api.post("/billing/packages", {
          patient_id: patient.id,
          name: vals.name,
          department_id: Number(vals.department_id),
          clinic_id: vals.clinic_id ? Number(vals.clinic_id) : null,
          total_sessions: Number(vals.total_sessions),
          total_price: vals.total_price,
          notes: vals.notes || null,
          installments
        });
        toast(t("billing.packages.created", { default: "Package created successfully" }), { type: "success" });
        modal.close();
        onSaved?.();
      } catch (err) {
        toastApiError(err);
      }
    }
  });

  const modal = openModal({
    title: `${t("billing.packages.new", { default: "New Package / Treatment Plan" })} — ${patient.full_name}`,
    size: "md",
    body: form.el
  });
}
