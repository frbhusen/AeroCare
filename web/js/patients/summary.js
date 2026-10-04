// Complete Patient Summary (GET /patients/<id>/summary): access-scoped sections, printable (window.print()).
import { api, h, t, icon, formatDate, formatDateTime, formatBytes, statusPill, printButton, printView, apiUrl,
  getCenter } from "../core/index.js";
import { hasKey } from "../core/i18n.js";
import { patientHeader, patientHref } from "./header.js";
import { departmentsDetail } from "./profile.js";
import { rxItemsTable } from "./prescriptions.js";
import { summaryRenderer } from "./hooks.js";

const TITLES = { profile: "patients.general_info", departments: "patients.departments.title", visits: "patients.tab.visits",
  prescriptions: "patients.tab.prescriptions", files: "patients.tab.files", generic: "patients.summary.generic" };

export async function renderPatientSummary(ctx) {
  const res = await api.get(`/patients/${encodeURIComponent(ctx.params.id)}/summary`, { cache: true });
  const sections = res.sections || [];
  const profile = sections.find((s) => s.name === "profile")?.data;
  ctx.setTitle(t("patients.summary.title"));
  const center = getCenter();
  return h("div", { class: "page pat-summary" },
    h("div", { class: "page-header no-print" },
      h("a", { class: "btn btn-link", href: patientHref(ctx, ctx.params.id) }, icon("arrowLeft", "flip-rtl"), t("patients.back_to_profile")),
      h("div", { class: "page-actions" }, printButton(() => printView()))),
    h("div", { class: "print-only pat-print-head" }, h("strong", center?.name || ""), " — ", t("patients.summary.title"),
      h("div", { class: "text-xs" }, formatDateTime(new Date(), { year: "always" }))),
    h("h1", { class: "no-print" }, t("patients.summary.title")),
    h("p", { class: "text-sm text-muted" }, t("patients.summary.scope_note")),
    profile ? patientHeader(profile, { ctx }) : null,
    sections.map((s) => section(s, ctx)));
}

function section({ name, data }, ctx) {
  const custom = summaryRenderer(name);
  const titleKey = custom?.title || TITLES[name] || `${name}.summary.title`;
  let body;
  if (custom) body = custom.render(data, ctx);
  else if (name === "profile") body = profileBody(data);
  else if (name === "departments") body = departmentsDetail(data);
  else if (name === "visits") body = visitsBody(data);
  else if (name === "prescriptions") body = rxBody(data);
  else if (name === "files") body = filesBody(data);
  else if (name === "generic") body = genericBody(data);
  else body = fallback(data);
  return h("section", { class: "card pat-sum-section" },
    h("div", { class: "card-header" }, h("h2", hasKey(titleKey) ? t(titleKey) : (data?.title || name))),
    h("div", { class: "card-body" }, body));
}

const dash = (v) => (v == null || v === "" ? h("span", { class: "text-muted" }, "—") : v);

function profileBody(p) {
  const row = (k, v, cls) => [h("dt", t(`patients.field.${k}`)), h("dd", { class: cls }, dash(v))];
  return h("dl", { class: "kv" }, row("address", p.address), row("blood_type", p.blood_type, "ltr"), row("allergies", p.allergies),
    row("chronic_conditions", p.chronic_conditions), row("medications", p.medications), row("general_notes", p.general_notes));
}

function visitsBody(d) {
  if (!d.clinics?.length) return h("p", { class: "text-muted" }, t("patients.visit.none"));
  return h("div", { class: "stack" }, d.clinics.map((c) => h("div",
    h("h3", `${c.department_name} — ${c.clinic_name}`, " ", h("span", { class: "badge" }, t("patients.visits_count", { count: c.total }))),
    simpleTable([t("patients.visit.date"), t("patients.visit.type"), t("patients.visit.title"), t("patients.visit.author"), t("patients.visit.status")],
      c.visits.map((v) => [formatDateTime(v.visit_at, { year: "always" }), t(`patients.visit_type.${v.visit_type}`), v.title || "",
        v.author_name || "", statusPill(v.status, "patients.visit_status")])))),
  d.truncated ? h("p", { class: "text-sm text-muted" }, t("patients.summary.truncated")) : null);
}

function rxBody(d) {
  if (!d.items?.length) return h("p", { class: "text-muted" }, t("patients.rx.none"));
  return h("div", { class: "stack" }, d.items.map((rx) => h("div",
    h("div", { class: "row-between" }, h("strong", formatDateTime(rx.prescribed_at, { year: "always" }), " · ", rx.clinic_name || "",
      " · ", rx.author_name || ""), statusPill(rx.status, "patients.rx_status")),
    rxItemsTable(rx.items))));
}

function filesBody(d) {
  if (!d.items?.length) return h("p", { class: "text-muted" }, t("patients.files_none"));
  return simpleTable([t("patients.file.name"), t("patients.file.category"), t("patients.field.clinic"), t("patients.file.date"), t("patients.file.size")],
    d.items.map((f) => [h("a", { href: apiUrl(f.url), target: "_blank", rel: "noopener" }, f.display_name),
      t(`files.category.${f.category}`), f.clinic_name || "", formatDate(f.created_at, { year: "always" }), formatBytes(f.size_bytes)]));
}

function genericBody(d) {
  const vit = (v) => Object.entries(v || {}).map(([k, x]) => `${t(`generic.vital.${k}`)}: ${x}`).join(", ");
  return simpleTable([t("patients.visit.date"), t("patients.field.clinic"), t("generic.field.chief_complaint"), t("generic.field.diagnosis"),
    t("generic.field.treatment_plan"), t("generic.vitals")],
  d.items.map((r) => [formatDateTime(r.visit_at, { year: "always" }), r.clinic_name || "", r.chief_complaint || "", r.diagnosis || "",
    r.treatment_plan || "", vit(r.vitals)]));
}

/** Generic rendering for sections of modules that did not register a renderer. */
function fallback(data) {
  if (data == null) return null;
  if (Array.isArray(data) || Array.isArray(data.items)) {
    const items = Array.isArray(data) ? data : data.items;
    if (!items.length) return h("p", { class: "text-muted" }, t("core.empty.title"));
    const keys = [...new Set(items.flatMap((x) => (x && typeof x === "object" ? Object.keys(x) : [])))]
      .filter((k) => !/(^id$|_id$|version|url)/.test(k) && items.some((x) => isScalar(x?.[k])));
    return simpleTable(keys.map(humanize), items.map((x) => keys.map((k) => fmt(x?.[k]))));
  }
  if (typeof data === "object") {
    return h("dl", { class: "kv" }, Object.entries(data).filter(([k, v]) => isScalar(v) && k !== "title")
      .map(([k, v]) => [h("dt", humanize(k)), h("dd", fmt(v))]));
  }
  return h("p", String(data));
}

const isScalar = (v) => v == null || ["string", "number", "boolean"].includes(typeof v);
const humanize = (k) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const fmt = (v) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v) ? formatDateTime(v, { year: "always" }) : v == null ? "" : String(v));

function simpleTable(cols, rows) {
  return h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
    h("thead", h("tr", cols.map((c) => h("th", c)))),
    h("tbody", rows.map((r) => h("tr", r.map((v, i) => h("td", { "data-label": cols[i] }, v)))))));
}
