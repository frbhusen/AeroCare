// Appointment detail drawer: status buttons, edit, WhatsApp reminder, print slip, delete + undo.
import {
  api, h, t, mount, openDrawer, openModal, confirmDialog, toastSuccess, toastApiError, deleteWithUndo, icon,
  formatDate, formatDateTime, printElement, getLang, loadingState, errorState,
} from "../core/index.js";
import { pill, typeLabel, timeRange, weekdayName, conflictBlock } from "./common.js";
import { openAppointmentForm } from "./form.js";
import { slipNode } from "./print.js";

const ACTION_ORDER = ["arrived", "in_progress", "completed", "no_show", "cancelled", "scheduled"];
const ACTION_STYLE = { arrived: "btn-primary", in_progress: "", completed: "", no_show: "", cancelled: "btn-danger", scheduled: "btn-ghost" };

/** openAppointment({ctx, meta, id, onChanged}) */
export function openAppointment({ ctx, meta, id, onChanged }) {
  const body = h("div", { class: "appt-detail" }, loadingState());
  const drawer = openDrawer({ title: t("appointments.title"), body });
  let appt = null;

  async function load() {
    mount(body, loadingState());
    try {
      appt = await api.get(`/appointments/${id}`);
      render();
    } catch (e) {
      mount(body, e.status === 404 ? h("div", { class: "state" }, icon("alert"), t("appointments.not_found")) : errorState(e, load));
    }
  }

  async function setStatus(status, btn) {
    if (status === "cancelled" && !(await confirmDialog({ danger: true, message: t("appointments.action.cancelled") + "?" }))) return;
    btn.disabled = true;
    try {
      appt = await api.post(`/appointments/${appt.id}/status`, { status, version: appt.version });
      toastSuccess(t("appointments.status_changed"));
      render();
      onChanged?.();
    } catch (e) {
      const block = conflictBlock(e);
      if (block) alerts.replaceChildren(block);
      else if (e.code === "version_conflict") versionConflict();
      else toastApiError(e);
    } finally { btn.disabled = false; }
  }

  const alerts = h("div", { class: "appt-alerts" });
  function versionConflict() {
    alerts.replaceChildren(h("div", { class: "alert alert-warning", role: "alert" }, t("appointments.version_conflict"), " ",
      h("button", { class: "btn btn-sm", type: "button", onClick: load }, icon("refresh"), t("appointments.reload"))));
  }

  function render() {
    alerts.replaceChildren();
    const a = appt;
    const can = meta.can || {};
    const transitions = (meta.transitions || {})[a.status] || [];
    const statusButtons = can.edit ? ACTION_ORDER.filter((s) => transitions.includes(s)).map((s) => {
      const b = h("button", { class: `btn btn-sm ${ACTION_STYLE[s] || ""}`, type: "button", onClick: () => setStatus(s, b) },
        t(`appointments.action.${s}`));
      return b;
    }) : [];
    const kv = [
      [t("appointments.field.patient"), h("span", a.patient.name, " ", a.patient.code ? h("span", { class: "text-muted ltr" }, a.patient.code) : null)],
      a.patient.phone ? [t("appointments.field.phone"), h("span", { class: "ltr" }, a.patient.phone)] : null,
      [t("appointments.field.date"), `${weekdayName(a.local_date)} ${formatDate(a.local_date, { year: "always" })}`],
      [t("appointments.field.time"), timeRange(a)],
      [t("appointments.field.clinic"), a.clinic.name],
      [t("appointments.field.department"), a.department.name],
      [t("appointments.field.doctor"), a.doctor ? a.doctor.name : "—"],
      a.location ? [t("appointments.field.location"), a.location] : null,
      a.appointment_type ? [t("appointments.field.type"), typeLabel(a.appointment_type)] : null,
      a.reason ? [t("appointments.field.reason"), a.reason] : null,
      a.notes ? [t("appointments.field.notes"), h("span", { class: "appt-notes" }, a.notes)] : null,
      [t("appointments.field.created_by"), `${a.created_by.name || "—"} · ${formatDateTime(a.created_at)}`],
      a.series_id ? ["", t("appointments.rec.series", { id: a.series_id, index: (a.series_index ?? 0) + 1 })] : null,
    ].filter(Boolean);
    mount(body,
      alerts,
      h("div", { class: "row row-between appt-detail-head" }, h("div", { class: "row" }, pill(a.status),
        a.is_walk_in ? h("span", { class: "badge" }, t("appointments.walk_in_badge")) : null)),
      statusButtons.length ? h("div", { class: "btn-group appt-status-btns" }, statusButtons) : null,
      h("dl", { class: "kv" }, kv.flatMap(([k, v]) => [h("dt", k), h("dd", v)])),
      h("div", { class: "btn-group appt-detail-actions" },
        can.edit ? h("button", { class: "btn", type: "button", onClick: () => openAppointmentForm({ ctx, meta, appt: a,
          onSaved: (saved, opts) => { if (saved) { appt = saved; render(); onChanged?.(); } else if (opts?.reload) load(); } }) },
        icon("edit"), t("core.edit")) : null,
        a.patient.phone ? h("button", { class: "btn", type: "button", onClick: () => whatsapp(a) }, icon("bell"), t("appointments.whatsapp")) : null,
        h("button", { class: "btn", type: "button", onClick: () => printElement(slipNode(a)) }, icon("printer"), t("appointments.print_slip")),
        can.edit && a.series_id && a.status === "scheduled" ? h("button", { class: "btn btn-danger", type: "button", onClick: cancelSeries },
          icon("x"), t("appointments.series.cancel")) : null,
        can.delete ? h("button", { class: "btn btn-danger", type: "button", onClick: remove }, icon("trash"), t("appointments.delete")) : null));
  }

  /** Cancel this and all later scheduled occurrences, or the whole series. Past/arrived visits are kept. */
  function cancelSeries() {
    const run = async (fromId, m) => {
      try {
        const res = await api.post(`/appointments/series/${appt.series_id}/cancel`, fromId ? { from_appointment_id: fromId } : {});
        m.close();
        toastSuccess(t("appointments.series.cancelled", { n: res.cancelled }));
        load();
        onChanged?.();
      } catch (e) { toastApiError(e); }
    };
    const m = openModal({ title: t("appointments.series.cancel"), size: "sm",
      body: h("p", t("appointments.series.cancel_message")),
      actions: [
        { label: t("core.cancel") },
        { label: t("appointments.series.cancel_future"), variant: "danger", onClick: () => { run(appt.id, m); return false; } },
        { label: t("appointments.series.cancel_all"), variant: "danger", onClick: () => { run(null, m); return false; } },
      ] });
  }

  async function remove() {
    if (!(await confirmDialog({ danger: true, message: t("appointments.delete_confirm") }))) return;
    try {
      await deleteWithUndo(`/appointments/${appt.id}`, { message: t("appointments.deleted"),
        onDone: () => { drawer.close(); onChanged?.(); }, onUndone: () => onChanged?.() });
    } catch { /* toast shown */ }
  }

  load();
  return drawer;
}

/** WhatsApp reminder: fetch the prepared link, preview it, open on an explicit click (no popup blocking). */
export async function whatsapp(a) {
  let lang = getLang() === "ar" ? "ar" : "en";
  const msg = h("pre", { class: "appt-wa-msg" });
  const link = h("a", { class: "btn btn-primary", target: "_blank", rel: "noopener noreferrer" }, icon("bell"), t("appointments.whatsapp.open"));
  const langSel = h("select", { class: "select", "aria-label": t("appointments.whatsapp.lang") },
    h("option", { value: "ar" }, "العربية"), h("option", { value: "en" }, "English"));
  langSel.value = lang;
  async function fetchLink() {
    try {
      const res = await api.get(`/appointments/${a.id}/whatsapp`, { query: { lang } });
      msg.textContent = res.message;
      if (typeof res.url === "string" && /^https:\/\/wa\.me\/\d+\?text=/.test(res.url)) link.setAttribute("href", res.url);
      return true;
    } catch (e) {
      toastApiError(e);
      return false;
    }
  }
  langSel.addEventListener("change", () => { lang = langSel.value; fetchLink(); });
  if (!(await fetchLink())) return;
  const m = openModal({ title: t("appointments.whatsapp"), size: "md",
    body: [h("div", { class: "field" }, h("label", t("appointments.whatsapp.lang")), langSel), msg,
      h("p", { class: "text-muted text-sm" }, t("appointments.whatsapp.hint"))],
    footer: [h("button", { class: "btn", type: "button", onClick: () => m.close() }, t("core.close")), link] });
  link.addEventListener("click", () => setTimeout(() => m.close(), 100));
}
