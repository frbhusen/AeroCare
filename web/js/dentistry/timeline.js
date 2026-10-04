// Dental timeline (visits, appointments, treatments, plan items, X-rays, prescriptions).
import { api, h, t, icon, mount, formatDate, loadingState, errorState, emptyState, offlineCopyBanner, statusPill, openImageViewer } from "../core/index.js";
import { dentUrl, fileSrc, statusBadge, xrayTypeLabel } from "./common.js";

const ICON = { visit: "stethoscope", appointment: "calendar", treatment: "tooth", "treatment-plan": "clipboard", xray: "image", prescription: "rx" };
const DENTAL_STATUS = new Set(["planned", "accepted", "scheduled", "in-progress", "completed", "cancelled"]);

export function renderTimeline(panel, { patientId, clinicId }) {
  let type = null;
  const list = h("div", { class: "dent-timeline" });
  const types = Object.keys(ICON);
  const chips = h("div", { class: "row dent-timeline-filter no-print" },
    [null, ...types].map((k) => h("button", { type: "button", class: "btn btn-sm", "aria-pressed": String(k === type),
      onClick: (e) => { type = k; chips.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false")); e.currentTarget.setAttribute("aria-pressed", "true"); draw(); } },
    k ? t(`dentistry.timeline.${k}`) : t("dentistry.timeline.all"))));
  let events = [];
  let banner = null;
  mount(panel, chips, list);

  function status(e) {
    if (!e.status) return null;
    if (e.type === "treatment" || e.type === "treatment-plan") return DENTAL_STATUS.has(e.status) ? statusBadge(e.status) : null;
    return statusPill(e.status, e.type === "appointment" ? "appointments.status" : "core.status");
  }

  function draw() {
    const shown = type ? events.filter((e) => e.type === type) : events;
    if (!shown.length) return mount(list, banner, emptyState({ icon: "clock", title: t("dentistry.timeline.empty") }));
    mount(list, banner, h("ol", { class: "dent-timeline-list" }, shown.map((e) => h("li", { class: `dent-tl dent-tl--${e.type}` },
      h("span", { class: "dent-tl-icon", "aria-hidden": "true" }, icon(ICON[e.type] || "info")),
      h("div", { class: "dent-tl-body" },
        h("div", { class: "row row-between" },
          h("div", h("strong", e.type === "xray" ? e.title : e.title), " ", h("span", { class: "badge" }, t(`dentistry.timeline.${e.type}`))),
          h("span", { class: "text-sm text-muted nowrap" }, e.date ? formatDate(e.date, { year: "always" }) : "", e.time ? ` ${e.time}` : "")),
        h("div", { class: "row text-sm" },
          e.tooth ? h("span", { class: "dent-tooth-chip ltr" }, e.tooth) : null,
          e.type === "xray" ? xrayTypeLabel(e.description) : e.description ? h("span", e.description) : null,
          e.fee ? h("span", { class: "num" }, e.fee) : null,
          status(e)),
        h("div", { class: "text-xs text-muted" }, [e.clinic_name, e.author_name].filter(Boolean).join(" · ")),
        e.type === "xray" ? h("button", { type: "button", class: "btn btn-sm no-print",
          onClick: () => openImageViewer({ src: fileSrc(e.file_id), title: e.title }) }, icon("eye"), t("dentistry.xray.open")) : null)))));
  }

  async function load() {
    mount(list, loadingState());
    try {
      const res = await api.get(dentUrl(`/patients/${patientId}/timeline`), { query: { clinic_id: clinicId }, cache: true });
      events = res.events || [];
      banner = offlineCopyBanner(res);
      draw();
    } catch (e) {
      mount(list, errorState(e, load));
    }
  }
  load();
  return { reload: load };
}
