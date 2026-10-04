// Login screen. Platform branding from GET /api/v1/platform/branding (admin module) when available;
// built-in branding otherwise. Center branding applies only after login.
import { h, mount, safeHref, safeColor } from "../core/dom.js";
import { t, getLang, setLang } from "../core/i18n.js";
import { api } from "../core/api.js";
import { icon } from "../components/icons.js";
import { createForm } from "../components/form.js";
import { login } from "./session.js";

let brandingCache;

async function platformBranding() {
  if (brandingCache !== undefined) return brandingCache;
  try {
    const b = await api.get("/platform/branding", { silent401: true });
    brandingCache = b && typeof b === "object" ? (b.branding || b) : null;
  } catch {
    brandingCache = null; // endpoint not available: built-in branding
  }
  return brandingCache;
}

/** renderLogin(root, {message, onLoggedIn(me)}) */
export async function renderLogin(root, { message, onLoggedIn } = {}) {
  document.body.removeAttribute("data-portal");
  document.body.removeAttribute("data-env");
  document.title = t("core.app_name");
  const b = await platformBranding();
  const name = (getLang() === "ar" ? b?.name_ar : b?.name_en) || b?.name || b?.platform_name || t("core.app_name");
  const tagline = (getLang() === "ar" ? b?.tagline_ar : b?.tagline_en) || b?.tagline || b?.login_message || t("core.login.tagline");
  const logo = safeHref(b?.logo_url);
  const color = safeColor(b?.primary_color);

  const alert = h("div", { class: "alert alert-danger", role: "alert", hidden: !message }, icon("alert"), h("div", message || ""));
  const form = createForm({
    columns: 1,
    fields: [
      { name: "email", label: t("core.login.email"), type: "email", required: true, autocomplete: "username", attrs: { autofocus: true, dir: "ltr" } },
      { name: "password", label: t("core.login.password"), type: "password", required: true, autocomplete: "current-password", attrs: { dir: "ltr" } },
    ],
    submitLabel: t("core.login.submit"),
    onSubmit: async (v) => {
      alert.hidden = true;
      try {
        const me = await login(v.email, v.password);
        if (onLoggedIn) onLoggedIn(me);
      } catch (e) {
        const msg = e.code === "invalid_credentials" ? t("core.login.invalid")
          : e.code === "rate_limited" ? t("core.login.rate_limited")
            : e.code === "center_inactive" ? t("core.error.center_inactive") : e.message;
        mount(alert, icon("alert"), h("div", msg));
        alert.hidden = false;
      }
    },
  });
  form.submitButton.classList.add("btn-block", "btn-lg");

  const other = getLang() === "ar" ? "en" : "ar";
  mount(root, h("div", { class: "login-screen", style: color ? { "--c-ocean": color } : null },
    h("button", { class: "btn btn-sm login-lang", type: "button", onClick: () => { setLang(other); renderLogin(root, { message, onLoggedIn }); } },
      icon("globe"), t(`core.lang.${other}`)),
    h("main", { class: "login-card" },
      h("div", { class: "login-brand" },
        h("div", { class: "brand-mark" }, logo ? h("img", { src: logo, alt: "" }) : icon("hospital")),
        h("h1", name), h("p", tagline)),
      alert,
      form.el,
      h("div", { class: "login-foot" }, t("core.login.foot")))));
  root.querySelector("input[name=email]")?.focus();
}
