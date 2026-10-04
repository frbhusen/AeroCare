// Empty / loading / error / unavailable states, status pills, offline-copy banner.
import { h } from "../core/dom.js";
import { t, formatDateTime, hasKey } from "../core/i18n.js";
import { cachedAt } from "../core/api.js";
import { icon } from "./icons.js";

export function loadingState(label) {
  return h("div", { class: "state", role: "status" }, h("div", { class: "spinner" }), h("div", label || t("core.loading")));
}

export function emptyState({ icon: ic = "layers", title, message, action } = {}) {
  return h("div", { class: "state" }, icon(ic), h("div", { class: "state-title" }, title || t("core.empty.title")),
    message ? h("div", message) : null, action || null);
}

/** Error state for a failed load; retry() re-runs the loader. */
export function errorState(err, retry) {
  const msg = err?.message || t("core.error.generic");
  return h("div", { class: "state state-error", role: "alert" }, icon("alert"),
    h("div", { class: "state-title" }, err?.status === 404 ? t("core.error.not_found") : t("core.error.load_failed")),
    h("div", msg),
    retry ? h("button", { class: "btn btn-sm", type: "button", onClick: retry }, icon("refresh"), t("core.retry")) : null);
}

/** For features whose backend is not available yet (e.g. endpoint 404 during parallel development). */
export function unavailableState(message) {
  return h("div", { class: "state" }, icon("clock"), h("div", { class: "state-title" }, t("core.unavailable.title")),
    h("div", message || t("core.unavailable.message")));
}

/** "Coming soon" page for route slots another module will fill. */
export function comingSoon(titleKey) {
  return h("div", { class: "page" }, h("div", { class: "card coming-soon" },
    h("div", { class: "state" }, icon("clock"), h("div", { class: "state-title" }, titleKey ? t(titleKey) : t("core.soon.title")),
      h("div", t("core.soon.message")), h("span", { class: "pill pill--warning" }, t("core.soon.badge")))));
}

/** Banner shown when `data` came from the offline read cache (api.get(..., {cache:true})). Returns null otherwise. */
export function offlineCopyBanner(data) {
  const ts = cachedAt(data);
  if (!ts) return null;
  return h("div", { class: "alert alert-warning offline-copy-banner", role: "status" }, icon("wifiOff"),
    h("div", t("core.offline.cached_copy", { time: formatDateTime(ts) })));
}

/**
 * Status pill. statusPill("in_progress", "appointments.status") -> label t("appointments.status.in_progress")
 * (falls back to core.status.<status>). CSS: .pill--<status> (see components.css for the known set).
 */
export function statusPill(status, keyPrefix = "core.status", variant) {
  const key = `${keyPrefix}.${status}`;
  const label = hasKey(key) ? t(key) : t(`core.status.${status}`, { default: String(status ?? "").replace(/_/g, " ") });
  return h("span", { class: `pill pill--${variant || String(status).replace(/[^a-z0-9_-]/gi, "")}` }, label);
}
