// Lab request detail: info, workflow actions, result entry with live abnormal flags, print.
import {
  api, h, mount, t, getLang, formatDateTime, formatDate, ageFrom, icon, toast, toastSuccess, confirmDialog,
  openModal, createForm, deleteWithUndo, printPdf, loadingState, errorState, withBusy,
} from "../core/index.js";
import { computeFlag, flagBadge, refRange, labStatus, priorityPill, showError, kvList } from "./common.js";

/**
 * labRequestView(id, {onChanged, onDeleted}) -> {el, reload()}
 * Works for every access level returned by the API ("lab" | "requester" | "result").
 */
export function labRequestView(id, { onChanged, onDeleted } = {}) {
  const el = h("div", { class: "lab-detail stack" }, loadingState());
  let data = null;
  let dirty = false;

  async function reload() {
    try {
      data = await api.get(`/lab/requests/${id}`);
      dirty = false;
      render();
    } catch (e) {
      mount(el, errorState(e, reload));
      if (e.status === 404 || e.status === 403) throw e;
    }
  }

  const changed = (res) => {
    data = res;
    dirty = false;
    render();
    if (onChanged) onChanged(res);
  };

  async function act(path, body, msg) {
    try {
      const res = await api.post(`/lab/requests/${id}/${path}`, { version: data.version, ...(body || {}) });
      toastSuccess(msg);
      changed(res);
      return res;
    } catch (e) {
      showError(e, reload);
      return null;
    }
  }

  function header() {
    const pt = data.patient || {};
    const can = data.can || {};
    const actions = [];
    if (can.start) actions.push(h("button", { class: "btn btn-primary", type: "button",
      onClick: (e) => withBusy(e.currentTarget, () => act("start", {}, t("laboratory.msg.started"))) }, icon("check"), t("laboratory.action.start")));
    if (data.status === "completed") actions.push(h("button", { class: "btn", type: "button",
      onClick: () => printPdf(`/lab/requests/${id}/report`, { format: "pdf", lang: getLang() }) }, icon("printer"), t("laboratory.action.print")));
    if (can.edit) actions.push(h("button", { class: "btn", type: "button", onClick: openEdit }, icon("edit"), t("laboratory.action.edit")));
    if (can.cancel) actions.push(h("button", { class: "btn btn-ghost", type: "button", onClick: openCancel }, icon("x"), t("laboratory.action.cancel")));
    if (can.delete) actions.push(h("button", { class: "btn btn-ghost", type: "button", "aria-label": t("laboratory.action.delete"),
      onClick: doDelete }, icon("trash")));
    return h("div", { class: "page-header" },
      h("div",
        h("h1", { class: "row" }, t("laboratory.detail.title", { id: data.id }), labStatus(data.status), priorityPill(data.priority)),
        h("p", { class: "subtitle" }, h("strong", pt.full_name || ""), " ",
          pt.code ? h("span", { class: "ltr text-muted" }, pt.code) : null,
          pt.date_of_birth ? h("span", { class: "text-muted" }, ` · ${ageFrom(pt.date_of_birth) ?? ""} · ${formatDate(pt.date_of_birth, { year: "always" })}`) : null)),
      h("div", { class: "page-actions no-print" }, actions));
  }

  function info() {
    return h("section", { class: "card" }, h("div", { class: "card-body" }, kvList([
      [t("laboratory.detail.requesting_clinic"), data.requesting_clinic?.name],
      [t("laboratory.detail.requested_by"), data.requested_by?.name],
      [t("laboratory.detail.requested_at"), formatDateTime(data.requested_at)],
      [t("laboratory.detail.lab"), [data.lab_department?.name, data.lab_clinic?.name].filter(Boolean).join(" · ")],
      [t("laboratory.detail.started"), data.started_at && formatDateTime(data.started_at)],
      [t("laboratory.detail.performed_by"), data.performed_by],
      [t("laboratory.detail.finalized"), data.finalized_at && formatDateTime(data.finalized_at)],
      [t("laboratory.detail.finalized_by"), data.finalized_by?.name],
      [t("laboratory.detail.cancelled"), data.cancelled_at && formatDateTime(data.cancelled_at)],
      [t("laboratory.detail.cancel_reason"), data.cancel_reason],
      [t("laboratory.detail.clinical_notes"), data.clinical_notes],
    ])));
  }

  function readOnlyResults() {
    const shown = data.items.length && "result_value" in data.items[0];
    if (!shown) {
      return h("section", { class: "card" }, h("div", { class: "card-header" }, h("h2", t("laboratory.detail.results"))),
        h("div", { class: "card-body stack" },
          data.status !== "cancelled" ? h("div", { class: "alert alert-info" }, icon("clock"), h("div", t("laboratory.detail.pending_results"))) : null,
          h("ul", { class: "lab-test-list" }, data.items.map((i) => h("li", i.test_name, i.unit ? h("span", { class: "text-muted" }, ` (${i.unit})`) : null)))));
    }
    const rows = data.items.map((i) => h("tr", { class: i.abnormal_flag && i.abnormal_flag !== "N" ? "lab-row-abnormal" : null },
      h("td", { "data-label": t("laboratory.col.test") }, i.test_name),
      h("td", { "data-label": t("laboratory.col.result"), class: "lab-result" }, h("bdi", i.result_value ?? "—")),
      h("td", { "data-label": t("laboratory.col.unit") }, i.unit || ""),
      h("td", { "data-label": t("laboratory.col.range"), class: "ltr-cell" }, h("bdi", refRange(i))),
      h("td", { "data-label": t("laboratory.col.flag") }, flagBadge(i.abnormal_flag)),
      h("td", { "data-label": t("laboratory.col.comment") }, i.comment || "")));
    return h("section", { class: "card" },
      h("div", { class: "card-header row-between" }, h("h2", t("laboratory.detail.results")),
        data.abnormal_count ? h("span", { class: "pill pill--danger" }, t("laboratory.detail.abnormal_count", { n: data.abnormal_count })) : null),
      data.access === "result" ? h("div", { class: "card-body" }, h("div", { class: "text-muted text-sm" }, t("laboratory.detail.read_only"))) : null,
      h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" }, resultHead(), h("tbody", rows))),
      data.result_notes ? h("div", { class: "card-body" }, h("strong", t("laboratory.detail.result_notes")), h("p", data.result_notes)) : null);
  }

  const resultHead = () => h("thead", h("tr", ["test", "result", "unit", "range", "flag", "comment"].map((k) => h("th", t(`laboratory.col.${k}`)))));

  function entryResults() {
    const inputs = [];
    const rows = data.items.map((i) => {
      const flagCell = h("td", { "data-label": t("laboratory.col.flag") }, flagBadge(i.abnormal_flag));
      let control;
      let abnormalBox = null;
      if (i.result_type === "choice") {
        control = h("select", { class: "select" }, h("option", { value: "" }, "—"), (i.choices || []).map((c) => h("option", { value: c }, c)));
        control.value = i.result_value || "";
      } else {
        control = h("input", { class: "input", type: "text", inputmode: i.result_type === "numeric" ? "decimal" : null,
          value: i.result_value || "", maxlength: 500, "aria-label": i.test_name });
      }
      if (i.result_type !== "numeric") {
        abnormalBox = h("input", { type: "checkbox", checked: i.abnormal_flag === "A" });
      }
      const comment = h("input", { class: "input", type: "text", value: i.comment || "", maxlength: 2000, "aria-label": t("laboratory.col.comment") });
      let abnormalTouched = false;
      const update = () => {
        dirty = true;
        const f = computeFlag(i, control.value, abnormalBox && (abnormalTouched || i.result_type === "text") ? abnormalBox.checked : null);
        control.classList.toggle("is-invalid", f === undefined);
        mount(flagCell, f === undefined ? h("span", { class: "pill pill--warning" }, "?") : flagBadge(f));
      };
      control.addEventListener("input", update);
      control.addEventListener("change", update);
      comment.addEventListener("input", () => { dirty = true; });
      if (abnormalBox) abnormalBox.addEventListener("change", () => { abnormalTouched = true; update(); });
      inputs.push({ item: i, control, comment, abnormalBox, touched: () => abnormalTouched });
      return h("tr", {},
        h("td", { "data-label": t("laboratory.col.test") }, h("strong", i.test_name), h("div", { class: "text-xs text-muted ltr" }, i.test_code)),
        h("td", { "data-label": t("laboratory.col.result") }, control,
          abnormalBox ? h("label", { class: "check text-sm" }, abnormalBox, t("laboratory.form.abnormal")) : null),
        h("td", { "data-label": t("laboratory.col.unit") }, i.unit || ""),
        h("td", { "data-label": t("laboratory.col.range") }, h("bdi", refRange(i))),
        flagCell,
        h("td", { "data-label": t("laboratory.col.comment") }, comment));
    });
    const notes = h("textarea", { class: "textarea", rows: 2, maxlength: 4000 });
    notes.value = data.result_notes || "";
    notes.addEventListener("input", () => { dirty = true; });

    const payload = () => ({
      version: data.version,
      result_notes: notes.value.trim() || null,
      items: inputs.map(({ item, control, comment, abnormalBox, touched }) => {
        const row = { id: item.id, result_value: control.value.trim() || null, comment: comment.value.trim() || null };
        if (abnormalBox && (touched() || item.result_type === "text")) row.abnormal = abnormalBox.checked;
        return row;
      }),
    });
    async function save(quiet) {
      try {
        const res = await api.put(`/lab/requests/${id}/results`, payload());
        if (!quiet) toastSuccess(t("laboratory.msg.saved"));
        changed(res);
        return res;
      } catch (e) {
        if (e.status === 422 && e.details) toast(Object.values(e.details).join(" · "), { type: "error" });
        else showError(e, reload);
        return null;
      }
    }
    async function finalize(btn) {
      if (!(await confirmDialog({ message: t("laboratory.confirm.finalize"), confirmLabel: t("laboratory.action.finalize") }))) return;
      await withBusy(btn, async () => {
        if (dirty || data.status === "requested") {
          const saved = await save(true);
          if (!saved) return;
        }
        await act("finalize", {}, t("laboratory.msg.finalized"));
      });
    }
    const saveBtn = h("button", { class: "btn", type: "button", onClick: (e) => withBusy(e.currentTarget, () => save(false)) },
      icon("save"), t("laboratory.action.save_results"));
    const finBtn = h("button", { class: "btn btn-primary", type: "button", onClick: (e) => finalize(e.currentTarget) },
      icon("check"), t("laboratory.action.finalize"));
    return h("section", { class: "card" },
      h("div", { class: "card-header" }, h("h2", t("laboratory.detail.results"))),
      h("div", { class: "table-wrap" }, h("table", { class: "table table-stack lab-entry" }, resultHead(), h("tbody", rows))),
      h("div", { class: "card-body stack" },
        h("label", { class: "field" }, h("span", t("laboratory.detail.result_notes")), notes)),
      h("div", { class: "card-footer row no-print", style: "justify-content:flex-end" }, saveBtn, finBtn));
  }

  function render() {
    mount(el, header(), info(), data.can?.enter_results ? entryResults() : readOnlyResults());
  }

  function openEdit() {
    const form = createForm({
      columns: 1,
      values: { priority: data.priority, clinical_notes: data.clinical_notes },
      fields: [
        { name: "priority", label: t("laboratory.form.priority"), type: "select", empty: false, required: true,
          options: ["routine", "urgent"].map((p) => ({ value: p, label: t(`laboratory.priority.${p}`) })) },
        { name: "clinical_notes", label: t("laboratory.form.clinical_notes"), type: "textarea", maxLength: 4000 },
      ],
      onSubmit: async (v) => {
        const res = await api.patch(`/lab/requests/${id}`, { ...v, version: data.version });
        modal.close();
        changed(res);
      },
    });
    const modal = openModal({ title: t("laboratory.action.edit"), body: form.el });
  }

  function openCancel() {
    const form = createForm({
      columns: 1, submitLabel: t("laboratory.action.cancel"),
      fields: [{ name: "reason", label: t("laboratory.cancel.reason"), type: "textarea", maxLength: 500, rows: 2 }],
      onSubmit: async (v) => {
        const res = await api.post(`/lab/requests/${id}/cancel`, { ...v, version: data.version });
        modal.close();
        toastSuccess(t("laboratory.msg.cancelled"));
        changed(res);
      },
    });
    const modal = openModal({ title: t("laboratory.confirm.cancel"), body: form.el, size: "sm" });
  }

  async function doDelete() {
    if (!(await confirmDialog({ danger: true }))) return;
    try {
      await deleteWithUndo(`/lab/requests/${id}`, { message: t("laboratory.msg.deleted"),
        onDone: () => onDeleted && onDeleted(), onUndone: () => onChanged && onChanged() });
    } catch { /* toast shown */ }
  }

  const ready = reload().then(() => null, (e) => e); // resolves to the load error (404/403) or null
  return { el, reload, ready, isDirty: () => dirty };
}

/** Department route: #/d/<dept>/lab/requests/:id */
export async function renderRequestPage(ctx) {
  const view = labRequestView(ctx.params.id, { onDeleted: () => history.back() });
  const err = await view.ready;
  if (err) throw err;
  ctx.setTitle(t("laboratory.detail.title", { id: ctx.params.id }));
  const warn = (e) => { if (view.isDirty()) { e.preventDefault(); e.returnValue = ""; } };
  window.addEventListener("beforeunload", warn);
  ctx.onLeave = () => window.removeEventListener("beforeunload", warn);
  return h("div", { class: "page" }, view.el);
}
