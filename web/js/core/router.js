// Hash router. URLs:
//   #/admin/<path>          superadmin portal (area "admin")
//   #/center/<path>         center-wide area (area "center")
//   #/d/<deptId>/<path>     isolated department environment (area "department")
// Guards: portal per area, department visibility (out of scope -> not found), route perm (-> forbidden).
import { emit } from "./events.js";
import { getRoutes, envMatches } from "./registry.js";
import { getPortal, getDepartments, getDepartment } from "./state.js";
import { allowed } from "./perm.js";

let handler = null;
let current = null;

export function parseHash(hash = location.hash) {
  const raw = hash.replace(/^#\/?/, "");
  const [p, qs = ""] = raw.split("?");
  const segments = p.split("/").filter(Boolean).map((s) => {
    try { return decodeURIComponent(s); } catch { return s; }
  });
  return { segments, query: Object.fromEntries(new URLSearchParams(qs)) };
}

/** Build "#/..." from a path ("/center/patients") and optional query object. */
export function href(path, query) {
  const qs = query ? new URLSearchParams(Object.entries(query).filter(([, v]) => v != null && v !== "")).toString() : "";
  return `#/${String(path).replace(/^[#/]+/, "")}${qs ? `?${qs}` : ""}`;
}

/** Link inside a department environment: deptHref(3, "patients/12") -> "#/d/3/patients/12". */
export const deptHref = (deptId, sub = "", query) => href(`d/${deptId}${sub ? `/${String(sub).replace(/^\/+/, "")}` : ""}`, query);
/** Area-relative link for the current context (department-aware): areaHref(ctx, "patients"). */
export const areaHref = (ctx, sub = "", query) => (ctx.area === "department" ? deptHref(ctx.dept.id, sub, query)
  : href(`${ctx.area}/${String(sub).replace(/^\/+/, "")}`, query));

export function navigate(path, { replace = false, query } = {}) {
  const target = path.startsWith("#") ? path : href(path, query);
  if (replace) {
    history.replaceState(null, "", target);
    resolve();
  } else if (location.hash === target) {
    resolve();
  } else {
    location.hash = target;
  }
}

/** Default landing path for the signed-in portal. */
export function homePath() {
  const portal = getPortal();
  if (portal === "superadmin") return "/admin";
  if (portal === "center") return "/center";
  const d = getDepartments()[0];
  return d ? `/d/${d.id}` : "/d/0"; // no department in scope: shell shows an explanatory empty state
}

function compile(pattern) {
  return pattern ? pattern.split("/") : [];
}

function matchPath(pattern, rest) {
  const parts = compile(pattern);
  if (parts.length !== rest.length) return null;
  const params = {};
  for (let i = 0; i < parts.length; i++) {
    if (parts[i].startsWith(":")) params[parts[i].slice(1)] = rest[i];
    else if (parts[i] !== rest[i]) return null;
  }
  return params;
}

// specificity: env-specific beats "*", static segments beat params
const score = (r) => (r.env === "*" ? 0 : 1000) + compile(r.path).filter((p) => !p.startsWith(":")).length;

export function resolveRoute({ segments, query }) {
  const portal = getPortal();
  const [head, ...tail] = segments;
  let area;
  let rest = tail;
  let dept = null;
  if (head === "admin") area = "admin";
  else if (head === "center") area = "center";
  else if (head === "d") {
    area = "department";
    dept = getDepartment(tail[0]);
    rest = tail.slice(1);
    if (!dept) return { status: "notfound", area, query, dept: null };
  } else return { status: "home" };

  if (area === "admin" && portal !== "superadmin") return { status: "home" };
  if (area === "center" && portal !== "center") return { status: "home" };
  if (area === "department" && portal === "superadmin") return { status: "home" };

  const candidates = getRoutes().filter((r) => r.area === area && (area !== "department" || envMatches(r.env, dept.environment)))
    .sort((a, b) => score(b) - score(a));
  for (const r of candidates) {
    const params = matchPath(r.path, rest);
    if (!params) continue;
    if (!allowed(r.perm)) return { status: "forbidden", area, route: r, params, query, dept };
    return { status: "ok", area, route: r, params, query, dept, path: rest.join("/") };
  }
  return { status: "notfound", area, query, dept };
}

function resolve() {
  if (!handler) return;
  const parsed = parseHash();
  const m = resolveRoute(parsed);
  if (m.status === "home") {
    history.replaceState(null, "", href(homePath()));
    return resolve();
  }
  current = m;
  handler(m);
  emit("route:changed", m);
}

/** Start routing; handler(match) renders. Call again after login to re-resolve. */
export function startRouter(h) {
  const first = !handler;
  handler = h;
  if (first) window.addEventListener("hashchange", resolve);
  resolve();
}

export function stopRouter() {
  handler = null;
  window.removeEventListener("hashchange", resolve);
}

export const currentRoute = () => current;
export const refresh = () => resolve();
