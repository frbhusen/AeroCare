// Extension points of the patient profile for other modules (see docs/modules/patients.md "UI").
//
//   import { registerPatientTab, registerVisitOpener } from "../patients/hooks.js";
//   registerPatientTab({ key: "dental", label: "dentistry.tab", env: ["dentistry"], order: 30, perm: "medical_records.view",
//                        render: (panelEl, { patient, ctx, reload }) => { ... } });
//   registerVisitOpener("dentistry", (ctx, visit) => "#/d/<id>/dentistry/visits/<visit.id>");   // href or null
//   registerVisitCreator("dentistry", (ctx, patient, { onDone }) => openMyNewVisitFlow(...));
//
// env: "*" or array of department environments; tabs with an env array are shown only inside a department of
// that environment (department area). Center area shows "*" tabs only.
import { allowed } from "../core/index.js";

const tabs = [];
const openers = new Map();
const creators = new Map();

export function registerPatientTab(tab) {
  const def = { order: 50, env: "*", ...tab };
  const i = tabs.findIndex((x) => x.key === def.key);
  if (i >= 0) tabs[i] = def;
  else tabs.push(def);
}

export function patientTabsFor(ctx) {
  const env = ctx.area === "department" ? ctx.dept?.environment : null;
  return tabs.filter((tb) => (tb.env === "*" || (env && tb.env.includes(env))) && allowed(tb.perm))
    .sort((a, b) => a.order - b.order);
}

/** fn(ctx, visit) -> href string, false when the environment opened its own view, or null to fall back
 * to the generic visit drawer. */
export function registerVisitOpener(environment, fn) {
  openers.set(environment, fn);
}

export function visitOpener(environment) {
  return openers.get(environment) || null;
}

/** fn(ctx, patient, {onDone}) opens the environment's own "new visit" flow (used inside that department). */
export function registerVisitCreator(environment, fn) {
  creators.set(environment, fn);
}

export function visitCreator(environment) {
  return creators.get(environment) || null;
}

const summaryRenderers = new Map();

/**
 * Render a Complete Patient Summary section produced by your backend provider:
 *   registerSummaryRenderer("dentistry", { title: "dentistry.summary.title", render: (data, ctx) => Node });
 * Sections without a renderer use a generic table/key-value fallback.
 */
export function registerSummaryRenderer(name, def) {
  summaryRenderers.set(name, def);
}

export function summaryRenderer(name) {
  return summaryRenderers.get(name) || null;
}
