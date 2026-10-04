// Invoice editor: new invoice or edit a draft. Patient search, service lines / free lines,
// per-line discounts (amount or %), invoice discount, live estimated totals, save draft / save & issue.
import { api, h, t, mount, navigate, toast, toastApiError, patientSearch, patientName, popover, debounce, icon,
  formatMoney, getUser, loadingState, errorState, getClinic, ApiError } from "../core/index.js";
import { link, meta, clinicOptions, lineMath, fromCents, toCents, money } from "./util.js";

export async function renderEditor(ctx) {
  const id = ctx.params.id ? Number(ctx.params.id) : null;
  const m = await meta();
  let inv = null;
  if (id) {
    inv = await api.get(`/billing/invoices/${id}`);
    if (inv.status !== "draft") {
      navigate(link(ctx, `invoices/${id}`), { replace: true });
      return h("div");
    }
  }
  const state = {
    patient: inv ? { id: inv.patient_id, full_name: inv.patient_name, code: inv.patient_code } : null,
    clinic_id: inv?.clinic_id || Number(ctx.query.clinic_id) || defaultClinic(ctx),
    doctor_user_id: inv?.doctor_user_id || null,
    invoice_discount: inv && Number(inv.invoice_discount) ? inv.invoice_discount : "",
    notes: inv?.notes || "",
    lines: (inv?.items || []).map((i) => ({
      service_id: i.service_id, kind: i.kind, description: i.description, qty: i.qty, unit_price: i.unit_price,
      list_price: i.list_price, reference_type: i.reference_type, reference_id: i.reference_id,
      discount_mode: i.discount_percent != null ? "percent" : "amount",
      discount_value: i.discount_percent != null ? i.discount_percent : (Number(i.discount_amount) ? i.discount_amount : ""),
    })),
  };
  if (!inv && ctx.query.patient_id) {
    state.patient = { id: Number(ctx.query.patient_id) };
    api.get(`/patients/${state.patient.id}`).then((p) => { state.patient = p; renderPatient(); }).catch(() => {});
  }

  const errorBox = h("div");
  const patientBox = h("div", { class: "billing-patient" });
  const linesBody = h("tbody");
  const totalsBox = h("div", { class: "billing-editor-totals" });
  const doctorSel = h("select", { class: "select", name: "doctor_user_id" });

  // ---- patient
  function renderPatient() {
    if (state.patient) {
      mount(patientBox, h("div", { class: "row" }, icon("user"),
        h("strong", patientName(state.patient)), state.patient.code ? h("span", { class: "text-muted ltr" }, state.patient.code) : null,
        inv ? null : h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { state.patient = null; renderPatient(); } },
          t("billing.editor.change_patient"))));
    } else {
      const ps = patientSearch({ placeholder: t("billing.editor.choose_patient"), autofocus: true,
        onSelect: (p) => { state.patient = p; renderPatient(); } });
      mount(patientBox, ps.el);
    }
  }

  // ---- clinic + doctor
  const clinicSel = h("select", { class: "select", name: "clinic_id", disabled: !!inv },
    h("option", { value: "" }, t("core.select_placeholder")),
    clinicOptions(ctx).map((o) => h("option", { value: String(o.value) }, o.label)));
  clinicSel.value = state.clinic_id ? String(state.clinic_id) : "";
  clinicSel.addEventListener("change", () => { state.clinic_id = Number(clinicSel.value) || null; loadDoctors(); });
  doctorSel.addEventListener("change", () => { state.doctor_user_id = Number(doctorSel.value) || null; });

  async function loadDoctors() {
    mount(doctorSel, h("option", { value: "" }, t("billing.editor.no_doctor")));
    if (!state.clinic_id) return;
    try {
      const res = await api.get("/billing/doctors", { query: { clinic_id: state.clinic_id }, cache: true });
      res.items.forEach((d) => doctorSel.append(h("option", { value: String(d.id) }, d.name)));
      if (!inv && !state.doctor_user_id && res.items.some((d) => d.id === getUser()?.id)) state.doctor_user_id = getUser().id;
      doctorSel.value = state.doctor_user_id ? String(state.doctor_user_id) : "";
    } catch { /* optional field */ }
  }

  // ---- lines
  const kindOptions = (m.item_kinds || []).map((k) => ({ value: k, label: t(`billing.kind.${k}`) }));
  function lineRow(line, idx) {
    const math = lineMath(line);
    const totalCell = h("td", { class: "num", "data-label": t("billing.editor.line_total") },
      Number.isFinite(math.total) ? money(fromCents(math.total)) : "—");
    const refresh = () => {
      const mm = lineMath(line);
      mount(totalCell, Number.isFinite(mm.total) ? money(fromCents(mm.total)) : "—");
      totalCell.classList.toggle("billing-bad", !Number.isFinite(mm.total) || mm.total < 0);
      renderTotals();
    };
    const inp = (key, attrs) => {
      const el = h("input", { class: "input", value: line[key] ?? "", ...attrs });
      el.addEventListener("input", () => { line[key] = el.value.trim(); refresh(); });
      return el;
    };
    const kind = h("select", { class: "select", "aria-label": t("billing.editor.kind") },
      kindOptions.map((o) => h("option", { value: o.value }, o.label)));
    kind.value = line.kind || "service";
    kind.addEventListener("change", () => { line.kind = kind.value; });
    const mode = h("select", { class: "select billing-disc-mode", "aria-label": t("billing.editor.discount_mode") },
      h("option", { value: "amount" }, t("billing.editor.amount")), h("option", { value: "percent" }, t("billing.editor.percent")));
    mode.value = line.discount_mode || "amount";
    mode.addEventListener("change", () => { line.discount_mode = mode.value; refresh(); });
    return h("tr",
      h("td", { "data-label": t("billing.editor.description") },
        inp("description", { maxlength: 300, required: true, "aria-label": t("billing.editor.description") }),
        line.list_price && line.list_price !== line.unit_price
          ? h("div", { class: "text-sm text-muted" }, t("billing.editor.list_price", { price: formatMoney(line.list_price) })) : null),
      h("td", { "data-label": t("billing.editor.kind") }, kind),
      h("td", { "data-label": t("billing.editor.qty") }, inp("qty", { type: "number", min: "0.01", step: "0.01", inputmode: "decimal", class: "input billing-num", "aria-label": t("billing.editor.qty") })),
      h("td", { "data-label": t("billing.editor.price") }, inp("unit_price", { type: "number", min: "0", step: "0.01", inputmode: "decimal", class: "input billing-num", "aria-label": t("billing.editor.price") })),
      h("td", { "data-label": t("billing.editor.discount") }, h("div", { class: "billing-disc" }, mode,
        inp("discount_value", { type: "number", min: "0", step: "0.01", inputmode: "decimal", class: "input billing-num", "aria-label": t("billing.editor.discount") }))),
      totalCell,
      h("td", { class: "actions" }, h("button", { class: "btn btn-ghost btn-icon btn-sm", type: "button", "aria-label": t("billing.editor.remove_line"),
        onClick: () => { state.lines.splice(idx, 1); renderLines(); } }, icon("trash"))));
  }
  function renderLines() {
    mount(linesBody, state.lines.length ? state.lines.map(lineRow)
      : h("tr", h("td", { colspan: 7, class: "text-muted" }, t("billing.editor.no_items"))));
    renderTotals();
  }
  function renderTotals() {
    let sub = 0; let disc = 0;
    for (const l of state.lines) {
      const mm = lineMath(l);
      sub += mm.gross; disc += mm.discount;
    }
    const invDisc = toCents(state.invoice_discount || "0");
    const total = sub - disc - (Number.isFinite(invDisc) ? invDisc : 0);
    const row = (label, cents, strong) => h("div", { class: ["row-between", strong && "billing-grand"] },
      h("span", label), h("span", { class: "num ltr" }, Number.isFinite(cents) ? formatMoney(fromCents(cents)) : "—"));
    mount(totalsBox, row(t("billing.subtotal"), sub), row(t("billing.discounts"), disc + (Number.isFinite(invDisc) ? invDisc : 0)),
      row(t("billing.total"), total, true), h("div", { class: "text-sm text-muted" }, t("billing.editor.estimate")));
  }

  function addFree() {
    state.lines.push({ kind: "service", description: "", qty: "1", unit_price: "", discount_mode: "amount", discount_value: "" });
    renderLines();
    linesBody.querySelector("tr:last-child input")?.focus();
  }

  function addService(btn) {
    if (!state.clinic_id) return toast(t("billing.editor.need_clinic"), { type: "warning" });
    const results = h("div", { class: "billing-svc-results" });
    const search = h("input", { class: "input", type: "search", placeholder: t("billing.editor.search_service"), autofocus: true });
    const pop = popover(btn, h("div", { class: "billing-svc-pop" }, search, results), { align: "start" });
    const load = async () => {
      mount(results, loadingState());
      try {
        const res = await api.get("/billing/services", { query: { clinic_id: state.clinic_id, active: true, q: search.value.trim() || undefined, per_page: 30 }, cache: true });
        mount(results, res.items.length ? res.items.map((s) => h("button", { class: "search-result", type: "button", onClick: () => {
          state.lines.push({ service_id: s.id, kind: s.kind, description: s.name, qty: "1", unit_price: s.effective_price,
            list_price: s.effective_price, discount_mode: "amount", discount_value: "" });
          pop.close();
          renderLines();
        } }, h("span", { class: "search-result-name" }, s.name),
        h("span", { class: "search-result-meta num ltr" }, formatMoney(s.effective_price), s.category ? ` · ${s.category}` : "")))
          : h("div", { class: "search-hint" }, t("billing.editor.no_services")));
      } catch (e) {
        mount(results, errorState(e));
      }
    };
    search.addEventListener("input", debounce(load, 250));
    load();
    setTimeout(() => search.focus(), 0);
  }

  const invDiscInput = h("input", { class: "input billing-num", type: "number", min: "0", step: "0.01", inputmode: "decimal", value: state.invoice_discount });
  invDiscInput.addEventListener("input", () => { state.invoice_discount = invDiscInput.value.trim(); renderTotals(); });
  const notes = h("textarea", { class: "textarea", rows: 2, maxlength: 4000 });
  notes.value = state.notes;
  notes.addEventListener("input", () => { state.notes = notes.value; });

  // ---- save
  function payload() {
    return {
      doctor_user_id: state.doctor_user_id || null,
      notes: state.notes.trim() || null,
      invoice_discount: state.invoice_discount || "0",
      items: state.lines.map((l) => {
        const item = { kind: l.kind || "service", description: l.description || null, qty: l.qty || "1", unit_price: l.unit_price === "" ? null : l.unit_price };
        if (l.service_id) item.service_id = l.service_id;
        if (l.reference_type && l.reference_id) Object.assign(item, { reference_type: l.reference_type, reference_id: l.reference_id });
        if (l.discount_value) item[l.discount_mode === "percent" ? "discount_percent" : "discount_amount"] = l.discount_value;
        return item;
      }),
    };
  }
  async function save(btn, issue) {
    mount(errorBox);
    if (!state.patient) return showError(t("billing.editor.need_patient"));
    if (!state.clinic_id) return showError(t("billing.editor.need_clinic"));
    if (issue && !state.lines.length) return showError(t("billing.editor.need_items"));
    btn.classList.add("is-loading");
    btn.disabled = true;
    try {
      let res;
      if (inv) {
        res = await api.put(`/billing/invoices/${inv.id}`, { ...payload(), version: inv.version });
        if (issue) res = await api.post(`/billing/invoices/${inv.id}/issue`, { version: res.version });
      } else {
        res = await api.post("/billing/invoices", { ...payload(), patient_id: state.patient.id, clinic_id: state.clinic_id, issue },
          { offline: true, label: t("billing.new_invoice") });
      }
      if (res.queued) {
        toast(t("billing.editor.saved_offline"), { type: "warning" });
        return navigate(link(ctx, "invoices"));
      }
      toast(t("billing.editor.saved"), { type: "success" });
      navigate(link(ctx, `invoices/${res.id}`), { replace: true });
    } catch (e) {
      if (e?.code === "version_conflict") {
        showError(t("billing.detail.conflict"), h("button", { class: "btn btn-sm", type: "button", onClick: () => navigate(link(ctx, `invoices/${inv.id}`)) }, t("billing.detail.reload")));
      } else if (e instanceof ApiError && e.status === 422) {
        const det = e.details && typeof e.details === "object" ? Object.entries(e.details).map(([k, v]) => `${k}: ${v}`).join(" · ") : "";
        showError(e.message + (det ? ` — ${det}` : ""));
      } else if (e?.status && e.status < 500) showError(e.message);
      else toastApiError(e);
    } finally {
      btn.classList.remove("is-loading");
      btn.disabled = false;
    }
  }
  function showError(msg, extra) {
    mount(errorBox, h("div", { class: "alert alert-danger", role: "alert" }, icon("alert"), h("div", msg), extra || null));
  }

  renderPatient();
  renderLines();
  loadDoctors();
  const addSvcBtn = h("button", { class: "btn", type: "button" }, icon("search"), t("billing.editor.add_service"));
  addSvcBtn.addEventListener("click", () => addService(addSvcBtn));
  const draftBtn = h("button", { class: "btn", type: "button" }, icon("save"), t("billing.editor.save_draft"));
  draftBtn.addEventListener("click", () => save(draftBtn, false));
  const issueBtn = h("button", { class: "btn btn-primary", type: "button" }, icon("check"), t("billing.editor.save_issue"));
  issueBtn.addEventListener("click", () => save(issueBtn, true));

  const field = (label, control) => h("div", { class: "field" }, h("label", label), control);
  return h("div", { class: "page billing-page" },
    h("div", { class: "page-header" },
      h("div", h("a", { class: "btn btn-link", href: link(ctx, inv ? `invoices/${inv.id}` : "invoices") }, icon("arrowLeft", "flip-rtl"), t("billing.tab.invoices")),
        h("h1", inv ? t("billing.editor.edit_title", { number: inv.number }) : t("billing.editor.new_title")))),
    errorBox,
    h("section", { class: "card card-pad stack" },
      field(t("billing.patient"), patientBox),
      h("div", { class: "form-grid" }, field(t("billing.clinic"), clinicSel), field(t("billing.doctor"), doctorSel))),
    h("section", { class: "card" },
      h("div", { class: "card-header" }, h("h2", t("billing.editor.items")),
        h("div", { class: "btn-group" }, addSvcBtn,
          h("button", { class: "btn", type: "button", onClick: addFree }, icon("plus"), t("billing.editor.add_line")))),
      h("div", { class: "table-wrap" }, h("table", { class: "table table-stack billing-lines" },
        h("thead", h("tr", [t("billing.editor.description"), t("billing.editor.kind"), t("billing.editor.qty"), t("billing.editor.price"),
          t("billing.editor.discount"), t("billing.editor.line_total"), ""].map((x) => h("th", x)))), linesBody))),
    h("section", { class: "grid-2 billing-editor-foot" },
      h("div", { class: "card card-pad stack" },
        field(t("billing.invoice_discount"), invDiscInput), field(t("billing.notes"), notes)),
      h("div", { class: "card card-pad stack" }, totalsBox,
        h("div", { class: "form-actions" }, draftBtn, issueBtn))));
}

function defaultClinic(ctx) {
  const opts = clinicOptions(ctx);
  const own = getUser()?.clinic_id;
  if (own && getClinic(own) && opts.some((o) => o.value === own)) return own;
  return opts.length === 1 ? opts[0].value : null;
}
