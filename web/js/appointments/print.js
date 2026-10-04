// Printable views (window.print via printElement; print CSS hides app chrome).
import { h, t, formatDate, formatDateTime, getCenter } from "../core/index.js";
import { typeLabel, weekdayName } from "./common.js";

function header(title, subtitle) {
  const c = getCenter();
  return h("div", { class: "appt-print-head" },
    h("div", { class: "appt-print-center" }, c?.name || ""),
    h("h1", title), subtitle ? h("div", { class: "appt-print-sub" }, subtitle) : null);
}

const footer = () => h("div", { class: "appt-print-foot" }, t("appointments.print.generated", { date: formatDateTime(new Date()) }));

/** Appointment slip for the patient. */
export function slipNode(a) {
  const rows = [
    [t("appointments.field.patient"), `${a.patient.name || ""}${a.patient.code ? ` (${a.patient.code})` : ""}`],
    [t("appointments.field.date"), `${weekdayName(a.local_date)} ${formatDate(a.local_date, { year: "always" })}`],
    [t("appointments.field.time"), `${a.start_time} – ${a.end_time}`],
    [t("appointments.field.clinic"), a.clinic.name],
    a.location ? [t("appointments.field.location"), a.location] : null,
    a.doctor ? [t("appointments.field.doctor"), a.doctor.name] : null,
    a.appointment_type ? [t("appointments.field.type"), typeLabel(a.appointment_type)] : null,
  ].filter(Boolean);
  return h("div", { class: "appt-print appt-slip" }, header(t("appointments.print.slip_title")),
    h("table", { class: "table" }, h("tbody", rows.map(([k, v]) => h("tr", h("th", k), h("td", v))))), footer());
}

/** Schedule print: one table per day. data = /appointments/schedule payload. */
export function scheduleNode(data, subtitle) {
  const days = (data.days || []).filter((d) => d.items.length || data.view === "day");
  return h("div", { class: "appt-print" },
    header(t("appointments.print.title"), subtitle),
    days.map((d) => h("section", { class: "appt-print-day" },
      h("h2", `${weekdayName(d.date)} ${formatDate(d.date, { year: "always" })}`),
      d.items.length ? h("table", { class: "table" },
        h("thead", h("tr", [t("appointments.field.time"), t("appointments.field.patient"), t("appointments.field.clinic"),
          t("appointments.field.doctor"), t("appointments.field.type"), t("appointments.field.status")].map((x) => h("th", x)))),
        h("tbody", d.items.map((a) => h("tr",
          h("td", { class: "ltr nowrap" }, `${a.start_time}–${a.end_time}`),
          h("td", a.patient.name || "", a.patient.phone ? h("div", { class: "ltr text-sm" }, a.patient.phone) : null),
          h("td", a.clinic.name || ""), h("td", a.doctor?.name || "—"), h("td", typeLabel(a.appointment_type)),
          h("td", t(`appointments.status.${a.status}`)))))) : h("p", t("appointments.empty_day")))),
    footer());
}
