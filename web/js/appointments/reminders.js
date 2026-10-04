// Tomorrow's (or any day's) reminder list: every scheduled appointment with its prepared WhatsApp link.
// Staff open each link (WhatsApp sends nothing by itself — spec §77) and the row is marked as reminded.
import { api, h, t, mount, icon, openDrawer, getLang, toastApiError, loadingState, errorState, emptyState, formatDate } from "../core/index.js";
import { timeRange } from "./common.js";

const tomorrowISO = () => {
  const d = new Date(Date.now() + 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Damascus" }).format(d); // YYYY-MM-DD
};

export function openReminders({ clinicId } = {}) {
  const state = { date: tomorrowISO(), lang: getLang() === "ar" ? "ar" : "en" };
  const list = h("div", { class: "stack gap-sm" }, loadingState());
  const summary = h("div", { class: "text-sm muted" });
  const dateInput = h("input", { class: "input", type: "date", value: state.date, onChange: (e) => { state.date = e.target.value; load(); } });
  const langSel = h("select", { class: "select", "aria-label": t("appointments.whatsapp.lang"), onChange: (e) => { state.lang = e.target.value; load(); } },
    h("option", { value: "ar" }, "العربية"), h("option", { value: "en" }, "English"));
  langSel.value = state.lang;

  async function load() {
    mount(list, loadingState());
    let res;
    try {
      res = await api.get("/appointments/reminders", { query: { date: state.date, lang: state.lang, clinic_id: clinicId || undefined } });
    } catch (e) {
      return mount(list, errorState(e, load));
    }
    summary.textContent = t("appointments.reminders.summary", { total: res.items.length, sent: res.sent, phone: res.with_phone });
    mount(list, res.items.length ? res.items.map(row) : emptyState({ icon: "calendar", title: t("appointments.reminders.none") }));
  }

  function row(a) {
    const status = h("span", { class: a.reminder_sent_at ? "pill pill--success" : "pill" },
      a.reminder_sent_at ? t("appointments.reminders.sent") : t("appointments.reminders.pending"));
    const open = a.whatsapp ? h("a", { class: "btn btn-sm btn-primary", href: a.whatsapp.url, target: "_blank", rel: "noopener noreferrer",
      onClick: async () => {
        try {
          await api.post(`/appointments/${a.id}/reminded`, {});
          status.className = "pill pill--success";
          status.textContent = t("appointments.reminders.sent");
        } catch (e) { toastApiError(e); }
      } }, icon("bell"), t("appointments.whatsapp")) : h("span", { class: "text-sm muted" }, t("appointments.reminders.no_phone"));
    return h("div", { class: "card card-body row-between wrap gap-sm" },
      h("div", { style: "min-width:0" },
        h("strong", a.patient?.name || ""), " ", h("span", { class: "muted ltr" }, a.patient?.code || ""),
        h("div", { class: "text-sm muted" }, timeRange(a), ` · ${a.clinic?.name || ""}${a.doctor?.name ? ` · ${a.doctor.name}` : ""}`)),
      h("div", { class: "row gap-sm" }, status, open));
  }

  openDrawer({ title: t("appointments.reminders.title"), size: "lg",
    body: h("div", { class: "stack gap-md" },
      h("p", { class: "text-sm muted" }, t("appointments.reminders.help")),
      h("div", { class: "row gap-sm wrap" }, dateInput, langSel),
      summary, list) });
  load();
}

export const reminderDateLabel = (iso) => formatDate(iso, { year: "always" });
