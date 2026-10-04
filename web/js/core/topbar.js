// Topbar: brand, active environment, connectivity, notifications bell, user menu.
import { h, mount, initials, safeHref } from "./dom.js";
import { t, getLang, setLang, localName, formatRelative } from "./i18n.js";
import { api } from "./api.js";
import { getUser, getCenter, getPrincipal } from "./state.js";
import { onEvent, emit } from "./events.js";
import { icon } from "../components/icons.js";
import { popover } from "../components/modal.js";
import { connectivityIndicator } from "../components/connectivity.js";
import { toastApiError } from "../components/toast.js";
import { logout, openChangePassword, exitSupport } from "../auth/session.js";
import { openSyncPanel } from "../offline/sync-panel.js";

const POLL_MS = 60000;
let pollTimer = null;

export function buildTopbar({ area, dept, onToggleNav }) {
  const center = getCenter();
  const user = getUser();
  const p = getPrincipal() || {};
  const homeHref = area === "admin" ? "#/admin" : p.center_wide || p.support_mode ? "#/center" : "#/";
  const brand = h("a", { class: "brand", href: homeHref },
    h("div", { class: "brand-mark" }, center?.logo_url ? h("img", { src: safeHref(center.logo_url), alt: "" }) : icon(area === "admin" ? "shield" : "hospital")),
    h("div", { class: "brand-text" },
      h("span", { class: "brand-name" }, area === "admin" ? t("core.portal.superadmin") : center?.name || t("core.app_name")),
      h("span", { class: "brand-sub" }, area === "admin" ? t("core.app_name") : t(`core.role.${p.role}`, { default: p.role || "" }))));

  const actions = h("div", { class: "topbar-actions" }, connectivityIndicator());
  if (p.center_id) actions.append(notificationsBell());
  actions.append(userMenuButton(user, p));

  return h("header", { class: "topbar" },
    h("button", { class: "btn btn-ghost btn-icon nav-toggle", type: "button", "aria-label": t("core.menu"), onClick: onToggleNav }, icon("menu")),
    brand,
    dept ? h("div", { class: "topbar-env" }, h("span", { class: "dot" }), h("span", { class: "topbar-env-label" }, localName(dept, dept.name))) : null,
    actions);
}

function userMenuButton(user, p) {
  const btn = h("button", { class: "user-chip", type: "button", "aria-haspopup": "menu" },
    h("span", { class: "avatar" }, initials(user?.name)), h("span", { class: "user-chip-name" }, user?.name || ""), icon("chevronDown"));
  btn.addEventListener("click", () => {
    const other = getLang() === "ar" ? "en" : "ar";
    let pop;
    const item = (ic, label, fn, cls) => h("button", { class: `menu-item ${cls || ""}`, type: "button", role: "menuitem",
      onClick: () => { pop.close(); fn(); } }, icon(ic), label);
    pop = popover(btn, [
      h("div", { class: "menu-head" }, h("strong", user?.name || ""), h("div", { class: "text-xs text-muted ltr" }, user?.email || ""),
        h("div", { class: "text-xs text-muted" }, t(`core.role.${p.role}`, { default: p.role || "" }))),
      item("globe", t(`core.lang.${other}`), () => setLang(other)),
      item("key", t("core.password.change"), openChangePassword),
      item("cloud", t("core.sync.title"), openSyncPanel),
      p.support_mode ? item("arrowLeft", t("core.support.exit"), () => exitSupport().catch(toastApiError)) : null,
      h("div", { class: "menu-sep" }),
      item("logout", t("core.logout"), () => logout(), "danger"),
    ].filter(Boolean));
  });
  return btn;
}

function notificationsBell() {
  const count = h("span", { class: "badge badge-count", hidden: true });
  const btn = h("button", { class: "btn btn-ghost btn-icon", type: "button", "aria-label": t("core.notifications.title") }, icon("bell"));
  const wrap = h("span", { class: "icon-btn-wrap" }, btn, count);

  const setCount = (n) => {
    count.hidden = !n;
    count.textContent = n > 99 ? "99+" : String(n);
  };
  const refresh = async () => {
    try {
      const res = await api.get("/notifications", { query: { per_page: 1 } });
      setCount(res.unread || 0);
    } catch { /* offline or no access: keep last count */ }
  };
  clearInterval(pollTimer);
  pollTimer = setInterval(() => wrap.isConnected ? refresh() : clearInterval(pollTimer), POLL_MS);
  refresh();
  const off = onEvent("notifications:changed", () => (wrap.isConnected ? refresh() : off()));

  btn.addEventListener("click", async () => {
    const list = h("div", { class: "notif-list" }, h("div", { class: "search-hint" }, t("core.loading")));
    const markAll = h("button", { class: "btn btn-link btn-sm", type: "button" }, t("core.notifications.mark_all"));
    const pop = popover(btn, h("div", h("div", { class: "notif-head" }, h("strong", t("core.notifications.title")), markAll), list),
      { className: "notif-panel" });
    markAll.addEventListener("click", async () => {
      try {
        await api.post("/notifications/read", {});
        setCount(0);
        list.querySelectorAll(".is-unread").forEach((x) => x.classList.remove("is-unread"));
      } catch (e) { toastApiError(e); }
    });
    try {
      const res = await api.get("/notifications", { query: { per_page: 20 } });
      setCount(res.unread || 0);
      if (!res.items?.length) return mount(list, h("div", { class: "state" }, icon("bell"), t("core.notifications.empty")));
      mount(list, res.items.map((n) => h("button", { class: ["notif-item", !n.is_read && "is-unread"], type: "button", onClick: async () => {
        const link = safeHref(n.link);
        if (!n.is_read) {
          try {
            await api.post("/notifications/read", { ids: [n.id] });
            emit("notifications:changed");
          } catch { /* non-critical */ }
        }
        pop.close();
        if (link && link.startsWith("#/")) location.hash = link;
      } },
      h("div", { class: "notif-title" }, n.title), n.body ? h("div", { class: "notif-body" }, n.body) : null,
      h("div", { class: "notif-time" }, formatRelative(n.created_at)))));
      pop.place();
    } catch (e) {
      mount(list, h("div", { class: "search-hint" }, e.message));
    }
  });
  return wrap;
}
