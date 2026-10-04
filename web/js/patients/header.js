// Reusable patient header / profile card (exported for other modules).
//
//   import { patientHeader, loadPatient, patientHref } from "../patients/header.js";
//   const p = await loadPatient(id);            // GET /patients/<id> (404 -> ApiError)
//   el.append(patientHeader(p, { ctx, actions: [btn], compact: false }));
import { api, h, t, formatDate, ageFrom, areaHref, icon, initials } from "../core/index.js";

export const loadPatient = (id) => api.get(`/patients/${encodeURIComponent(id)}`, { cache: true });

/** Link to the patient profile in the current area (center or department). */
export const patientHref = (ctx, id, sub = "") => areaHref(ctx, `patients/${id}${sub ? `/${sub}` : ""}`);

export function genderLabel(g) {
  return g ? t(`patients.gender.${g}`) : "";
}

/** Compact identity line: code · age · gender · phone. */
export function patientMeta(p) {
  const age = p.date_of_birth ? ageFrom(p.date_of_birth) : null;
  return [
    h("span", { class: "ltr" }, p.display_code),
    p.date_of_birth ? h("span", formatDate(p.date_of_birth, { year: "always" }),
      age != null ? ` (${t("patients.age_years", { age })})` : "") : null,
    p.gender ? h("span", genderLabel(p.gender)) : null,
    p.phone ? h("span", { class: "ltr" }, p.phone) : null,
  ].filter(Boolean).flatMap((x, i) => (i ? [h("span", { class: "text-muted" }, " · "), x] : [x]));
}

/**
 * patientHeader(patient, {ctx, actions: Node[], compact, link: true}) -> card element.
 * Shows allergies / chronic conditions as alerts (they matter in every department).
 */
export function patientHeader(p, { ctx, actions = [], compact = false, link = false } = {}) {
  const name = link && ctx ? h("a", { href: patientHref(ctx, p.id) }, p.full_name) : p.full_name;
  const warn = [];
  if (p.allergies) warn.push(h("span", { class: "pill pill--danger", title: p.allergies }, icon("alert"), t("patients.field.allergies"), ": ", p.allergies));
  if (!compact && p.chronic_conditions) warn.push(h("span", { class: "pill pill--warning", title: p.chronic_conditions }, t("patients.field.chronic_conditions"), ": ", p.chronic_conditions));
  if (!compact && p.blood_type) warn.push(h("span", { class: "pill pill--info" }, t("patients.field.blood_type"), ": ", h("span", { class: "ltr" }, p.blood_type)));
  return h("section", { class: ["card", "pat-header", compact && "pat-header--compact"] },
    h("div", { class: "pat-header-main" },
      h("div", { class: "avatar pat-avatar", "aria-hidden": "true" }, initials(p.full_name)),
      h("div", { class: "pat-header-id" },
        h(compact ? "strong" : "h1", { class: "pat-name" }, name),
        h("div", { class: "pat-meta text-sm" }, patientMeta(p))),
      actions.length ? h("div", { class: "pat-header-actions row no-print" }, actions) : null),
    warn.length ? h("div", { class: "pat-warnings row" }, warn) : null);
}
