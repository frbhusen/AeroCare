// Toasts + Undo for staged deletions (DELETE -> 202 {undo_token, undo_seconds}; POST /undo).
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { api } from "../core/api.js";
import { icon } from "./icons.js";

const ICONS = { success: "check", error: "alert", warning: "alert", info: "info" };

function container() {
  let c = document.getElementById("toasts");
  if (!c) {
    c = h("div", { id: "toasts", class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(c);
  }
  return c;
}

/**
 * toast(message, {type: "info"|"success"|"error"|"warning", duration ms (0 = sticky),
 *                 action: {label, onClick}}) -> {close, el}
 */
export function toast(message, { type = "info", duration, action } = {}) {
  const ms = duration ?? (type === "error" ? 7000 : 4000);
  let timer;
  const close = () => {
    clearTimeout(timer);
    el.remove();
  };
  const el = h("div", { class: `toast toast-${type}`, role: type === "error" ? "alert" : "status" },
    icon(ICONS[type] || "info"),
    h("div", { class: "toast-msg" }, message),
    action ? h("button", { class: "btn btn-sm", type: "button", onClick: async () => { close(); await action.onClick(); } }, action.label) : null,
    h("button", { class: "toast-close", type: "button", "aria-label": t("core.close"), onClick: close }, icon("x")));
  container().append(el);
  if (ms > 0) timer = setTimeout(close, ms);
  return { close, el };
}

export const toastSuccess = (m, o) => toast(m, { ...o, type: "success" });
export const toastError = (m, o) => toast(m, { ...o, type: "error" });

/** Show an ApiError (or any error) as a toast. */
export function toastApiError(err) {
  console.warn(err);
  return toast(err?.message || t("core.error.generic"), { type: "error" });
}

/**
 * Undo toast for a staged deletion response.
 * undoToast(res, {message, onUndone}) where res = {undo_token, undo_seconds, undo_expires_at}.
 */
export function undoToast(res, { message, onUndone } = {}) {
  if (!res?.undo_token) return toast(message || t("core.deleted"), { type: "success" });
  const seconds = Number(res.undo_seconds) || 30;
  const expires = res.undo_expires_at ? Date.parse(res.undo_expires_at) : Date.now() + seconds * 1000;
  const deadline = Math.min(Date.now() + seconds * 1000, Number.isNaN(expires) ? Infinity : expires);
  const count = h("span", { class: "toast-countdown" });
  let done = false;
  const tick = () => {
    const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
    count.textContent = `${left}s`;
    if (left <= 0) handle.close();
  };
  const handle = toast(h("span", message || t("core.deleted"), " ", count), {
    type: "info",
    duration: 0,
    action: {
      label: t("core.undo"),
      onClick: async () => {
        if (done) return;
        done = true;
        try {
          await api.post("/undo", { undo_token: res.undo_token });
          toast(t("core.restored"), { type: "success" });
          if (onUndone) await onUndone();
        } catch (e) {
          toastApiError(e);
        }
      },
    },
  });
  tick();
  const iv = setInterval(() => {
    if (!handle.el.isConnected) return clearInterval(iv);
    tick();
  }, 500);
  return handle;
}

/**
 * DELETE with confirmation-free undo flow: deleteWithUndo("/patients/5", {message, onDone, onUndone}).
 * onDone runs after the server staged the deletion (refresh your list there).
 */
export async function deleteWithUndo(url, { message, onDone, onUndone, body } = {}) {
  try {
    const res = await api.del(url, body ? { body } : undefined);
    if (onDone) await onDone(res);
    undoToast(res, { message, onUndone });
    return res;
  } catch (e) {
    toastApiError(e);
    throw e;
  }
}
