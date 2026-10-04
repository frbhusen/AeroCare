// Shared helpers for the appointments UI.
import { api, h, t, statusPill, formatDate, formatTime, getUser } from "../core/index.js";
import { hasKey } from "../core/i18n.js";

let metaPromise = null;
let cacheUser = null;
const doctorCache = new Map();
function checkUser() {
  const uid = getUser()?.id ?? null;
  if (uid !== cacheUser) { cacheUser = uid; metaPromise = null; doctorCache.clear(); }
}

/** GET /appointments/meta once per signed-in user (statuses, transitions, clinics in scope, can{}). */
export function loadMeta(force = false) {
  checkUser();
  if (force || !metaPromise) metaPromise = api.get("/appointments/meta").catch((e) => { metaPromise = null; throw e; });
  return metaPromise;
}

export function loadDoctors(clinicId) {
  checkUser();
  if (!clinicId) return Promise.resolve([]);
  const key = Number(clinicId);
  if (!doctorCache.has(key)) {
    doctorCache.set(key, api.get("/appointments/doctors", { query: { clinic_id: key } })
      .then((r) => r.items || []).catch((e) => { doctorCache.delete(key); throw e; }));
  }
  return doctorCache.get(key);
}

/** Clinics shown in this area: department area -> only that department's clinics. */
export function areaClinics(meta, ctx) {
  const all = meta?.clinics || [];
  return ctx?.area === "department" && ctx.dept ? all.filter((c) => c.department_id === ctx.dept.id) : all;
}

export const pill = (status) => statusPill(status, "appointments.status");

export function typeLabel(type) {
  if (!type) return "";
  const key = `appointments.type.${type}`;
  return hasKey(key) ? t(key) : type;
}

// ---- local calendar-date arithmetic on "YYYY-MM-DD" strings (no timezone involved)
const toUTC = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
const fromUTC = (dt) => dt.toISOString().slice(0, 10);
export const addDays = (iso, n) => { const d = toUTC(iso); d.setUTCDate(d.getUTCDate() + n); return fromUTC(d); };
/** ISO weekday 1=Mon..7=Sun */
export const isoWeekday = (iso) => ((toUTC(iso).getUTCDay() + 6) % 7) + 1;
/** Saturday on or before the date (the local working week starts on Saturday, as the API). */
export const weekStart = (iso) => addDays(iso, -((isoWeekday(iso) - 6 + 7) % 7));
export const weekdayName = (iso) => t(`appointments.wd.${isoWeekday(iso)}`);

/** "HH:MM" + minutes -> "HH:MM" (clamped to 23:59). */
export function addMinutes(hhmm, minutes) {
  const [hh, mm] = (hhmm || "00:00").split(":").map(Number);
  const total = Math.min(23 * 60 + 59, hh * 60 + mm + Number(minutes || 0));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}
export function minutesBetween(a, b) {
  const [ah, am] = a.split(":").map(Number);
  const [bh, bm] = b.split(":").map(Number);
  return bh * 60 + bm - (ah * 60 + am);
}

/** Readable block for a 409 appointment_conflict (single slot or recurring dates). Returns null otherwise. */
export function conflictBlock(err) {
  if (err?.code !== "appointment_conflict") return null;
  const d = err.details || {};
  let items = [];
  if (Array.isArray(d.conflicting_dates)) {
    return h("div", { class: "alert alert-danger appt-conflict", role: "alert" },
      h("strong", t("appointments.conflict.title")),
      h("div", t("appointments.conflict.dates")),
      h("ul", d.conflicting_dates.map((x) => h("li", { class: "ltr" }, formatDate(x, { year: "always" }) + ` (${weekdayName(x)})`))));
  }
  if (Array.isArray(d.conflicts)) {
    items = d.conflicts.map((c) => h("li", t(`appointments.conflict.${c.kind || "clinic"}`, {
      from: `${formatDate(c.starts_at)} ${formatTime(c.starts_at)}`, to: formatTime(c.ends_at) })));
  }
  return h("div", { class: "alert alert-danger appt-conflict", role: "alert" },
    h("strong", t("appointments.conflict.title")),
    items.length ? h("ul", items) : h("div", t("appointments.conflict.generic")));
}

export const timeRange = (a) => h("span", { class: "ltr nowrap" }, `${a.start_time}–${a.end_time}`);
