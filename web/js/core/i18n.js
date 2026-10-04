// i18n + locale formatting. Timezone is always Asia/Damascus (spec §68).
// Language preference is the ONLY value this app keeps in localStorage.
import { emit } from "./events.js";
import en from "./locales/en.js";
import ar from "./locales/ar.js";

export const TIMEZONE = "Asia/Damascus";
export const LANGS = ["en", "ar"];
const STORAGE_KEY = "hc.lang";
const dicts = { en: { ...en }, ar: { ...ar } };
let lang = detectLang();
let defaultCurrency = "SYP";

function detectLang() {
  let saved = null;
  try {
    saved = localStorage.getItem(STORAGE_KEY);
  } catch { /* storage blocked: fall back to browser language */ }
  if (LANGS.includes(saved)) return saved;
  return (navigator.language || "en").toLowerCase().startsWith("ar") ? "ar" : "en";
}

/** Merge module dictionaries: register({en: {...}, ar: {...}}). Keys are namespaced: "<module>.<key>". */
export function registerDictionary(d) {
  for (const l of LANGS) if (d && d[l]) Object.assign(dicts[l], d[l]);
}

/** t("patients.title"), t("core.items", {count: 3}) — "{count} items". Missing key -> English -> key. */
export function t(key, params) {
  if (typeof params === "string") params = { default: params }; // t(key, fallbackText)
  let s = dicts[lang][key] ?? dicts.en[key];
  if (s == null) {
    if (params && params.default != null) s = params.default;
    else return key;
  }
  if (params) s = s.replace(/\{(\w+)\}/g, (m, k) => (params[k] != null ? String(params[k]) : m));
  return s;
}

/** True when a key exists (in current language or English). */
export const hasKey = (key) => key in dicts[lang] || key in dicts.en;

export const getLang = () => lang;
export const isRtl = () => lang === "ar";
export const dir = () => (lang === "ar" ? "rtl" : "ltr");

export function applyLang() {
  document.documentElement.lang = lang;
  document.documentElement.dir = dir();
}

export function setLang(next) {
  if (!LANGS.includes(next) || next === lang) return;
  lang = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch { /* ignore */ }
  applyLang();
  emit("lang:changed", { lang });
}

/** Pick the localized name from objects with name_en/name_ar (e.g. department types). */
export function localName(obj, fallback = "") {
  if (!obj) return fallback;
  return (lang === "ar" ? obj.name_ar : obj.name_en) || obj.name || fallback;
}

// ------------------------------------------------------------------ numbers & money
const locale = () => (lang === "ar" ? "ar-SY-u-nu-latn" : "en-US");

export function formatNumber(n, { decimals, min, max } = {}) {
  if (n == null || n === "") return "";
  const v = Number(n);
  if (!Number.isFinite(v)) return String(n);
  return new Intl.NumberFormat(locale(), {
    minimumFractionDigits: decimals ?? min ?? 0,
    maximumFractionDigits: decimals ?? max ?? 2,
  }).format(v);
}

export function setDefaultCurrency(c) {
  if (c) defaultCurrency = c;
}
export const getCurrency = () => defaultCurrency;

/** Money strings from the API ("1250.00") -> "1,250.00 SYP" (currency label localized when known). */
export function formatMoney(amount, currency = defaultCurrency) {
  if (amount == null || amount === "") return "";
  const label = t(`core.currency.${currency}`, { default: currency });
  return `${formatNumber(amount, { decimals: 2 })} ${label}`;
}

// ------------------------------------------------------------------ dates & times
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const partsFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: TIMEZONE, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  second: "2-digit", hourCycle: "h23",
});

/** Calendar parts in Asia/Damascus: {year, month, day, hour, minute, second} (numbers). Date-only strings are not shifted. */
export function tzParts(value) {
  if (value == null || value === "") return null;
  if (typeof value === "string") {
    const m = DATE_ONLY.exec(value);
    if (m) return { year: +m[1], month: +m[2], day: +m[3], hour: 0, minute: 0, second: 0, dateOnly: true };
  }
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  const out = {};
  for (const p of partsFmt.formatToParts(d)) if (p.type !== "literal") out[p.type] = Number(p.value);
  if (out.hour === 24) out.hour = 0;
  return out;
}

const pad = (n) => String(n).padStart(2, "0");
const currentYear = () => tzParts(new Date()).year;

function monthName(m, style) {
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-SY" : "en-US", { month: style, timeZone: "UTC" })
    .format(new Date(Date.UTC(2000, m - 1, 1)));
}

/**
 * Month/day order (spec §68). opts.year: "auto" (default; shown when not the current year) | "always" | "never".
 * opts.month: "numeric" (default, MM/DD[/YYYY]) | "short" | "long" ("Oct 3[, 2025]").
 */
export function formatDate(value, { year = "auto", month = "numeric" } = {}) {
  const p = tzParts(value);
  if (!p) return "";
  const showYear = year === "always" || (year === "auto" && p.year !== currentYear());
  if (month === "numeric") return `${pad(p.month)}/${pad(p.day)}${showYear ? `/${p.year}` : ""}`;
  return `${monthName(p.month, month)} ${p.day}${showYear ? `${lang === "ar" ? "،" : ","} ${p.year}` : ""}`;
}

/** HH:MM (24h) in Asia/Damascus. */
export function formatTime(value) {
  const p = tzParts(value);
  return p ? `${pad(p.hour)}:${pad(p.minute)}` : "";
}

export function formatDateTime(value, opts) {
  const p = tzParts(value);
  if (!p) return "";
  return `${formatDate(value, opts)} ${formatTime(value)}`;
}

/** "5 minutes ago" style; falls back to date for older than a week. */
export function formatRelative(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const sec = Math.round((d.getTime() - Date.now()) / 1000);
  const abs = Math.abs(sec);
  const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
  if (abs < 60) return rtf.format(Math.round(sec), "second");
  if (abs < 3600) return rtf.format(Math.round(sec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(sec / 3600), "hour");
  if (abs < 7 * 86400) return rtf.format(Math.round(sec / 86400), "day");
  return formatDate(value);
}

/** Value for <input type="date"> (Damascus calendar day). */
export function toDateInput(value) {
  const p = tzParts(value);
  return p ? `${p.year}-${pad(p.month)}-${pad(p.day)}` : "";
}

/** Value for <input type="datetime-local">; the API treats naive datetimes as Asia/Damascus local. */
export function toDateTimeInput(value) {
  const p = tzParts(value);
  return p ? `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}` : "";
}

/** Today's date (YYYY-MM-DD) in Asia/Damascus. */
export const todayISO = () => toDateInput(new Date());

/** Whole years between a YYYY-MM-DD birth date and today (Damascus). */
export function ageFrom(dob) {
  const b = tzParts(dob);
  const n = tzParts(new Date());
  if (!b || !n) return null;
  let a = n.year - b.year;
  if (n.month < b.month || (n.month === b.month && n.day < b.day)) a -= 1;
  return a < 0 ? null : a;
}

/** Human file size. */
export function formatBytes(bytes) {
  const b = Number(bytes) || 0;
  if (b < 1024) return `${b} B`;
  if (b < 1024 ** 2) return `${formatNumber(b / 1024, { max: 1 })} KB`;
  if (b < 1024 ** 3) return `${formatNumber(b / 1024 ** 2, { max: 1 })} MB`;
  return `${formatNumber(b / 1024 ** 3, { max: 2 })} GB`;
}
