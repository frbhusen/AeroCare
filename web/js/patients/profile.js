// Patient profile: header, departments-with-records indicator, general info (edit), visits timeline,
// prescriptions, files, + tabs registered by other modules (hooks.js).
import { api, h, t, mount, icon, can, toast, createForm, openModal, confirmDialog, deleteWithUndo, tabs,
  navigate, areaHref, formatDateTime, loadingState, errorState, offlineCopyBanner } from "../core/index.js";
import { conflictOr } from "./util.js";
import { patientHeader, patientHref } from "./header.js";
import { loadMeta, profileFields } from "./meta.js";
import { patientTabsFor } from "./hooks.js";
import { visitsTimeline } from "./visits.js";
import { prescriptionsPanel } from "./prescriptions.js";
import { filesPanel } from "../files/panel.js";

export async function renderPatientProfile(ctx) {
  const id = ctx.params.id;
  const root = h("div", { class: "page pat-profile" }, loadingState());
  let patient;

  async function load(activeTab) {
    try {
      patient = await api.get(`/patients/${encodeURIComponent(id)}`, { cache: true });
    } catch (e) {
      if (e.status === 404 || e.status === 403) throw e;
      mount(root, errorState(e, () => load()));
      return;
    }
    ctx.setTitle(patient.full_name);
    render(activeTab);
  }

  function render(activeTab) {
    const actions = [
      h("a", { class: "btn", href: patientHref(ctx, patient.id, "summary") }, icon("clipboard"), t("patients.summary.open")),
      can("patients.edit") ? h("button", { class: "btn", type: "button", onClick: openEdit }, icon("edit"), t("core.edit")) : null,
      can("patients.delete") ? h("button", { class: "btn btn-ghost", type: "button", "aria-label": t("core.delete"),
        title: t("core.delete"), onClick: remove }, icon("trash")) : null,
    ].filter(Boolean);
    const items = [
      { key: "overview", label: t("patients.tab.overview"), render: (el) => mount(el, overview()) },
      can("medical_records.view") ? { key: "visits", label: t("patients.tab.visits"),
        render: (el) => mount(el, visitsTimeline({ ctx, patient })) } : null,
      ...patientTabsFor(ctx).map((tb) => ({ key: tb.key, label: t(tb.label),
        render: (el) => tb.render(el, { patient, ctx, reload: () => load(tb.key) }) })),
      can("medical_records.view") ? { key: "prescriptions", label: t("patients.tab.prescriptions"),
        render: (el) => mount(el, prescriptionsPanel({ ctx, patient })) } : null,
      can("files.view") ? { key: "files", label: t("patients.tab.files"),
        render: (el) => mount(el, filesPanel({ ctx, patient })) } : null,
    ].filter(Boolean);
    const tabKey = items.some((x) => x.key === (activeTab || ctx.query.tab)) ? (activeTab || ctx.query.tab) : undefined;
    mount(root,
      h("div", { class: "page-header no-print" },
        h("a", { class: "btn btn-link", href: areaHref(ctx, "patients") }, icon("arrowLeft", "flip-rtl"), t("patients.back_to_list"))),
      offlineCopyBanner(patient),
      patientHeader(patient, { ctx, actions }),
      departmentsIndicator(patient.departments),
      tabs(items, { active: tabKey }).el);
  }

  function overview() {
    const p = patient;
    const row = (k, v, cls) => [h("dt", t(`patients.field.${k}`)), h("dd", { class: cls }, v || h("span", { class: "text-muted" }, "—"))];
    return h("div", { class: "grid-2" },
      h("section", { class: "card" }, h("div", { class: "card-header" }, h("h2", t("patients.general_info"))),
        h("div", { class: "card-body" }, h("dl", { class: "kv" },
          row("full_name", p.full_name), row("phone", p.phone, "ltr"), row("address", p.address),
          row("blood_type", p.blood_type, "ltr"), row("allergies", p.allergies), row("chronic_conditions", p.chronic_conditions),
          row("medications", p.medications), row("general_notes", p.general_notes),
          row("created_at", formatDateTime(p.created_at))))),
      h("section", { class: "card" }, h("div", { class: "card-header" }, h("h2", t("patients.departments.title"))),
        h("div", { class: "card-body" }, departmentsDetail(p.departments))));
  }

  async function openEdit() {
    let meta;
    try { meta = await loadMeta(); } catch (e) { return toast(e.message, { type: "error" }); }
    const fields = [
      { name: "full_name", label: t("patients.field.full_name"), required: true, maxLength: 200, span: 2 },
      { name: "phone", label: t("patients.field.phone"), type: "tel", maxLength: 40, attrs: { dir: "ltr" } },
      ...profileFields(meta),
    ];
    const values = { ...patient };
    const form = createForm({
      fields, values, onCancel: () => modal.close(),
      onSubmit: async (v) => {
        try {
          const res = await api.patch(`/patients/${patient.id}`, { ...v, version: patient.version },
            { offline: true, label: t("patients.edit") });
          modal.close();
          if (res?.queued) return toast(t("patients.saved_offline"), { type: "warning" });
          toast(t("core.saved"), { type: "success" });
          patient = res;
          render("overview");
        } catch (err) {
          conflictOr(form, err, async () => { modal.close(); await load("overview"); openEdit(); });
        }
      },
    });
    const modal = openModal({ title: t("patients.edit"), size: "lg", body: form.el });
  }

  async function remove() {
    const ok = await confirmDialog({ danger: true, title: t("patients.delete.title"),
      message: t("patients.delete.message", { name: patient.full_name }), confirmLabel: t("core.delete") });
    if (!ok) return;
    try {
      await deleteWithUndo(`/patients/${patient.id}`, {
        message: t("patients.delete.done"),
        onDone: () => navigate(areaHref(ctx, "patients")),
        onUndone: () => navigate(patientHref(ctx, patient.id)),
      });
    } catch { /* toast shown */ }
  }

  await load();
  return root;
}

/** Chips: ✓ accessible departments, 🔒 restricted ones (no details). */
export function departmentsIndicator(depts = []) {
  if (!depts.length) return null;
  return h("div", { class: "pat-depts row", "aria-label": t("patients.departments.title") },
    h("span", { class: "text-sm text-muted" }, t("patients.departments.with_records")),
    depts.map((d) => h("span", { class: ["pat-dept", d.accessible ? "is-open" : "is-locked"], style: d.color ? { "--dc": d.color } : null,
      title: d.accessible ? t("patients.departments.accessible") : t("patients.departments.restricted") },
    d.accessible ? icon("check") : h("span", { "aria-hidden": "true" }, "🔒"), d.name,
    d.accessible ? null : h("span", { class: "sr-only" }, t("patients.departments.restricted")))));
}

export function departmentsDetail(depts = []) {
  if (!depts.length) return h("p", { class: "text-muted" }, t("patients.departments.none"));
  return h("ul", { class: "pat-dept-list" }, depts.map((d) => h("li", { class: d.accessible ? "is-open" : "is-locked" },
    h("div", { class: "row-between" },
      h("strong", d.accessible ? "✓ " : "🔒 ", d.name),
      d.accessible ? h("span", { class: "badge" }, t("patients.visits_count", { count: d.visit_count ?? 0 }))
        : h("span", { class: "pill pill--neutral" }, t("patients.departments.restricted"))),
    d.accessible && d.clinics?.length ? h("div", { class: "text-sm text-muted" },
      d.clinics.map((c) => `${c.name} (${c.visit_count})`).join(" · ")) : null)));
}
