// Session state from /auth/me. Read-only for modules (use the getters); the shell updates it.
// Nothing here is authoritative: the server re-checks every request.

const listeners = new Set();
const state = {
  me: null, // full /auth/me payload
  user: null,
  principal: null,
  portal: null, // "superadmin" | "center" | "department"
  center: null,
  departments: [],
  clinics: [],
  csrf: null,
  activeDepartmentId: null,
};

export function setSession(me) {
  state.me = me || null;
  state.user = me?.user || null;
  state.principal = me?.principal || null;
  state.portal = me?.portal || null;
  state.center = me?.center || null;
  state.departments = me?.departments || [];
  state.clinics = me?.clinics || [];
  state.csrf = me?.csrf_token || null;
  if (!state.departments.some((d) => d.id === state.activeDepartmentId)) state.activeDepartmentId = null;
  notify();
}

export function clearSession() {
  setSession(null);
}

export function setActiveDepartment(id) {
  const next = id == null ? null : Number(id);
  if (next === state.activeDepartmentId) return;
  state.activeDepartmentId = next;
  notify();
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of [...listeners]) {
    try {
      fn(state);
    } catch (e) {
      console.error("state listener failed", e);
    }
  }
}

export const getState = () => state;
export const getUser = () => state.user;
export const getPrincipal = () => state.principal;
export const getPortal = () => state.portal;
export const getCenter = () => state.center;
export const getCsrf = () => state.csrf;
export const setCsrf = (token) => { state.csrf = token || null; };
export const isAuthenticated = () => !!state.user;
export const getDepartments = () => state.departments;
export const getClinics = () => state.clinics;
export const getDepartment = (id) => state.departments.find((d) => d.id === Number(id)) || null;
export const getClinic = (id) => state.clinics.find((c) => c.id === Number(id)) || null;
export const clinicsOf = (departmentId) => state.clinics.filter((c) => c.department_id === Number(departmentId));
export const getActiveDepartment = () => getDepartment(state.activeDepartmentId);
