// Departments (activate module types, head doctor, settings) and clinics (contact, working hours, active).
import {
  api, h, t, mount, icon, dataTable, createForm, openModal, toast, toastSuccess, toastApiError, undoToast, confirmDialog,
  loadingState, errorState, emptyState, localName, safeColor, formatNumber, can,
} from "../core/index.js";
import { btn, formModal, conflictToast, usageBar } from "../admin/ui.js";

export const DAYS = ["sat", "sun", "mon", "tue", "wed", "thu", "fri"];
const DUR = "appointment_duration_minutes";

/** Merge the appointment duration into an existing settings object (other keys preserved). */
function withDuration(settings, minutes) {
  const out = { ...(settings || {}) };
  if (minutes == null || minutes === "") delete out[DUR];
  else out[DUR] = Number(minutes);
  return out;
}

/** On 409 *_in_use offer to deactivate instead. */
async function deleteOrDeactivate(url, obj, label, reload) {
  if (!(await confirmDialog({ message: t("center-admin.org.delete_confirm", { name: obj.name }), danger: true }))) return;
  try {
    const res = await api.del(url);
    reload();
    undoToast(res, { message: t("center-admin.org.deleted", { name: obj.name }), onUndone: reload });
  } catch (e) {
    if (e.status === 409 && /_in_use$/.test(e.code || "")) {
      if (obj.is_active && await confirmDialog({ title: t("center-admin.org.in_use_title"), message: t("center-admin.org.in_use", { name: obj.name }),
        confirmLabel: t("admin.ui.deactivate") })) {
        try {
          await api.patch(url, { is_active: false, version: obj.version });
          toastSuccess(t("center-admin.org.deactivated", { name: obj.name }));
          reload();
        } catch (e2) {
          if (e2.code === "version_conflict") conflictToast(reload);
          else toastApiError(e2);
        }
      } else if (!obj.is_active) toast(t("center-admin.org.in_use_inactive", { name: label }), { type: "warning" });
    } else toastApiError(e);
  }
}

const activePill = (on) => h("span", { class: `pill pill--${on ? "active" : "archived"}` }, t(on ? "admin.ui.active" : "admin.ui.inactive"));

// ---------------------------------------------------------------- departments (center level)
export async function departmentsTab(el, { centerLevel = true } = {}) {
  mount(el, loadingState());
  let list;
  let meta;
  try {
    [list, meta] = await Promise.all([api.get("/center/departments"), api.get("/center/departments/meta")]);
  } catch (e) {
    return mount(el, errorState(e, () => departmentsTab(el, { centerLevel })));
  }
  const reload = () => departmentsTab(el, { centerLevel });
  const available = meta.types.filter((x) => x.available);
  const add = centerLevel && can("settings.edit") && available.length ? h("button", { class: "btn btn-primary", type: "button",
    onClick: () => addDepartment(available, reload) }, icon("plus"), t("center-admin.dept.add")) : null;
  const L = meta.limits;
  mount(el, h("div", { class: "stack" },
    !centerLevel ? null : h("div", { class: "card card-body grid-3" },
      h("div", h("div", { class: "text-sm" }, t("admin.limit.max_departments")), usageBar(L.used_departments, L.max_departments)),
      h("div", h("div", { class: "text-sm" }, t("admin.limit.max_clinics")), usageBar(L.used_clinics, L.max_clinics)),
      h("div", h("div", { class: "text-sm" }, t("admin.limit.max_head_doctors")), usageBar(L.used_head_doctors, L.max_head_doctors))),
    h("div", { class: "row-between" }, h("p", { class: "text-muted" }, t("center-admin.dept.help")), add),
    list.items.length ? h("div", { class: "dept-grid" }, list.items.map((d) => deptCard(d, reload, centerLevel)))
      : emptyState({ icon: "building", title: t("center-admin.dept.none"), message: t("center-admin.dept.none_help") })));
}

function deptCard(d, reload, centerLevel = true) {
  return h("div", { class: "card card-body stack", style: { borderInlineStart: `4px solid ${safeColor(d.color) || "var(--line)"}` } },
    h("div", { class: "row-between" },
      h("div", { class: "row" }, h("span", { class: "adm-swatch", style: { background: safeColor(d.color) || "var(--neutral)" } }, icon(d.type.icon || "stethoscope")),
        h("div", h("strong", d.name), h("div", { class: "text-sm text-muted" }, `${localName(d.type, d.type.name_en)} · ${t(`admin.env.${d.environment}`)}`))),
      activePill(d.is_active)),
    d.module_active === false ? h("div", { class: "alert alert-warning" }, icon("lock"), h("div", t("center-admin.dept.module_off"))) : null,
    h("dl", { class: "kv" },
      h("dt", t("center-admin.dept.head")), h("dd", d.head ? d.head.name : t("center-admin.dept.no_head")),
      h("dt", t("center-admin.dept.clinics")), h("dd", formatNumber(d.clinic_count)),
      h("dt", t("center-admin.dept.duration")), h("dd", d.settings?.[DUR] ? t("center-admin.minutes", { n: d.settings[DUR] }) : "—")),
    d.can_manage && can("settings.edit") ? h("div", { class: "row" },
      btn(t("admin.ui.edit"), () => editDepartment(d, reload, centerLevel), { small: true, iconName: "edit" }),
      centerLevel && can("staff.edit") ? btn(t("center-admin.dept.set_head"), () => setHead(d, reload), { small: true, iconName: "shield" }) : null,
      centerLevel ? btn(t("admin.ui.delete"), () => deleteOrDeactivate(`/center/departments/${d.id}`, d, d.name, reload), { small: true, variant: "ghost", iconName: "trash" }) : null)
      : null);
}

function addDepartment(types, reload) {
  formModal({
    title: t("center-admin.dept.add"), columns: 1,
    intro: h("p", { class: "text-muted" }, t("center-admin.dept.add_help")),
    fields: [
      { name: "department_type_id", label: t("center-admin.dept.type"), type: "select", required: true, numeric: true,
        options: types.map((x) => ({ value: x.id, label: localName(x, x.name_en) })) },
      { name: "name", label: t("center-admin.dept.name"), help: t("center-admin.dept.name_help"), maxLength: 150 },
      { name: "color", label: t("center-admin.dept.color"), type: "color" },
    ],
    values: { color: "#2563eb" },
    submit: async (v) => {
      await api.post("/center/departments", v);
      toastSuccess(t("center-admin.dept.added"));
      reload();
    },
  });
}

/** Edit form; centerLevel adds the active switch. Used in center settings and the department environment. */
export function editDepartment(d, reload, centerLevel) {
  formModal({
    title: t("center-admin.dept.edit", { name: d.name }),
    fields: [
      { name: "name", label: t("center-admin.dept.name"), required: true, maxLength: 150 },
      { name: "color", label: t("center-admin.dept.color"), type: "color" },
      { name: "duration", label: t("center-admin.dept.duration"), type: "number", min: 5, max: 480, help: t("center-admin.dept.duration_help") },
      centerLevel ? { name: "is_active", label: t("center-admin.dept.active"), type: "checkbox", help: t("center-admin.dept.active_help") } : null,
    ].filter(Boolean),
    values: { ...d, duration: d.settings?.[DUR] },
    submit: async (v) => {
      const body = { name: v.name, color: v.color, settings: withDuration(d.settings, v.duration), version: d.version };
      if (centerLevel) body.is_active = v.is_active;
      try {
        await api.patch(`/center/departments/${d.id}`, body);
      } catch (e) {
        if (e.code === "version_conflict") conflictToast(reload);
        throw e;
      }
      toastSuccess(t("admin.ui.saved"));
      reload();
    },
  });
}

async function setHead(d, reload) {
  let managers;
  try {
    managers = (await api.get("/center/staff", { query: { role: "department_manager", department_id: d.id, status: "active", per_page: 100 } })).items;
  } catch (e) {
    return toastApiError(e);
  }
  formModal({
    title: t("center-admin.dept.head_for", { name: d.name }), columns: 1, size: "sm",
    intro: h("p", { class: "text-muted" }, managers.length ? t("center-admin.dept.head_help") : t("center-admin.dept.head_none_help")),
    fields: [{ name: "user_id", label: t("center-admin.dept.head"), type: "select", numeric: true,
      placeholder: t("center-admin.dept.no_head"), options: managers.map((u) => ({ value: u.id, label: u.name })) }],
    values: { user_id: d.head?.id },
    submit: async (v) => {
      await api.put(`/center/departments/${d.id}/head`, { user_id: v.user_id });
      toastSuccess(t("admin.ui.saved"));
      reload();
    },
  });
}

// ---------------------------------------------------------------- clinics
/** deptId: restrict to one department (department environment). */
export function clinicsTab(el, { deptId = null } = {}) {
  const table = dataTable({
    columns: [
      { key: "name", label: t("center-admin.clinic.name"), render: (c) => h("div", h("strong", c.name),
        deptId ? null : h("div", { class: "text-sm text-muted" }, c.department_name || "")) },
      { key: "location", label: t("center-admin.clinic.location"), render: (c) => c.location || "—" },
      { key: "contact", label: t("center-admin.clinic.contact"), render: (c) => h("div", { class: "text-sm" },
        c.phone ? h("div", { class: "ltr" }, c.phone) : null, c.email ? h("div", { class: "ltr" }, c.email) : null) },
      { key: "hours", label: t("center-admin.clinic.hours"), render: (c) => hoursSummary(c.working_hours) },
      { key: "is_active", label: t("center-admin.clinic.status"), render: (c) => activePill(c.is_active) },
      { key: "actions", label: "", class: "actions", render: (c) => c.can_manage && can("settings.edit") ? h("div", { class: "btn-group" },
        h("button", { class: "btn btn-sm", type: "button", onClick: () => editClinic(c, deptId, table.reload) }, icon("edit"), t("admin.ui.edit")),
        h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": t("admin.ui.delete"),
          onClick: () => deleteOrDeactivate(`/center/clinics/${c.id}`, c, c.name, table.reload) }, icon("trash"))) : null },
    ],
    fetch: () => api.get("/center/clinics", { query: { department_id: deptId } }),
    search: { placeholder: t("center-admin.clinic.search") },
    toolbar: can("settings.edit") ? [h("button", { class: "btn btn-primary", type: "button",
      onClick: () => editClinic(null, deptId, table.reload) }, icon("plus"), t("center-admin.clinic.add"))] : [],
    empty: { icon: "hospital", title: t("center-admin.clinic.none") },
  });
  mount(el, table.el);
  return table;
}

function hoursSummary(wh) {
  const days = DAYS.filter((d) => (wh?.[d] || []).length);
  if (!days.length) return h("span", { class: "text-muted" }, "—");
  return h("div", { class: "text-sm" }, days.map((d) => h("div", h("span", `${t(`center-admin.day.${d}`)}: `),
    h("span", { class: "ltr" }, wh[d].map((iv) => `${iv[0]}–${iv[1]}`).join(", ")))));
}

async function editClinic(c, deptId, reload) {
  let depts = [];
  if (!c && !deptId) {
    try {
      depts = (await api.get("/center/departments")).items.filter((d) => d.can_manage);
    } catch (e) {
      return toastApiError(e);
    }
  }
  const hours = hoursEditor(c?.working_hours || {});
  const fields = [
    !c && !deptId ? { name: "department_id", label: t("center-admin.clinic.department"), type: "select", required: true, numeric: true,
      options: depts.map((d) => ({ value: d.id, label: d.name })) } : null,
    { name: "name", label: t("center-admin.clinic.name"), required: true, maxLength: 150 },
    { name: "location", label: t("center-admin.clinic.location"), help: t("center-admin.clinic.location_help"), maxLength: 200 },
    { name: "phone", label: t("center-admin.clinic.phone"), type: "tel" },
    { name: "email", label: t("center-admin.clinic.email"), type: "email" },
    { name: "duration", label: t("center-admin.dept.duration"), type: "number", min: 5, max: 480, help: t("center-admin.clinic.duration_help") },
    { name: "is_active", label: t("center-admin.clinic.active"), type: "checkbox", help: t("center-admin.clinic.active_help") },
    { name: "notes", label: t("center-admin.clinic.notes"), type: "textarea", span: 2, rows: 2 },
  ].filter(Boolean);
  let modal;
  const form = createForm({
    fields,
    values: c ? { ...c, duration: c.settings?.[DUR] } : { is_active: true },
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      const body = { name: v.name, location: v.location, phone: v.phone, email: v.email, notes: v.notes, is_active: v.is_active,
        working_hours: hours.value(), settings: withDuration(c?.settings, v.duration) };
      try {
        if (c) await api.patch(`/center/clinics/${c.id}`, { ...body, version: c.version });
        else await api.post("/center/clinics", { ...body, department_id: deptId || v.department_id });
      } catch (e) {
        if (e.code === "version_conflict") conflictToast(reload);
        throw e;
      }
      modal.close();
      toastSuccess(t("admin.ui.saved"));
      reload();
    },
  });
  form.el.querySelector(".form-grid").append(h("div", { class: "field span-2", dataset: { field: "working_hours" } },
    h("label", t("center-admin.clinic.hours")), hours.el));
  modal = openModal({ title: c ? t("center-admin.clinic.edit", { name: c.name }) : t("center-admin.clinic.add"), size: "lg", body: form.el });
}

/** Weekly hours editor -> {"sat": [["09:00","13:00"], ...], ...}. */
export function hoursEditor(initial) {
  const rows = {};
  const make = (day, list) => {
    const wrap = h("div", { class: "adm-hours-intervals" });
    const addBtn = h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { addIv(["09:00", "17:00"]); } },
      icon("plus"), t("center-admin.hours.add"));
    const closed = h("span", { class: "text-sm text-muted" }, t("center-admin.hours.closed"));
    function refresh() {
      closed.hidden = wrap.querySelectorAll(".adm-hours-interval").length > 0;
      addBtn.hidden = wrap.querySelectorAll(".adm-hours-interval").length >= 4;
    }
    function addIv([a, b]) {
      const s = h("input", { class: "input ltr", type: "time", value: a, "aria-label": t("center-admin.hours.from") });
      const e = h("input", { class: "input ltr", type: "time", value: b, "aria-label": t("center-admin.hours.to") });
      const iv = h("span", { class: "adm-hours-interval" }, s, "–", e,
        h("button", { class: "btn btn-sm btn-ghost btn-icon", type: "button", "aria-label": t("admin.ui.delete"),
          onClick: () => { iv.remove(); refresh(); } }, icon("x")));
      wrap.insertBefore(iv, closed);
      refresh();
    }
    wrap.append(closed, addBtn);
    (list || []).forEach(addIv);
    refresh();
    rows[day] = { wrap, addIv, clear: () => { wrap.querySelectorAll(".adm-hours-interval").forEach((x) => x.remove()); refresh(); } };
    return h("div", { class: "adm-hours-row" }, h("strong", t(`center-admin.day.${day}`)), wrap);
  };
  const read = (day) => [...rows[day].wrap.querySelectorAll(".adm-hours-interval")].map((iv) => {
    const [a, b] = iv.querySelectorAll("input");
    return [a.value, b.value];
  }).filter(([a, b]) => a && b);
  const copy = h("button", { class: "btn btn-sm", type: "button", onClick: () => {
    const first = read("sat");
    DAYS.slice(1).forEach((d) => { if (d !== "fri") { rows[d].clear(); first.forEach((iv) => rows[d].addIv(iv)); } });
  } }, t("center-admin.hours.copy_sat"));
  const el = h("div", { class: "adm-hours card card-body" }, DAYS.map((d) => make(d, initial[d])), h("div", { class: "row" }, copy));
  return {
    el,
    value() {
      const out = {};
      DAYS.forEach((d) => {
        const v = read(d);
        if (v.length) out[d] = v;
      });
      return out;
    },
  };
}
