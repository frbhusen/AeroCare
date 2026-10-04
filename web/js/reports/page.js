// Reports page (center area and department areas). Built entirely from GET /reports (catalog):
// report picker -> filters (dates, department/clinic/doctor, group_by/view) -> results table with totals,
// column picker, Excel/PDF export (reports.export) and Print. In a department area the department is fixed.
import {
  api, ApiError, apiUrl, h, mount, t, getLang, formatNumber, formatMoney, formatDate, formatDateTime, todayISO,
  toastApiError, toast, popover, icon, printView, loadingState, errorState, emptyState, getCenter, withBusy,
} from "../core/index.js";
import { parseBody, toApiError } from "../core/api.js";

const VALUE_GROUPS = new Set(["status", "kind", "gender", "exam_type", "procedure"]);
const VALUE_COLUMNS = new Set(["status", "low", "role"]);

// ---- date helpers (ISO YYYY-MM-DD, local Damascus "today" from core) ----------------------------
function shift(iso, days) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
function ranges() {
  const today = todayISO();
  const [y, m] = today.split("-").map(Number);
  const monthStart = `${y}-${String(m).padStart(2, "0")}-01`;
  const lastEnd = shift(monthStart, -1);
  return {
    today: [today, today], "7d": [shift(today, -6), today], "30d": [shift(today, -29), today],
    month: [monthStart, today], last_month: [`${lastEnd.slice(0, 7)}-01`, lastEnd], year: [`${y}-01-01`, today],
  };
}

const ar = () => getLang() === "ar";
const colLabel = (c) => (ar() ? c.label_ar || c.label : c.label);
const reportTitle = (r) => (ar() ? r.title_ar || r.title : r.title);

function valueText(v) {
  return t(`reports.value.${v}`, { default: String(v) });
}

export async function renderReports(ctx) {
  const deptId = ctx.area === "department" ? ctx.dept?.id ?? null : null;
  const catalog = await api.get("/reports"); // 403/404 -> standard pages
  const reports = catalog.reports || [];
  const title = deptId ? t("reports.dept_title", { dept: ctx.dept.name }) : t("reports.title");
  ctx.setTitle?.(title);

  const page = h("div", { class: "page reports-page" });
  if (!reports.length) {
    mount(page, h("div", { class: "page-header" }, h("h1", title)),
      h("div", { class: "card" }, emptyState({ icon: "chart", title: t("reports.none_available") })));
    return page;
  }

  const defaults = catalog.default_range || {};
  const initial = reports.find((r) => r.key === ctx.query?.report) || reports[0];
  const state = {
    report: initial,
    filters: { date_from: defaults.date_from, date_to: defaults.date_to, department_id: deptId, clinic_id: null,
      doctor_id: null, days: 30 },
    group: {}, view: {}, hidden: {}, // per report key
    data: null, seq: 0,
  };
  const canExport = (catalog.formats || []).length > 0;

  const picker = h("div", { class: "reports-picker no-print", role: "tablist", "aria-label": t("reports.pick") });
  const filtersEl = h("div", { class: "card reports-filters no-print" });
  const actions = h("div", { class: "page-actions no-print" });
  const printHead = h("div", { class: "print-only reports-print-head" });
  const result = h("div", { class: "reports-result" });

  function renderPicker() {
    mount(picker, reports.map((r) => h("button", {
      class: ["reports-chip", r.key === state.report.key && "is-active"], type: "button", role: "tab",
      "aria-selected": String(r.key === state.report.key),
      onClick: () => { if (r.key !== state.report.key) { state.report = r; renderAll(); } },
    }, reportTitle(r))));
  }

  // ---- filters ----------------------------------------------------------------------------
  function select(label, value, options, onChange, { allLabel = t("reports.all"), all = true } = {}) {
    const sel = h("select", { class: "select", onChange: (e) => onChange(e.target.value || null) },
      all ? h("option", { value: "" }, allLabel) : null,
      options.map(([v, l]) => h("option", { value: String(v), selected: String(v) === String(value ?? "") }, l)));
    return h("label", { class: "field" }, h("span", { class: "field-label" }, label), sel);
  }

  function dateInput(label, key) {
    return h("label", { class: "field" }, h("span", { class: "field-label" }, label),
      h("input", { class: "input ltr", type: "date", value: state.filters[key] || "", required: true,
        onChange: (e) => { if (e.target.value) { state.filters[key] = e.target.value; run(); } } }));
  }

  function clinicsInScope() {
    const dep = state.filters.department_id;
    return (catalog.clinics || []).filter((c) => !dep || c.department_id === dep);
  }

  function doctorsInScope() {
    const dep = state.filters.department_id;
    const clinic = state.filters.clinic_id;
    const depClinics = new Set(clinicsInScope().map((c) => c.id));
    return (catalog.doctors || []).filter((d) => {
      if (clinic) return d.clinic_id === clinic;
      if (dep) return d.department_id === dep || depClinics.has(d.clinic_id);
      return true;
    });
  }

  function renderFilters() {
    const r = state.report;
    const f = new Set(r.filters || []);
    const fields = [];
    if (f.has("date_from")) {
      fields.push(dateInput(t("reports.date_from"), "date_from"), dateInput(t("reports.date_to"), "date_to"));
    }
    if (f.has("department_id") && !deptId && (catalog.departments || []).length > 1) {
      fields.push(select(t("reports.department"), state.filters.department_id,
        catalog.departments.map((d) => [d.id, d.name]), (v) => {
          state.filters.department_id = v ? Number(v) : null;
          state.filters.clinic_id = null;
          state.filters.doctor_id = null;
          renderFilters();
          run();
        }));
    }
    const clinics = clinicsInScope();
    if (f.has("clinic_id") && clinics.length > 1) {
      fields.push(select(t("reports.clinic"), state.filters.clinic_id, clinics.map((c) => [c.id, c.name]), (v) => {
        state.filters.clinic_id = v ? Number(v) : null;
        state.filters.doctor_id = null;
        renderFilters();
        run();
      }));
    }
    const doctors = doctorsInScope();
    if (f.has("doctor_id") && doctors.length > 1) {
      fields.push(select(t("reports.doctor"), state.filters.doctor_id, doctors.map((d) => [d.id, d.name]), (v) => {
        state.filters.doctor_id = v ? Number(v) : null;
        run();
      }));
    }
    if ((r.views || []).length) {
      const cur = state.view[r.key] || r.views[0];
      fields.push(select(t("reports.view"), cur, r.views.map((v) => [v, t(`reports.view.${v}`, { default: v })]),
        (v) => { state.view[r.key] = v; renderFilters(); run(); }, { all: false }));
      if (cur === "expiry") {
        fields.push(h("label", { class: "field" }, h("span", { class: "field-label" }, t("reports.days")),
          h("input", { class: "input ltr", type: "number", min: 0, max: 3650, value: state.filters.days,
            onChange: (e) => { const n = Number(e.target.value); if (Number.isInteger(n) && n >= 0) { state.filters.days = n; run(); } } })));
      }
    }
    if ((r.group_by || []).length) {
      const cur = state.group[r.key] || r.default_group;
      const lbl = (g) => { const l = (r.group_labels || {})[g]; return l ? (ar() ? l[1] || l[0] : l[0]) : g; };
      fields.push(select(t("reports.group_by"), cur, r.group_by.map((g) => [g, lbl(g)]),
        (v) => { state.group[r.key] = v; run(); }, { all: false }));
    }
    const presets = f.has("date_from") ? h("div", { class: "reports-presets" },
      Object.entries(ranges()).map(([k, [from, to]]) => h("button", {
        class: ["btn btn-sm", state.filters.date_from === from && state.filters.date_to === to && "btn-primary"],
        type: "button",
        onClick: () => { state.filters.date_from = from; state.filters.date_to = to; renderFilters(); run(); },
      }, t(`reports.range.${k}`)))) : h("div", { class: "alert reports-nodates" }, icon("info"), h("div", t("reports.no_dates")));
    mount(filtersEl, h("div", { class: "card-body stack" }, h("div", { class: "reports-fields" }, fields), presets));
  }

  // ---- query + actions --------------------------------------------------------------------------
  function query() {
    const r = state.report;
    const f = new Set(r.filters || []);
    const q = {};
    for (const k of ["date_from", "date_to", "department_id", "clinic_id", "doctor_id"]) {
      if (f.has(k) && state.filters[k] != null) q[k] = state.filters[k];
    }
    if ((r.group_by || []).length) q.group_by = state.group[r.key] || r.default_group;
    if ((r.views || []).length) q.view = state.view[r.key] || r.views[0];
    if (q.view === "expiry") q.days = state.filters.days;
    return q;
  }

  function visibleColumns() {
    const cols = state.data?.columns || [];
    const hidden = state.hidden[state.report.key] || new Set();
    return cols.filter((c) => !hidden.has(c.key));
  }

  function openColumns(e) {
    const btn = e.currentTarget;
    const cols = state.data?.columns || [];
    if (!cols.length) return;
    const key = state.report.key;
    const hidden = state.hidden[key] || (state.hidden[key] = new Set());
    const list = h("div", { class: "reports-colpicker stack" },
      cols.map((c) => h("label", { class: "row reports-colpicker-item" },
        h("input", { type: "checkbox", checked: !hidden.has(c.key), onChange: (ev) => {
          if (!ev.target.checked && cols.length - hidden.size <= 1) {
            ev.target.checked = true;
            toast(t("reports.columns_min"), { type: "warning" });
            return;
          }
          if (ev.target.checked) hidden.delete(c.key); else hidden.add(c.key);
          renderResult();
        } }), h("span", colLabel(c)))),
      h("button", { class: "btn btn-sm btn-link", type: "button", onClick: () => {
        hidden.clear();
        list.querySelectorAll("input[type=checkbox]").forEach((x) => { x.checked = true; });
        renderResult();
      } }, t("reports.columns_all")));
    popover(btn, list);
  }

  async function download(fmt, btn) {
    const q = { ...query(), format: fmt, lang: getLang() };
    const hidden = state.hidden[state.report.key];
    if (hidden && hidden.size && state.data) q.columns = visibleColumns().map((c) => c.key).join(",");
    await withBusy(btn, async () => {
      try {
        const res = await fetch(apiUrl(`/reports/${encodeURIComponent(state.report.key)}/export`, q),
          { credentials: "same-origin", cache: "no-store" });
        if (!res.ok) throw toApiError(res.status, await parseBody(res));
        const blob = await res.blob();
        const m = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = m ? m[1] : `report.${fmt}`;
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      } catch (err) {
        toastApiError(err instanceof ApiError ? err : toApiError(0, null));
      }
    });
  }

  function renderActions() {
    const btns = [
      h("button", { class: "btn", type: "button", onClick: openColumns }, icon("sliders"), t("reports.columns")),
      h("button", { class: "btn", type: "button", onClick: () => run() }, icon("refresh"), t("reports.refresh")),
      h("button", { class: "btn", type: "button", onClick: () => printView() }, icon("printer"), t("reports.print")),
    ];
    if (canExport) {
      const x = h("button", { class: "btn btn-primary", type: "button", onClick: (e) => download("xlsx", e.currentTarget) },
        icon("download"), t("reports.export_xlsx"));
      const p = h("button", { class: "btn", type: "button", onClick: (e) => download("pdf", e.currentTarget) },
        icon("file"), t("reports.export_pdf"));
      btns.push(x, p);
    }
    mount(actions, btns);
  }

  // ---- results ----------------------------------------------------------------------------------
  function cell(c, row, currency) {
    const v = row[c.key];
    if (v == null || v === "") return c.type === "percent" || c.type === "number" ? "–" : "";
    switch (c.type) {
      case "int": return formatNumber(v);
      case "number": return formatNumber(v, { max: 3 });
      case "money": return formatMoney(v, currency || undefined);
      case "percent": return `${formatNumber(v, { decimals: 1 })}%`;
      case "date": return formatDate(v, { year: "always" });
      case "bool": return valueText(v);
      default: {
        const group = state.data?.filters?.group_by;
        if (c.key === "group" && (row.key == null || VALUE_GROUPS.has(group))) return valueText(v);
        if (VALUE_COLUMNS.has(c.key)) return valueText(v);
        return String(v);
      }
    }
  }

  function renderResult() {
    const d = state.data;
    if (!d) return;
    const cols = visibleColumns();
    const currency = d.meta?.currency;
    const numeric = (c) => ["int", "number", "money", "percent"].includes(c.type);
    const f = d.filters || {};
    mount(printHead,
      h("div", { class: "reports-print-title" }, getCenter()?.name || ""),
      h("h2", reportTitle(d)),
      (state.report.filters || []).includes("date_from")
        ? h("div", t("reports.period", { from: formatDate(f.date_from, { year: "always" }), to: formatDate(f.date_to, { year: "always" }) })) : null,
      Object.entries(d.filter_labels || {}).filter(([, v]) => v).map(([k, v]) => h("div", `${t(`reports.${k}`)}: ${v}`)),
      h("div", { class: "text-muted text-sm" }, t("reports.generated", { time: formatDateTime(d.generated_at) })));

    const notes = (d.notes || []).map((n) => h("div", { class: "text-muted text-sm" }, n));
    const trunc = d.truncated ? h("div", { class: "alert alert-warning" }, icon("alert"),
      h("div", t("reports.truncated", { n: formatNumber(d.row_limit) }))) : null;
    if (!d.rows.length) {
      mount(result, h("div", { class: "card" }, emptyState({ icon: "chart", title: t("reports.no_rows") })), ...notes);
      return;
    }
    const thead = h("thead", h("tr", cols.map((c) => h("th", { class: numeric(c) ? "num" : null }, colLabel(c)))));
    const tbody = h("tbody", d.rows.map((row) => h("tr", cols.map((c) => h("td", {
      class: [numeric(c) && "num", c.type === "date" && "ltr nowrap"], "data-label": colLabel(c),
    }, cell(c, row, currency))))));
    const tfoot = d.totals ? h("tfoot", h("tr", { class: "reports-total" }, cols.map((c, i) => h("td", {
      class: numeric(c) ? "num" : null, "data-label": colLabel(c),
    }, i === 0 && !numeric(c) ? t("reports.total") : cell(c, d.totals, currency))))) : null;
    mount(result,
      trunc,
      h("div", { class: "card" },
        h("div", { class: "card-header row row-between" }, h("strong", reportTitle(d)),
          h("span", { class: "text-muted text-sm" }, t("reports.rows", { count: formatNumber(d.rows.length) }))),
        h("div", { class: "table-wrap" }, h("table", { class: "table table-stack reports-table" }, thead, tbody, tfoot))),
      h("div", { class: "stack reports-notes" }, notes));
  }

  async function run() {
    const my = ++state.seq;
    mount(result, h("div", { class: "card" }, loadingState()));
    try {
      const data = await api.get(`/reports/${encodeURIComponent(state.report.key)}`, { query: query() });
      if (my !== state.seq) return;
      state.data = data;
      renderResult();
    } catch (err) {
      if (my !== state.seq) return;
      state.data = null;
      mount(printHead);
      mount(result, h("div", { class: "card" }, errorState(err, run)));
    }
  }

  function renderAll() {
    state.data = null;
    renderPicker();
    renderFilters();
    renderActions();
    run();
  }

  mount(page,
    h("div", { class: "page-header" }, h("h1", { class: "no-print" }, title), actions),
    picker, filtersEl, printHead, result);
  renderAll();
  return page;
}
