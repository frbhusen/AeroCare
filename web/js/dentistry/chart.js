// Dental patient chart: header + tabs (odontogram, treatments, plans, X-rays, timeline, prescriptions).
import {
  api, h, t, icon, mount, tabs, navigate, deptHref, printButton, printView, loadingState, errorState,
  unavailableState, formatMoney,
} from "../core/index.js";
import { loadPatient, patientHeader, patientHref } from "../patients/header.js";
import { prescriptionsPanel } from "../patients/prescriptions.js";
import { deptClinics, dentUrl, loadMeta } from "./common.js";
import { renderOdontogram } from "./odontogram.js";
import { renderPlans, renderTreatments } from "./records.js";
import { renderXrays } from "./xrays.js";
import { renderTimeline } from "./timeline.js";

export const TABS = ["chart", "treatments", "plans", "xrays", "timeline", "prescriptions"];

export async function renderChartPage(ctx) {
  const patientId = Number(ctx.params.patientId);
  const [meta, patient] = await Promise.all([loadMeta(), loadPatient(patientId)]);
  ctx.setTitle(`${patient.full_name} · ${t("dentistry.chart.title")}`);
  const clinics = deptClinics(meta, ctx);
  if (!clinics.length) return h("div", { class: "page" }, unavailableState(t("dentistry.no_clinic")));
  const clinicId = Number(ctx.query.clinic) && clinics.some((c) => c.id === Number(ctx.query.clinic))
    ? Number(ctx.query.clinic) : clinics[0].id;
  const active = TABS.includes(ctx.query.tab) ? ctx.query.tab : "chart";
  const go = (q) => navigate(`d/${ctx.dept.id}/chart/${patientId}`, { replace: true, query: { clinic: clinicId, tab: active, ...q } });

  const clinicSel = clinics.length > 1 ? h("select", { class: "select", "aria-label": t("dentistry.clinic"),
    onChange: (e) => go({ clinic: e.target.value }) }, clinics.map((c) => h("option", { value: c.id }, c.name))) : null;
  if (clinicSel) clinicSel.value = String(clinicId);
  const summary = h("div", { class: "dent-summary row" });

  const opts = { patientId, clinicId, meta };
  let current = active;
  const tb = tabs([
    { key: "chart", label: t("dentistry.tab.chart"), render: (p) => renderOdontogram(p, opts) },
    { key: "treatments", label: t("dentistry.tab.treatments"), render: (p) => renderTreatments(p, opts) },
    { key: "plans", label: t("dentistry.tab.plans"), render: (p) => renderPlans(p, { ...opts, onConverted: loadSummary }) },
    { key: "xrays", label: t("dentistry.tab.xrays"), render: (p) => renderXrays(p, opts) },
    { key: "timeline", label: t("dentistry.tab.timeline"), render: (p) => renderTimeline(p, opts) },
    { key: "prescriptions", label: t("dentistry.tab.prescriptions"), render: (p) => mount(p, prescriptionsPanel({ ctx, patient })) },
  ], {
    active,
    onChange: (k) => {
      if (k === current) return;
      current = k;
      history.replaceState(null, "", `#/${`d/${ctx.dept.id}/chart/${patientId}`}?clinic=${clinicId}&tab=${k}`);
      loadSummary();
    },
  });

  async function loadSummary() {
    try {
      const s = await api.get(dentUrl(`/patients/${patientId}/summary`), { cache: true });
      if (s.available === false) return mount(summary);
      const by = s.treatments_by_status || {};
      mount(summary,
        stat(t("dentistry.summary.treatments"), s.treatments_total ?? 0),
        stat(t("dentistry.summary.in_progress"), (by["in-progress"] || 0) + (by.scheduled || 0)),
        stat(t("dentistry.summary.open_plans"), s.open_plan_items ?? 0),
        stat(t("dentistry.summary.xrays"), s.xrays ?? 0),
        stat(t("dentistry.summary.charted"), s.charted_teeth ?? 0));
    } catch {
      mount(summary);
    }
  }
  loadSummary();

  return h("div", { class: "page dent-page" },
    h("div", { class: "page-header no-print" },
      h("div", h("a", { class: "btn btn-link", href: deptHref(ctx.dept.id, "charts") }, icon("arrowLeft", "flip-rtl"), t("dentistry.charts.title"))),
      h("div", { class: "page-actions" },
        clinicSel,
        h("a", { class: "btn", href: patientHref(ctx, patientId) }, icon("user"), t("dentistry.profile")),
        printButton(() => printView()))),
    patientHeader(patient, { ctx }),
    h("div", { class: "print-only dent-print-meta" }, clinics.find((c) => c.id === clinicId)?.name || ""),
    summary,
    h("section", { class: "card dent-tabs" }, h("div", { class: "card-body" }, tb.el)));
}

function stat(label, value) {
  return h("div", { class: "stat dent-stat" }, h("span", { class: "stat-label" }, label), h("span", { class: "stat-value num" }, String(value)));
}

export { formatMoney, loadingState, errorState };
