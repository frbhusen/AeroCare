// Session lifecycle: load /auth/me, login, logout, change password, superadmin support view.
import { api } from "../core/api.js";
import { setSession, clearSession, getUser } from "../core/state.js";
import { setDefaultCurrency, t } from "../core/i18n.js";
import { emit } from "../core/events.js";
import { setOfflineUserId } from "../offline/idb.js";
import { clearCache } from "../offline/cache.js";
import { listOps, startSync } from "../offline/queue.js";
import { createForm } from "../components/form.js";
import { openModal, confirmDialog } from "../components/modal.js";
import { toast } from "../components/toast.js";

/** GET /auth/me -> payload or null when not signed in. Throws on network/server errors. */
export async function fetchMe() {
  try {
    return await api.get("/auth/me", { silent401: true });
  } catch (e) {
    if (e.status === 401) return null;
    throw e;
  }
}

/** Apply a /auth/me (or login) payload to the app. */
export async function applySession(me) {
  const prevUser = getUser();
  setSession(me);
  setOfflineUserId(me.user.id);
  if (!prevUser || prevUser.id !== me.user.id) await clearCache(me.user.id);
  setDefaultCurrency(me.center?.currency);
  startSync();
  emit("auth:changed", me);
}

export async function login(email, password) {
  const me = await api.post("/auth/login", { email, password }, { silent401: true });
  await applySession(me);
  return me;
}

/** Reload identity (after support enter/exit, permission changes...). */
export async function reloadSession() {
  const me = await fetchMe();
  if (!me) {
    emit("auth:lost", { code: "unauthorized" });
    return null;
  }
  await applySession(me);
  return me;
}

export async function logout() {
  const pending = (await listOps()).length;
  if (pending && !(await confirmDialog({ title: t("core.logout"), message: t("core.logout.pending", { count: pending }), danger: true,
    confirmLabel: t("core.logout") }))) return false;
  try {
    await api.post("/auth/logout", {}, { silent401: true });
  } catch (e) {
    if (!e.isNetwork) console.warn("logout failed", e);
  }
  await clearCache();
  setOfflineUserId(null);
  clearSession();
  emit("auth:lost", { code: "logged_out" });
  return true;
}

export function openChangePassword() {
  let modal;
  const form = createForm({
    columns: 1,
    fields: [
      { name: "current_password", label: t("core.password.current"), type: "password", required: true, autocomplete: "current-password" },
      { name: "new_password", label: t("core.password.new"), type: "password", required: true, autocomplete: "new-password",
        help: t("core.password.rule") },
      { name: "confirm", label: t("core.password.confirm"), type: "password", required: true, autocomplete: "new-password" },
    ],
    submitLabel: t("core.password.change"),
    onCancel: () => modal.close(),
    onSubmit: async (v, f) => {
      if (v.new_password !== v.confirm) return f.setErrors({ confirm: t("core.password.mismatch") });
      try {
        await api.post("/auth/change-password", { current_password: v.current_password, new_password: v.new_password }, { silent401: true });
      } catch (e) {
        if (e.code === "invalid_credentials") return f.setErrors({ current_password: t("core.password.wrong") });
        if (e.details?.password) return f.setErrors({ new_password: e.details.password });
        throw e;
      }
      modal.close();
      toast(t("core.password.changed"), { type: "success" });
    },
  });
  modal = openModal({ title: t("core.password.change"), size: "sm", body: form.el });
}

/** Superadmin: enter a center's support view (read-only medical data). */
export async function enterSupport(centerId) {
  await api.post("/auth/support/enter", { center_id: Number(centerId) });
  await reloadSession();
  location.hash = "#/center";
}

export async function exitSupport() {
  await api.post("/auth/support/exit", {});
  await reloadSession();
  location.hash = "#/admin";
}
