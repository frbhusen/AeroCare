// Schedule page: day / week views per clinic & doctor (week collapses to a list on phones).
import {
  api, h, t, mount, icon, todayISO, formatDate, toastApiError, printElement, onEvent, loadingState, errorState,
  emptyState, offlineCopyBanner, debounce,
} from "../core/index.js";
import { loadMeta, loadDoctors, areaClinics, pill, typeLabel, addDays, weekStart, weekdayName, timeRange } from "./common.js";
import { openAppointmentForm, openWalkIn } from "./form.js";
import { openAppointment } from "./detail.js";
import { scheduleNode } from "./print.js";
import { openReminders } from "./reminders.js";

const ACTIVE = "scheduled,arrived,in_progress,completed";
const isPhone = () => window.matchMedia("(max-width: 640px)").matches;

export async function renderSchedule(ctx) {
  ctx.setTitle?.(t("appointments.title"));
  const meta = await loadMeta();
  const clinics = areaClinics(meta, ctx);
  const q = ctx.query || {};
  const state = {
    date: /^\d{4}-\d{2}-\d{2}$/.test(q.date || "") ? q.date : todayISO(),
    view: q.view === "week" || q.view === "day" ? q.view : (isPhone() ? "day" : "week"),
    clinic_id: q.clinic_id && clinics.some((c) => String(c.id) === String(q.clinic_id)) ? String(q.clinic_id)
      : (meta.is_doctor ? String(meta.own_clinic_id || "") : (clinics.length === 1 ? String(clinics[0].id) : "")),
    doctor_id: "",
    active_only: false,
  };
  let data = null;

  // ---- toolbar
  const dateInput = h("input", { class: "input appt-date-input", type: "date", value: state.date, "aria-label": t("appointments.field.date") });
  const viewBtns = ["day", "week"].map((v) => h("button", { class: "btn btn-sm", type: "button", "aria-pressed": "false",
    onClick: () => { state.view = v; load(); } }, t(`appointments.view.${v}`)));
  const clinicSel = h("select", { class: "select", "aria-label": t("appointments.filter.clinic") },
    h("option", { value: "" }, t("appointments.filter.all_clinics")),
    clinics.map((c) => h("option", { value: String(c.id) }, ctx.area === "department" ? c.name : `${c.name} · ${c.department_name}`)));
  clinicSel.value = state.clinic_id;
  const doctorSel = h("select", { class: "select", "aria-label": t("appointments.filter.doctor") });
  const activeBox = h("input", { type: "checkbox" });
  const title = h("h2", { class: "appt-range-title" });

  async function fillDoctors() {
    mount(doctorSel, h("option", { value: "" }, t("appointments.filter.all_doctors")));
    doctorSel.hidden = !state.clinic_id || meta.is_doctor;
    if (!state.clinic_id || meta.is_doctor) return;
    try {
      const docs = await loadDoctors(state.clinic_id);
      docs.forEach((d) => doctorSel.append(h("option", { value: String(d.id) }, d.name)));
      doctorSel.value = state.doctor_id;
    } catch (e) { toastApiError(e); }
  }

  const shift = (dir) => { state.date = addDays(state.date, dir * (state.view === "week" ? 7 : 1)); load(); };
  dateInput.addEventListener("change", () => { if (dateInput.value) { state.date = dateInput.value; load(); } });
  clinicSel.addEventListener("change", () => { state.clinic_id = clinicSel.value; state.doctor_id = ""; fillDoctors(); load(); });
  doctorSel.addEventListener("change", () => { state.doctor_id = doctorSel.value; load(); });
  activeBox.addEventListener("change", () => { state.active_only = activeBox.checked; load(); });

  const can = meta.can || {};
  const actions = h("div", { class: "page-actions" },
    can.create ? h("button", { class: "btn btn-primary", type: "button", onClick: () => openNew() }, icon("plus"), t("appointments.new")) : null,
    can.create ? h("button", { class: "btn", type: "button", onClick: () => openWalkIn({ ctx, meta, onSaved: (a) => { load(); if (a) openAppointment({ ctx, meta, id: a.id, onChanged: load }); } }) },
      icon("user"), t("appointments.walk_in")) : null,
    can.create ? h("button", { class: "btn", type: "button", onClick: () => openNew({}, true) }, icon("refresh"), t("appointments.recurring")) : null,
    h("button", { class: "btn", type: "button", onClick: () => openReminders({ clinicId: state.clinic_id || undefined }) },
      icon("bell"), t("appointments.reminders.button")),
    h("button", { class: "btn", type: "button", onClick: printSchedule }, icon("printer"), t("appointments.print")));

  const toolbar = h("div", { class: "appt-toolbar no-print" },
    h("div", { class: "row appt-nav" },
      h("button", { class: "btn btn-icon btn-sm", type: "button", "aria-label": t("appointments.prev"), onClick: () => shift(-1) }, h("span", { class: "appt-flip" }, "‹")),
      h("button", { class: "btn btn-sm", type: "button", onClick: () => { state.date = todayISO(); load(); } }, t("appointments.today")),
      h("button", { class: "btn btn-icon btn-sm", type: "button", "aria-label": t("appointments.next"), onClick: () => shift(1) }, h("span", { class: "appt-flip" }, "›")),
      dateInput, h("div", { class: "btn-group appt-view-toggle", role: "group" }, viewBtns)),
    h("div", { class: "row appt-filters" },
      meta.is_doctor || clinics.length < 2 ? null : clinicSel, doctorSel,
      h("label", { class: "check text-sm" }, activeBox, t("appointments.filter.active_only"))));

  const content = h("div", { class: "appt-content" }, loadingState());
  const page = h("div", { class: "page appt-page" },
    h("div", { class: "page-header" }, h("h1", t("appointments.title")), actions),
    toolbar, title, content);

  function openNew(defaults = {}, recurring = false) {
    openAppointmentForm({ ctx, meta, recurring,
      defaults: { date: state.date, clinic_id: state.clinic_id || undefined, doctor_id: state.doctor_id || undefined, ...defaults },
      onSaved: (a) => { if (a?.local_date && a.local_date !== state.date && state.view === "day") state.date = a.local_date; load(); } });
  }
  const openDetail = (a) => openAppointment({ ctx, meta, id: a.id, onChanged: load });

  let seq = 0;
  async function load() {
    const my = ++seq;
    dateInput.value = state.date;
    viewBtns.forEach((b, i) => {
      const on = ["day", "week"][i] === state.view;
      b.classList.toggle("btn-primary", on);
      b.setAttribute("aria-pressed", String(on));
    });
    const query = { date: state.date, view: state.view };
    if (ctx.area === "department" && ctx.dept) query.department_id = ctx.dept.id;
    if (state.clinic_id) query.clinic_id = state.clinic_id;
    if (state.doctor_id) query.doctor_id = state.doctor_id;
    if (state.active_only) query.status = ACTIVE;
    if (!data) mount(content, loadingState());
    try {
      const res = await api.get("/appointments/schedule", { query, cache: true });
      if (my !== seq) return;
      data = res;
      title.textContent = res.view === "week"
        ? `${formatDate(res.start_date)} – ${formatDate(res.end_date, { year: "always" })}`
        : `${weekdayName(res.start_date)} ${formatDate(res.start_date, { year: "always" })}`;
      mount(content, offlineCopyBanner(res), res.view === "week" ? weekView(res) : dayView(res.days[0]));
    } catch (e) {
      if (my !== seq) return;
      mount(content, errorState(e, load));
    }
  }

  function card(a) {
    return h("button", { class: `appt-card appt-card--${a.status}`, type: "button", onClick: () => openDetail(a) },
      h("div", { class: "appt-card-time" }, timeRange(a), pill(a.status)),
      h("div", { class: "appt-card-patient" }, a.patient.name || "—"),
      h("div", { class: "appt-card-meta text-sm text-muted" },
        [state.clinic_id ? null : a.clinic.name, a.doctor?.name, typeLabel(a.appointment_type)].filter(Boolean).join(" · ")),
      a.is_walk_in ? h("span", { class: "badge" }, t("appointments.walk_in_badge")) : null);
  }

  function weekView(res) {
    return h("div", { class: "appt-week" }, res.days.map((d) => h("section", { class: ["appt-day", d.date === todayISO() && "is-today"] },
      h("header", { class: "appt-day-head" },
        h("button", { class: "btn btn-link btn-sm", type: "button", onClick: () => { state.date = d.date; state.view = "day"; load(); } },
          h("strong", weekdayName(d.date)), " ", h("span", { class: "ltr" }, formatDate(d.date))),
        can.create ? h("button", { class: "btn btn-ghost btn-icon btn-sm no-print", type: "button", "aria-label": t("appointments.new"),
          onClick: () => openNew({ date: d.date }) }, icon("plus")) : null),
      d.items.length ? h("div", { class: "appt-day-list" }, d.items.map(card))
        : h("div", { class: "appt-day-empty text-muted text-sm" }, "—"))));
  }

  function dayView(d) {
    if (!d || !d.items.length) {
      return emptyState({ icon: "calendar", title: t("appointments.empty_day"),
        action: can.create ? h("button", { class: "btn btn-primary", type: "button", onClick: () => openNew() }, icon("plus"), t("appointments.new")) : null });
    }
    const transitions = meta.transitions || {};
    return h("div", { class: "card" }, h("table", { class: "table table-stack appt-table" },
      h("thead", h("tr", [t("appointments.field.time"), t("appointments.field.patient"), t("appointments.field.clinic"),
        t("appointments.field.doctor"), t("appointments.field.type"), t("appointments.field.status"), ""].map((x) => h("th", x)))),
      h("tbody", d.items.map((a) => {
        let quick = null;
        if (can.edit) {
          const trans = transitions[a.status] || [];
          if (a.status === "scheduled" && trans.includes("arrived")) {
            quick = h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: (e) => { e.stopPropagation(); quickStatus(a, "arrived", e.currentTarget); } },
              t("appointments.action.arrived"));
          } else if (a.status === "arrived" && trans.includes("in_progress")) {
            quick = h("button", { class: "btn btn-sm btn-accent", type: "button", onClick: (e) => { e.stopPropagation(); quickStatus(a, "in_progress", e.currentTarget); } },
              t("appointments.action.in_progress"));
          } else if (a.status === "in_progress" && trans.includes("completed")) {
            quick = h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: (e) => { e.stopPropagation(); quickStatus(a, "completed", e.currentTarget); } },
              t("appointments.action.completed"));
          }
        }
        const tr = h("tr", { class: `appt-row appt-row--${a.status}`, tabindex: "0" },
          h("td", { "data-label": t("appointments.field.time") }, timeRange(a)),
          h("td", { "data-label": t("appointments.field.patient") }, h("strong", a.patient.name || "—"),
            a.patient.code ? h("div", { class: "text-sm text-muted ltr" }, a.patient.code) : null),
          h("td", { "data-label": t("appointments.field.clinic") }, a.clinic.name, a.location ? h("div", { class: "text-sm text-muted" }, a.location) : null),
          h("td", { "data-label": t("appointments.field.doctor") }, a.doctor?.name || "—"),
          h("td", { "data-label": t("appointments.field.type") }, typeLabel(a.appointment_type), a.reason ? h("div", { class: "text-sm text-muted" }, a.reason) : null),
          h("td", { "data-label": t("appointments.field.status") }, pill(a.status),
            a.is_walk_in ? h("span", { class: "badge" }, t("appointments.walk_in_badge")) : null),
          h("td", { class: "actions" }, quick));
        tr.addEventListener("click", () => openDetail(a));
        tr.addEventListener("keydown", (e) => { if (e.key === "Enter") openDetail(a); });
        return tr;
      }))));
  }

  async function quickStatus(a, status, btn) {
    btn.disabled = true;
    try {
      await api.post(`/appointments/${a.id}/status`, { status, version: a.version });
      load();
    } catch (e) {
      if (e.code === "version_conflict") load();
      toastApiError(e);
    } finally { btn.disabled = false; }
  }

  function printSchedule() {
    if (!data) return;
    const parts = [];
    if (ctx.area === "department" && ctx.dept) parts.push(ctx.dept.name);
    if (state.clinic_id) parts.push(clinicSel.selectedOptions[0]?.textContent);
    if (state.doctor_id) parts.push(doctorSel.selectedOptions[0]?.textContent);
    parts.push(title.textContent);
    printElement(scheduleNode(data, parts.filter(Boolean).join(" · ")));
  }

  fillDoctors();
  load();
  const timer = setInterval(() => { if (document.visibilityState === "visible") load(); }, 60000);
  const off = onEvent("sync:applied", debounce(load, 300));
  ctx.onLeave = () => { clearInterval(timer); off?.(); };
  if (q.id && /^\d+$/.test(String(q.id))) openAppointment({ ctx, meta, id: Number(q.id), onChanged: load });
  return page;
}
