// Application entry point (loaded by index.html).
import { applyLang, t } from "./i18n.js";
import { onEvent } from "./events.js";
import { registry } from "./registry.js";
import { startRouter, stopRouter, refresh } from "./router.js";
import { renderMatch, resetShell } from "./shell.js";
import { clearSession, isAuthenticated, getUser } from "./state.js";
import { h, mount } from "./dom.js";
import { MODULES } from "../modules.js";
import { registerPortal } from "../portal/index.js";
import { registerCenter } from "../center/index.js";
import { registerDepartmentCore } from "./department.js";
import { fetchMe, applySession, logout } from "../auth/session.js";
import { api } from "./api.js";
import { createForm } from "../components/form.js";
import { renderLogin } from "../auth/login.js";
import { setOfflineUserId } from "../offline/idb.js";
import { errorState } from "../components/states.js";
import { initOmniSearchHotkeys } from "../components/omni-search.js";

const appRoot = document.getElementById("app");
const AUTH_MESSAGES = {
  session_replaced: "core.auth.session_replaced",
  center_inactive: "core.error.center_inactive",
  account_inactive: "core.auth.account_inactive",
  session_ended: "core.auth.session_ended",
  session_expired: "core.auth.session_expired",
};

/** Administrator-chosen password (new account / reset): the user must choose their own before working. */
function showForcedPasswordChange() {
  stopRouter();
  resetShell();
  const form = createForm({
    columns: 1,
    fields: [
      { name: "current_password", label: t("core.password.current_temp"), type: "password", required: true, autocomplete: "current-password" },
      { name: "new_password", label: t("core.password.new"), type: "password", required: true, autocomplete: "new-password",
        help: t("core.password.rule") },
      { name: "confirm", label: t("core.password.confirm"), type: "password", required: true, autocomplete: "new-password" },
    ],
    submitLabel: t("core.password.change"),
    onSubmit: async (v, f) => {
      if (v.new_password !== v.confirm) return f.setErrors({ confirm: t("core.password.mismatch") });
      try {
        await api.post("/auth/change-password", { current_password: v.current_password, new_password: v.new_password });
      } catch (e) {
        if (e.code === "invalid_credentials") return f.setErrors({ current_password: t("core.password.wrong") });
        if (e.details?.password) return f.setErrors({ new_password: e.details.password });
        throw e;
      }
      const me = await fetchMe();
      await applySession(me);
      startApp();
    },
  });
  mount(appRoot, h("div", { class: "login-screen" }, h("div", { class: "login-card card card-body stack gap-md" },
    h("h1", t("core.password.must_change_title")), h("p", { class: "muted" }, t("core.password.must_change_help")), form.el,
    h("button", { class: "btn btn-ghost", type: "button", onClick: () => logout() }, t("core.logout", { default: "Sign out" })))));
}

async function loadModules() {
  const loaded = [];
  await Promise.all(MODULES.map(async (name) => {
    try {
      const mod = await import(`../${name}/index.js`);
      if (typeof mod.register !== "function") throw new Error("missing register()");
      loaded.push({ name, mod });
    } catch (e) {
      console.info(`[modules] ${name} not loaded:`, e?.message || e);
    }
  }));
  // register in the declared order for deterministic overrides
  loaded.sort((a, b) => MODULES.indexOf(a.name) - MODULES.indexOf(b.name));
  for (const { name, mod } of loaded) {
    try {
      mod.register(registry);
    } catch (e) {
      console.error(`[modules] ${name} register() failed`, e);
    }
  }
  return loaded.map((x) => x.name);
}

let modulesReady = Promise.resolve();

async function startApp() {
  await modulesReady; // module routes must be registered before the first route resolves
  if (getUser()?.must_change_password) return showForcedPasswordChange();
  resetShell();
  startRouter((m) => renderMatch(m, appRoot));
}

function showLogin(message) {
  stopRouter();
  resetShell();
  if (location.hash && location.hash !== "#/") history.replaceState(null, "", "#/");
  renderLogin(appRoot, { message, onLoggedIn: () => startApp() });
}

async function boot() {
  applyLang();
  initOmniSearchHotkeys();
  registerPortal(registry);
  registerCenter(registry);
  registerDepartmentCore(registry);
  modulesReady = loadModules().then((names) => { window.__hcModules = names; });
  let me = null;
  try {
    me = await fetchMe();
  } catch (e) {
    await modulesReady;
    mount(appRoot, h("div", { class: "boot-splash" }, errorState(e, () => location.reload())));
    return;
  }
  if (me) {
    await applySession(me);
    startApp();
  } else {
    showLogin();
  }
}

onEvent("auth:lost", ({ code, message } = {}) => {
  const wasIn = isAuthenticated();
  if (!wasIn && code !== "logged_out" && appRoot.querySelector(".login-screen")) return; // already on login
  clearSession();
  setOfflineUserId(null);
  if (code === "logged_out") return showLogin();
  const key = AUTH_MESSAGES[code];
  showLogin(wasIn || key ? (key ? t(key) : message || t("core.auth.signed_out")) : undefined);
});

onEvent("auth:password_change", () => { if (isAuthenticated()) showForcedPasswordChange(); });

onEvent("lang:changed", () => {
  if (isAuthenticated()) {
    resetShell();
    refresh();
  }
});

if ("serviceWorker" in navigator && window.isSecureContext) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((e) => console.warn("service worker registration failed", e));
  });
}

boot();
