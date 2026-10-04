// Shared helpers for the dentistry UI: meta cache, clinic choice, status pills, conflict handling.
import { api, h, t, getUser, statusPill, toast, toastApiError, apiUrl } from "../core/index.js";

const BASE = "/dentistry";
export const dentUrl = (path) => `${BASE}${path}`;

let metaCache = { user: null, promise: null };

/** GET /dentistry/meta once per user (numbering, vocabularies, accessible dental clinics, permission flags). */
export function loadMeta(force = false) {
  const uid = getUser()?.id ?? null;
  if (force || !metaCache.promise || metaCache.user !== uid) {
    const promise = api.get(dentUrl("/meta"), { cache: true });
    metaCache = { user: uid, promise };
    promise.catch(() => { if (metaCache.promise === promise) metaCache.promise = null; });
  }
  return metaCache.promise;
}

/** Dental clinics of the current department (meta.clinics is already scope-filtered by the server). */
export function deptClinics(meta, ctx) {
  const all = meta?.clinics || [];
  const mine = ctx?.dept ? all.filter((c) => c.department_id === ctx.dept.id) : all;
  return mine.length ? mine : all;
}

const STATUS_VARIANT = {
  planned: "draft", accepted: "purple", scheduled: "scheduled", "in-progress": "in_progress",
  completed: "completed", cancelled: "cancelled",
};
export const statusBadge = (s) => statusPill(s, "dentistry.status", STATUS_VARIANT[s] || "neutral");

const PRIORITY_VARIANT = { low: "neutral", medium: "info", high: "danger" };
export const priorityBadge = (p) => statusPill(p, "dentistry.priority", PRIORITY_VARIANT[p] || "neutral");

export const conditionLabel = (c) => (c ? t(`dentistry.condition.${c}`) : t("dentistry.condition.healthy"));
export const xrayTypeLabel = (x) => t(`dentistry.xray_type.${x || "other"}`);

/** Tooth label for a record {tooth_mode, tooth_number} following AeroDent (primary = letters). */
export function toothLabel(rec) {
  if (!rec?.tooth_number) return "—";
  return rec.tooth_mode === "primary" ? String.fromCharCode(64 + rec.tooth_number) : String(rec.tooth_number);
}

/** Show a mutation error; on version_conflict offer a reload action. */
export function mutationError(err, reload) {
  if (err?.code === "version_conflict") {
    return toast(t("dentistry.conflict"), {
      type: "warning", duration: 0,
      action: reload ? { label: t("dentistry.reload"), onClick: reload } : undefined,
    });
  }
  return toastApiError(err);
}

/** Queued offline mutations resolve {queued: true}. */
export function savedNotice(res) {
  if (res?.queued) toast(t("dentistry.saved_offline"), { type: "warning" });
  else toast(t("dentistry.saved"), { type: "success" });
}

export const fileSrc = (fileId) => apiUrl(`/files/${encodeURIComponent(fileId)}/content`);

/** Small labelled select used in toolbars. */
export function filterSelect(label, options, value, onChange) {
  const sel = h("select", { class: "select", "aria-label": label, onChange: (e) => onChange(e.target.value || null) },
    h("option", { value: "" }, label), options.map((o) => h("option", { value: o.value }, o.label)));
  sel.value = value || "";
  return sel;
}

export const toothModes = () => [
  { value: "permanent", label: t("dentistry.mode.permanent") },
  { value: "primary", label: t("dentistry.mode.primary") },
];
export const statusOptions = (meta) => meta.statuses.map((s) => ({ value: s, label: t(`dentistry.status.${s}`) }));
export const priorityOptions = (meta) => meta.priorities.map((s) => ({ value: s, label: t(`dentistry.priority.${s}`) }));

/** <datalist> with suggested procedure names; returns {id, el}. */
export function procedureList(meta) {
  const id = `dent-proc-${Math.random().toString(36).slice(2, 8)}`;
  return { id, el: h("datalist", { id }, meta.procedures.map((p) => h("option", { value: t(`dentistry.procedure.${p}`) }))) };
}

/** Doctors for the clinic picker (cached per clinic). */
const doctorCache = new Map();
export function loadDoctors(clinicId) {
  if (!doctorCache.has(clinicId)) {
    const p = api.get(dentUrl("/doctors"), { query: { clinic_id: clinicId } }).then((r) => r.items || []);
    p.catch(() => doctorCache.delete(clinicId));
    doctorCache.set(clinicId, p);
  }
  return doctorCache.get(clinicId);
}
