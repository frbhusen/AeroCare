// Permission helpers mirroring the principal JSON from /auth/me.
// UI HINTS ONLY (hide/disable controls). The API is the authority: always handle 403/404.
import { getPrincipal, getPortal } from "./state.js";

const p = () => getPrincipal() || {};
const perms = () => new Set(p().permissions || []);

/** can("patients.view") */
export const can = (perm) => !perm || perms().has(perm);
/** canAny(["billing.view", "reports.view"]) */
export const canAny = (list) => !list || !list.length || list.some((x) => perms().has(x));
export const canAll = (list) => !list || list.every((x) => perms().has(x));
/** Check a route/menu `perm` value: string, array (any-of), or undefined. */
export const allowed = (perm) => (Array.isArray(perm) ? canAny(perm) : can(perm));

export const isSuperadmin = () => !!p().is_superadmin;
export const isSupportMode = () => !!p().support_mode;
export const isCenterWide = () => !!p().center_wide;
export const role = () => p().role || null;
export const portal = () => getPortal();

/** Clinic in the principal's scope. */
export const canClinic = (clinicId) => (p().clinic_ids || []).includes(Number(clinicId));
/** Department-level (manage) scope: managers, department receptionists, center-wide. */
export const managesDepartment = (deptId) => (p().managed_department_ids || []).includes(Number(deptId));
/** Department visible in navigation. */
export const seesDepartment = (deptId) => (p().visible_department_ids || []).includes(Number(deptId));
