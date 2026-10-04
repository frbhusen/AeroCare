// Module registry. Each module's web/js/<name>/index.js exports register(registry) and calls:
//   registry.i18n({en: {...}, ar: {...}})
//   registry.route({area, path, render, perm, env, title})
//   registry.menu({area, key, path, label, icon, perm, env, order, section})
//   registry.widget({area, key, render, perm, env, order, title, span})
// Areas: "admin" (superadmin portal, URL #/admin/<path>), "center" (center-wide, #/center/<path>),
//        "department" (isolated department environment, #/d/<deptId>/<path>).
// env: "*" (default) or an array of department environments (dentistry, dermatology, ophthalmology,
//      radiology, laboratory, pharmacy, generic) - applies to the department area only.
import { registerDictionary } from "./i18n.js";

export const AREAS = ["admin", "center", "department"];
const routes = [];
const menus = [];
const widgets = [];

function checkArea(area, what) {
  if (!AREAS.includes(area)) throw new Error(`${what}: unknown area "${area}"`);
}
const normPath = (p) => String(p || "").replace(/^\/+|\/+$/g, "");
const envList = (env) => (env == null || env === "*" ? "*" : Array.isArray(env) ? env : [env]);

/** Does an env filter match a department environment? */
export const envMatches = (env, deptEnv) => env === "*" || (deptEnv != null && env.includes(deptEnv));

export const registry = {
  i18n(dict) {
    registerDictionary(dict);
  },

  /**
   * route({area, path: "patients/:id", render: (ctx) => Node | Promise<Node> | void, perm, env, title, placeholder})
   * ctx = {el, area, path, params, query, dept, env, navigate, setTitle}. render may fill ctx.el and/or return
   * a Node; it may return {node, cleanup} or set ctx.onLeave = fn for teardown.
   */
  route(r) {
    checkArea(r.area, "route");
    if (typeof r.render !== "function") throw new Error("route: render() required");
    const def = { ...r, path: normPath(r.path), env: envList(r.env), placeholder: !!r.placeholder };
    const i = routes.findIndex((x) => x.area === def.area && x.path === def.path && sameEnv(x.env, def.env));
    if (i >= 0) {
      if (!routes[i].placeholder && !def.placeholder) console.warn(`route ${def.area}:${def.path} registered twice; last wins`);
      if (routes[i].placeholder || !def.placeholder) routes[i] = def;
      return;
    }
    routes.push(def);
  },

  /** menu({area, key, path, label (i18n key), icon, perm, env, order, section, placeholder}) */
  menu(m) {
    checkArea(m.area, "menu");
    if (!m.key) throw new Error("menu: key required");
    const def = { order: 50, ...m, path: normPath(m.path), env: envList(m.env), placeholder: !!m.placeholder };
    const i = menus.findIndex((x) => x.area === def.area && x.key === def.key && sameEnv(x.env, def.env));
    if (i >= 0) {
      if (menus[i].placeholder || !def.placeholder) menus[i] = def;
      return;
    }
    menus.push(def);
  },

  /** widget({area: "center"|"department"|"admin", key, title (i18n key), render: (el, ctx) => void, perm, env, order, span: 1|2}) */
  widget(w) {
    checkArea(w.area, "widget");
    if (!w.key || typeof w.render !== "function") throw new Error("widget: key and render required");
    const def = { order: 50, span: 1, ...w, env: envList(w.env) };
    const i = widgets.findIndex((x) => x.area === def.area && x.key === def.key);
    if (i >= 0) widgets[i] = def;
    else widgets.push(def);
  },
};

function sameEnv(a, b) {
  if (a === "*" || b === "*") return a === b;
  return a.length === b.length && a.every((x) => b.includes(x));
}

export const getRoutes = () => routes;
export const menusFor = (area, deptEnv) => menus.filter((m) => m.area === area && (area !== "department" || envMatches(m.env, deptEnv)))
  .sort((a, b) => a.order - b.order);
export const widgetsFor = (area, deptEnv) => widgets.filter((w) => w.area === area && (area !== "department" || envMatches(w.env, deptEnv)))
  .sort((a, b) => a.order - b.order);
