// Shared billing UI helpers.
import { api, h, t, areaHref, statusPill, getClinic, getDepartment, getClinics, clinicsOf, localName, isCenterWide,
  formatMoney } from "../core/index.js";

/** Route prefix of the billing area: center "financial", department "billing". */
export const basePath = (ctx) => (ctx.area === "center" ? "financial" : "billing");
export const link = (ctx, sub = "", query) => areaHref(ctx, `${basePath(ctx)}${sub ? `/${sub}` : ""}`, query);

export const invoiceStatus = (s) => statusPill(s, "billing.status", { draft: "draft", issued: "unpaid",
  partially_paid: "partial", paid: "paid", void: "cancelled" }[s]);

let metaPromise = null;
/** GET /billing/meta once per page load (currency, kinds, `can` flags). */
export function meta(force = false) {
  if (!metaPromise || force) metaPromise = api.get("/billing/meta", { cache: true }).catch((e) => { metaPromise = null; throw e; });
  return metaPromise;
}

/** Clinics the user may pick in this context (department area: that department's clinics). */
export function clinicOptions(ctx) {
  const list = ctx.area === "department" ? clinicsOf(ctx.dept.id) : getClinics();
  return list.map((c) => ({ value: c.id, label: c.name }));
}

export const clinicName = (id) => getClinic(id)?.name || (id ? `#${id}` : "");
export const deptName = (id) => { const d = getDepartment(id); return d ? localName(d, d.name) : (id ? `#${id}` : ""); };

/** Default filters for the current area (department area is pinned to its department). */
export const areaFilter = (ctx) => (ctx.area === "department" ? { department_id: ctx.dept.id } : {});

// ---- money (client-side estimates only; the server is authoritative)
export function toCents(v) {
  if (v == null || v === "") return 0;
  const s = String(v).trim();
  if (!/^-?\d*(\.\d*)?$/.test(s)) return NaN;
  const neg = s.startsWith("-");
  const [i, f = ""] = s.replace("-", "").split(".");
  const cents = Number(i || 0) * 100 + Number((f + "00").slice(0, 2)) + (Number(f[2] || 0) >= 5 ? 1 : 0);
  return neg ? -cents : cents;
}
export const fromCents = (c) => (Number.isFinite(c) ? `${c < 0 ? "-" : ""}${Math.floor(Math.abs(c) / 100)}.${String(Math.abs(c) % 100).padStart(2, "0")}` : "");

/** {gross, discount, total} in cents for a line {qty, unit_price, discount_mode, discount_value}. */
export function lineMath(line) {
  const qty = toCents(line.qty || "1"); // hundredths of a unit
  const price = toCents(line.unit_price);
  if (!Number.isFinite(qty) || !Number.isFinite(price)) return { gross: NaN, discount: 0, total: NaN };
  const gross = Math.round((qty * price) / 100);
  let discount = 0;
  if (line.discount_value) {
    discount = line.discount_mode === "percent"
      ? Math.round((gross * toCents(line.discount_value)) / 10000)
      : toCents(line.discount_value);
  }
  return { gross, discount, total: gross - discount };
}

export const money = (v) => h("span", { class: "num ltr nowrap" }, formatMoney(v));

export function moneyStat(label, value, variant) {
  return h("div", { class: ["stat", "card", variant && `billing-stat--${variant}`] },
    h("div", { class: "stat-label" }, label), h("div", { class: "stat-value num ltr" }, formatMoney(value)));
}

/** Total / Paid / Remaining strip used on invoice screens. */
export function totalsStrip(inv) {
  return h("div", { class: "billing-totals grid-3" },
    moneyStat(t("billing.total"), inv.total),
    moneyStat(t("billing.paid"), inv.paid_total, "paid"),
    moneyStat(t("billing.remaining"), inv.balance, Number(inv.balance) > 0 && inv.status !== "void" ? "due" : null));
}

export const showDeptFilter = (ctx) => ctx.area === "center" && isCenterWide();
