// /patients/meta (choices for forms), cached per signed-in user.
import { api, t, getUser } from "../core/index.js";

let cache = null;

export function loadMeta() {
  const uid = getUser()?.id;
  if (!cache || cache.uid !== uid) cache = { uid, p: api.get("/patients/meta", { cache: true }).catch((e) => { cache = null; throw e; }) };
  return cache.p;
}

/** General-profile fields (besides full_name/phone/clinic which the caller places). */
export function profileFields(meta, { compact = false } = {}) {
  return [
    { name: "date_of_birth", label: t("patients.field.date_of_birth"), type: "date" },
    { name: "gender", label: t("patients.field.gender"), type: "select",
      options: meta.genders.map((g) => ({ value: g, label: t(`patients.gender.${g}`) })) },
    { name: "blood_type", label: t("patients.field.blood_type"), type: "select",
      options: meta.blood_types.map((b) => ({ value: b, label: b })) },
    { name: "address", label: t("patients.field.address"), maxLength: 300 },
    { name: "allergies", label: t("patients.field.allergies"), type: "textarea", rows: compact ? 2 : 3, span: 2 },
    { name: "chronic_conditions", label: t("patients.field.chronic_conditions"), type: "textarea", rows: compact ? 2 : 3, span: 2 },
    { name: "medications", label: t("patients.field.medications"), type: "textarea", rows: compact ? 2 : 3, span: 2 },
    { name: "general_notes", label: t("patients.field.general_notes"), type: "textarea", rows: compact ? 2 : 3, span: 2 },
  ];
}
