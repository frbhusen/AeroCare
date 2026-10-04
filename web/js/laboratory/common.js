// Shared laboratory UI helpers (also used by the radiology module).
import { h, t, toast, toastApiError, statusPill } from "../core/index.js";

/** Same rules as backend flags.py: returns "L"|"H"|"N"|"A"|null, or undefined when the value is invalid. */
export function computeFlag(item, value, abnormal) {
  const v = value == null ? "" : String(value).trim();
  if (!v) return null;
  if (item.result_type === "numeric") {
    const n = Number(v.replace(",", "."));
    if (!Number.isFinite(n)) return undefined;
    const lo = item.ref_low == null ? null : Number(item.ref_low);
    const hi = item.ref_high == null ? null : Number(item.ref_high);
    if (lo != null && n < lo) return "L";
    if (hi != null && n > hi) return "H";
    return lo == null && hi == null ? null : "N";
  }
  if (item.result_type === "choice") {
    if ((item.choices || []).length && !item.choices.includes(v)) return undefined;
    if (abnormal != null) return abnormal ? "A" : "N";
    if ((item.normal_choices || []).length) return item.normal_choices.includes(v) ? "N" : "A";
    return null;
  }
  return abnormal == null ? null : abnormal ? "A" : "N";
}

export function flagBadge(flag) {
  if (!flag) return h("span", { class: "text-muted" }, "—");
  const cls = flag === "N" ? "pill--success" : "pill--danger";
  return h("span", { class: `pill ${cls} lab-flag`, title: t(`laboratory.flag.${flag}`) },
    flag === "N" ? t("laboratory.flag.N") : `${flag} · ${t(`laboratory.flag.${flag}`)}`);
}

export function refRange(i) {
  const lo = i.ref_low;
  const hi = i.ref_high;
  if (lo != null && hi != null) return `${lo} – ${hi}`;
  if (lo != null) return `≥ ${lo}`;
  if (hi != null) return `≤ ${hi}`;
  return i.ref_text || "";
}

export const labStatus = (s) => statusPill(s, "laboratory.status");

export function priorityPill(p) {
  return p === "urgent" ? h("span", { class: "pill pill--danger" }, t("laboratory.priority.urgent"))
    : h("span", { class: "pill pill--neutral" }, t("laboratory.priority.routine"));
}

/** Toast an error; on version_conflict offer a reload action. */
export function showError(err, reload) {
  if (err?.code === "version_conflict" && reload) {
    toast(t("laboratory.msg.conflict"), { type: "warning", duration: 0,
      action: { label: t("laboratory.action.reload"), onClick: reload } });
    return;
  }
  toastApiError(err);
}

export function kvList(rows) {
  return h("dl", { class: "kv" }, rows.filter((r) => r && r[1] != null && r[1] !== "")
    .flatMap(([k, v]) => [h("dt", k), h("dd", v)]));
}
