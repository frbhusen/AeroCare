// Shared helpers for the dermatology + ophthalmology UIs (patient header, clinic choice, meta cache).
import {
  api, h, t, getLang, clinicsOf, canClinic, formatDate, ageFrom, icon, areaHref, patientSearch, mount,
  errorState, loadingState, toast, toastApiError, navigate,
} from "../core/index.js";

const metaCache = new Map();

/** Cached GET of a module meta endpoint ("/dermatology/meta"). Retries after a failure. */
export function getMeta(url) {
  if (!metaCache.has(url)) {
    metaCache.set(url, api.get(url, { cache: true }).catch((e) => {
      metaCache.delete(url);
      throw e;
    }));
  }
  return metaCache.get(url);
}

/** Region label in the UI language from the body-region catalog. */
export function regionLabel(catalog, code) {
  const r = catalog?.regions?.find((x) => x.code === code);
  if (!r) return code;
  return getLang() === "ar" ? r.ar : r.en;
}

/** Clinics of the current department the user can work in. */
export const deptClinics = (ctx) => clinicsOf(ctx.dept.id).filter((c) => canClinic(c.id));

/** Form field spec for choosing the clinic (hidden when there is exactly one). */
export function clinicFieldSpec(ctx, label, value) {
  const list = deptClinics(ctx);
  if (list.length === 1) return { name: "clinic_id", type: "hidden", default: list[0].id };
  return { name: "clinic_id", label, type: "select", required: true, numeric: true,
    options: list.map((c) => ({ value: c.id, label: c.name })), default: value };
}

/** Default values for fields that carry a `default` (e.g. the single clinic). */
export const fieldDefaults = (fields) => Object.fromEntries(fields.filter((f) => f.default != null).map((f) => [f.name, f.default]));

/** Patient display name + code. */
export const patientLabel = (p) => (p ? `${p.full_name || ""}${p.display_code ? ` · ${p.display_code}` : ""}` : "");

/** Load + render the patient header card. Returns {el, patient: Promise}. */
export function patientHeader(patientId, { actions = [] } = {}) {
  const el = h("div", { class: "card derm-patient" }, loadingState());
  const patient = api.get(`/patients/${encodeURIComponent(patientId)}`, { cache: true });
  patient.then((p) => {
    const facts = [
      p.display_code && h("span", { class: "ltr" }, p.display_code),
      p.date_of_birth && t("dermatology.c.patient.age", { age: ageFrom(p.date_of_birth) ?? "—", dob: formatDate(p.date_of_birth, { year: "always" }) }),
      p.gender && t(`dermatology.c.gender.${p.gender}`),
      p.phone && h("span", { class: "ltr" }, p.phone),
      p.blood_type && h("span", { class: "ltr" }, p.blood_type),
    ].filter(Boolean);
    mount(el,
      h("div", { class: "card-body derm-patient-body" },
        h("div", { class: "derm-patient-avatar", "aria-hidden": "true" }, icon("user")),
        h("div", { class: "derm-patient-main" },
          h("h1", { class: "derm-patient-name" }, p.full_name),
          h("div", { class: "text-muted text-sm derm-facts" }, facts.flatMap((x, i) => (i ? [" · ", x] : [x])))),
        actions.length ? h("div", { class: "page-actions" }, actions) : null),
      p.allergies ? h("div", { class: "alert alert-danger derm-allergies" }, icon("alert"),
        h("div", h("strong", t("dermatology.c.patient.allergies")), " ", p.allergies)) : null,
      p.chronic_conditions ? h("div", { class: "alert alert-warning derm-allergies" }, icon("info"),
        h("div", h("strong", t("dermatology.c.patient.chronic")), " ", p.chronic_conditions)) : null);
  }).catch((e) => mount(el, errorState(e)));
  return { el, patient };
}

/** Patient picker card used on list pages: choose a patient -> navigate to the chart. */
export function openPatientBox(ctx, chartPath, label) {
  const box = patientSearch({
    placeholder: label,
    onSelect: (p) => navigate(areaHref(ctx, `${chartPath}/${p.id}`)),
  });
  return h("div", { class: "derm-patient-pick" }, box.el);
}

/** Labelled value for read-only detail views (skips empty values). */
export function kv(items) {
  const rows = items.filter(([, v]) => v != null && v !== "" && !(Array.isArray(v) && !v.length));
  if (!rows.length) return null;
  return h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", k), h("dd", { class: "derm-pre" }, v)]));
}

/** Toast after an offline-capable mutation. Returns true when queued. */
export function queuedNotice(res) {
  if (res && res.queued) {
    toast(t("dermatology.c.saved_offline"), { type: "warning" });
    return true;
  }
  return false;
}

/** Shows a friendly message for version conflicts and runs reload(). */
export function conflictAware(err, reload) {
  if (err?.code === "version_conflict") {
    toast(t("dermatology.c.version_conflict"), {
      type: "warning", duration: 0, action: { label: t("dermatology.c.reload"), onClick: () => reload && reload() },
    });
    return true;
  }
  toastApiError(err);
  return false;
}

/** Local datetime input value from an ISO string (Damascus wall clock). */
export { toDateTimeInput, toDateInput } from "../core/index.js";
