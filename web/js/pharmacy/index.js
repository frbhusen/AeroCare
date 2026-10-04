// Pharmacy environment: prescription queue + dispensing, cash sales (POS with USB barcode scanners),
// medication catalog with stock, expiry view. Backend: /api/v1/pharmacy (+ /inventory/lookup for scans).
import {
  api, h, mount, t, can, icon, dataTable, formatDate, formatDateTime, formatMoney, openModal, toastSuccess,
  toastApiError, toast, loadingState, errorState, emptyState, statusPill, patientSearch, listenBarcode, debounce,
} from "../core/index.js";
import { dict } from "./i18n.js";

const ENV = ["pharmacy"];
const PERM = "pharmacy.dispense";
let metaPromise = null;
const loadMeta = () => (metaPromise ||= api.get("/pharmacy/meta").catch((e) => { metaPromise = null; throw e; }));
let currentClinicId = null; // chosen pharmacy clinic (when the user has several)

export function register(registry) {
  registry.i18n(dict);
  const pages = [
    ["queue", "pharmacy.tab.queue", "clipboard", renderQueue, 20],
    ["sales", "pharmacy.tab.sales", "tag", renderSales, 30],
    ["medications", "pharmacy.tab.catalog", "pill", renderCatalog, 40],
    ["expiry", "pharmacy.tab.expiry", "alert", renderExpiry, 50],
  ];
  for (const [path, label, ic, render, order] of pages) {
    registry.route({ area: "department", env: ENV, path, title: label, perm: PERM, render });
    registry.menu({ area: "department", env: ENV, key: `pharmacy-${path}`, path, label, icon: ic, perm: PERM, order });
  }
}

// ---------------------------------------------------------------- shared
const qty = (v) => Number(v || 0);

async function clinicPicker(onChange) {
  const meta = await loadMeta();
  if (!currentClinicId || !meta.clinics.some((c) => c.id === currentClinicId)) currentClinicId = meta.clinics[0]?.id ?? null;
  if (meta.clinics.length < 2) return null;
  const sel = h("select", { class: "select", style: "max-width:220px", "aria-label": t("pharmacy.clinic"),
    onChange: (e) => { currentClinicId = Number(e.target.value); onChange(); } },
  meta.clinics.map((c) => h("option", { value: c.id }, c.name)));
  sel.value = String(currentClinicId);
  return sel;
}

function page(ctx, titleKey, actions, content) {
  ctx.setTitle(t(titleKey));
  return h("div", { class: "page" },
    h("div", { class: "page-header row-between" },
      h("div", h("h1", t(titleKey)), h("p", { class: "subtitle" }, ctx.dept?.name)),
      h("div", { class: "row gap-sm wrap" }, actions)),
    content);
}

function deferred(ctx, titleKey, build) {
  const holder = h("div", loadingState());
  const actions = h("div", { class: "row gap-sm wrap" });
  let built = null;
  (async () => {
    try {
      const picker = await clinicPicker(() => built?.reload());
      built = build(actions);
      if (picker) actions.prepend(picker);
      mount(holder, built.el);
    } catch (e) {
      mount(holder, errorState(e));
    }
  })();
  return page(ctx, titleKey, actions, holder);
}

// ---------------------------------------------------------------- queue
function renderQueue(ctx) {
  return deferred(ctx, "pharmacy.tab.queue", (actions) => {
    const status = h("select", { class: "select", style: "max-width:160px", onChange: (e) => table.setQuery({ status: e.target.value }) },
      h("option", { value: "open" }, t("pharmacy.filter.open")), h("option", { value: "all" }, t("pharmacy.filter.all")));
    actions.append(status);
    const table = dataTable({
      columns: [
        { key: "prescribed_at", label: t("pharmacy.col.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.prescribed_at)) },
        { key: "patient", label: t("pharmacy.col.patient"), render: (r) => h("span", h("strong", r.patient?.full_name || "—"), " ",
          h("span", { class: "muted ltr" }, r.patient?.code || "")) },
        { key: "items", label: t("pharmacy.col.items"), render: (r) => (r.items || []).map((i) => i.medication_name).join("، ") },
        { key: "doctor", label: t("pharmacy.col.doctor"), render: (r) => r.doctor_name || "—" },
        { key: "clinic", label: t("pharmacy.col.clinic"), render: (r) => r.clinic_name || "" },
        { key: "status", label: t("pharmacy.col.status"), render: (r) => statusPill(r.status, "pharmacy.status") },
      ],
      query: { status: "open" },
      search: { placeholder: t("pharmacy.search") },
      fetch: (q) => api.get("/pharmacy/queue", { query: q }),
      onRowClick: (r) => openDispense(r.id, () => table.reload()),
      empty: { icon: "clipboard", title: t("pharmacy.queue.empty") },
    });
    return table;
  });
}

function medicationSelect(value) {
  // Searchable select: small result list loaded on demand from the catalog (stock at this pharmacy).
  const sel = h("select", { class: "select" }, h("option", { value: "" }, t("pharmacy.pick_medication")));
  const search = h("input", { class: "input", type: "search", placeholder: t("pharmacy.sales.scan") });
  const load = async (q) => {
    const res = await api.get("/pharmacy/medications", { query: { clinic_id: currentClinicId, q: q || undefined, per_page: 50 } });
    const keep = sel.value;
    mount(sel, h("option", { value: "" }, t("pharmacy.pick_medication")),
      res.items.map((m) => h("option", { value: m.id, disabled: qty(m.available) <= 0 },
        `${m.name} — ${t("pharmacy.col.available")}: ${m.available}${m.unit ? ` ${m.unit}` : ""}`)));
    sel.value = keep || (value ? String(value) : "");
  };
  search.addEventListener("input", debounce((e) => load(e.target.value.trim()), 300));
  load("").catch(() => {});
  return { el: h("div", { class: "stack gap-xs" }, search, sel), select: sel };
}

async function openDispense(rxId, onDone) {
  const body = h("div", loadingState());
  const modal = openModal({ title: t("pharmacy.dispense.title"), body, size: "lg" });
  let rx;
  try {
    rx = await api.get(`/pharmacy/prescriptions/${rxId}`);
  } catch (e) {
    mount(body, errorState(e));
    return;
  }
  const pt = rx.patient || {};
  const open = rx.status === "pending" || rx.status === "partially_dispensed";
  const lines = (rx.items || []).map((it) => {
    const remaining = it.quantity != null ? Math.max(0, qty(it.quantity) - qty(it.dispensed_quantity)) : null;
    const med = medicationSelect(it.inventory_item_id);
    const q = h("input", { class: "input", type: "number", min: 0, step: "any", inputmode: "decimal", style: "max-width:120px",
      value: remaining ?? "", max: remaining ?? undefined, disabled: !open });
    const note = h("input", { class: "input", type: "text", maxlength: 500, placeholder: t("pharmacy.dispense.substitution_help"), disabled: !open });
    const err = h("div", { class: "field-error" });
    return { it, med, q, note, err,
      el: h("div", { class: "card card-body stack gap-sm" },
        h("div", { class: "row-between wrap" },
          h("div", h("strong", it.medication_name),
            h("div", { class: "text-sm text-muted" }, [it.dose, it.frequency, it.duration].filter(Boolean).join(" · ")),
            it.instructions ? h("div", { class: "text-sm" }, it.instructions) : null),
          h("div", { class: "text-sm text-muted ltr" },
            `${t("pharmacy.dispense.prescribed")}: ${it.quantity ?? "—"} · ${t("pharmacy.dispense.remaining")}: ${remaining ?? "—"}`)),
        open ? h("div", { class: "form-grid" },
          h("div", { class: "field" }, h("label", t("pharmacy.dispense.medication")), med.el),
          h("div", { class: "field" }, h("label", t("pharmacy.dispense.qty")), q),
          h("div", { class: "field span-2" }, h("label", t("pharmacy.dispense.substitution")), note)) : null,
        err) };
  });
  const complete = h("input", { type: "checkbox" });
  const notes = h("textarea", { class: "textarea", rows: 2, maxlength: 500 });
  const generalErr = h("div", { class: "alert alert-danger", hidden: true });
  const submit = h("button", { class: "btn btn-primary", type: "button" }, icon("check"), t("pharmacy.dispense.action"));
  submit.addEventListener("click", async () => {
    generalErr.hidden = true;
    lines.forEach((l) => { l.err.textContent = ""; });
    const items = lines.map((l) => ({ l, quantity: qty(l.q.value), inv: Number(l.med.select.value) || null }))
      .filter((x) => x.quantity > 0)
      .map(({ l, quantity, inv }) => ({ prescription_item_id: l.it.id, quantity, inventory_item_id: inv || undefined,
        note: l.note.value.trim() || undefined }));
    if (!items.length && !complete.checked) { generalErr.textContent = t("pharmacy.dispense.none_selected"); generalErr.hidden = false; return; }
    submit.disabled = true;
    try {
      await api.post(`/pharmacy/prescriptions/${rx.id}/dispense`, { clinic_id: currentClinicId, version: rx.version, items,
        complete: complete.checked, notes: notes.value.trim() || undefined });
      modal.close();
      toastSuccess(t("pharmacy.dispense.success"));
      onDone && onDone();
    } catch (e) {
      const d = e?.details || {};
      let shown = false;
      for (const [k, msg] of Object.entries(d)) {
        const m = /^items\.(\d+)\./.exec(k);
        const target = m ? lines.find((l) => l.it.id === items[Number(m[1])]?.prescription_item_id) : null;
        if (target) { target.err.textContent = String(msg); shown = true; }
      }
      if (!shown) { generalErr.textContent = e.message || String(e); generalErr.hidden = false; }
    } finally {
      submit.disabled = false;
    }
  });
  const history = (rx.dispensations || []).length ? h("details", { class: "card card-body" },
    h("summary", t("pharmacy.dispense.history")),
    h("ul", rx.dispensations.flatMap((d) => (d.items || []).map((i) =>
      h("li", `${formatDateTime(d.created_at)} — ${i.item_name} × ${i.quantity}${i.note ? ` (${i.note})` : ""}`))))) : null;
  mount(body, h("div", { class: "stack gap-md" },
    h("div", { class: "card card-body row-between wrap" },
      h("div", h("strong", pt.full_name || ""), " ", h("span", { class: "muted ltr" }, pt.code || ""),
        pt.age != null ? h("span", { class: "muted" }, ` · ${t("pharmacy.dispense.age")}: ${pt.age}`) : null),
      statusPill(rx.status, "pharmacy.status")),
    pt.allergies ? h("div", { class: "alert alert-warning" }, icon("alert"), h("strong", `${t("pharmacy.dispense.allergies")}: `), pt.allergies) : null,
    generalErr,
    lines.map((l) => l.el),
    history,
    open ? h("div", { class: "stack gap-sm" },
      h("label", { class: "check" }, complete, t("pharmacy.dispense.complete")),
      h("div", { class: "field" }, h("label", t("pharmacy.dispense.notes")), notes),
      h("div", { class: "row-end gap-sm" }, h("button", { class: "btn", type: "button", onClick: () => modal.close() }, t("core.cancel")), submit))
      : null));
}

// ---------------------------------------------------------------- sales (POS)
function renderSales(ctx) {
  return deferred(ctx, "pharmacy.tab.sales", (actions) => {
    actions.append(h("button", { class: "btn btn-primary", type: "button", onClick: () => openSale(() => table.reload()) },
      icon("plus"), t("pharmacy.sales.new")));
    const table = dataTable({
      columns: [
        { key: "created_at", label: t("pharmacy.col.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.created_at)) },
        { key: "customer", label: t("pharmacy.col.customer"), render: (r) => r.patient_name || r.customer_name || t("pharmacy.sales.walk_in") },
        { key: "total", label: t("pharmacy.col.total"), render: (r) => formatMoney(r.total) },
        { key: "paid", label: t("pharmacy.col.paid"), render: (r) => formatMoney(r.paid_amount) },
        { key: "author", label: t("pharmacy.col.sold_by"), render: (r) => r.author_name || "" },
      ],
      fetch: (q) => api.get("/pharmacy/sales", { query: { ...q, clinic_id: currentClinicId } }),
      empty: { icon: "tag", title: t("pharmacy.sales.empty") },
    });
    return table;
  });
}

function openSale(onDone) {
  const cart = []; // {id, name, unit_price, quantity, available}
  let patient = null;
  const cartBody = h("tbody");
  const totalEl = h("strong", formatMoney("0"));
  const changeEl = h("span", { class: "muted" });
  const paid = h("input", { class: "input", type: "number", min: 0, step: "0.01", inputmode: "decimal", style: "max-width:180px" });
  const customer = h("input", { class: "input", type: "text", maxlength: 200, placeholder: t("pharmacy.sales.customer") });
  const invoice = h("input", { type: "checkbox", disabled: true }); // invoices need a patient
  const generalErr = h("div", { class: "alert alert-danger", hidden: true });
  const total = () => cart.reduce((s, l) => s + l.quantity * Number(l.unit_price || 0), 0);

  function render() {
    mount(cartBody, cart.length ? cart.map((l, i) => {
      const q = h("input", { class: "input", type: "number", min: 0, step: "any", value: l.quantity, style: "max-width:90px",
        onInput: (e) => { l.quantity = qty(e.target.value); renderTotals(); } });
      const price = h("input", { class: "input", type: "number", min: 0, step: "0.01", value: l.unit_price, style: "max-width:120px",
        onInput: (e) => { l.unit_price = e.target.value; renderTotals(); } });
      return h("tr", h("td", h("strong", l.name), h("div", { class: "text-sm muted" }, `${t("pharmacy.col.available")}: ${l.available}`)),
        h("td", q), h("td", price),
        h("td", h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": t("core.delete"),
          onClick: () => { cart.splice(i, 1); render(); } }, icon("trash"))));
    }) : h("tr", h("td", { colspan: 4, class: "muted" }, t("pharmacy.sales.no_items"))));
    renderTotals();
  }
  function renderTotals() {
    totalEl.textContent = formatMoney(total().toFixed(2));
    const diff = qty(paid.value) - total();
    changeEl.textContent = paid.value === "" ? "" : diff >= 0 ? `${t("pharmacy.sales.change")}: ${formatMoney(diff.toFixed(2))}`
      : `${t("pharmacy.sales.balance")}: ${formatMoney((-diff).toFixed(2))}`;
  }
  paid.addEventListener("input", renderTotals);

  function add(m) {
    const ex = cart.find((l) => l.id === m.id);
    if (ex) ex.quantity += 1;
    else cart.push({ id: m.id, name: m.name, unit_price: m.selling_price ?? "0", quantity: 1, available: m.available ?? "?" });
    render();
  }
  async function addByCode(code) {
    try {
      const item = await api.get("/inventory/lookup", { query: { code } });
      if (!item.is_medication) return toast(t("pharmacy.sales.not_found"), { type: "warning" });
      const avail = (item.stock || []).reduce((s, x) => s + qty(x.quantity), 0);
      add({ id: item.id, name: item.name, selling_price: item.selling_price, available: String(avail) });
    } catch (e) {
      toast(e?.status === 404 ? t("pharmacy.sales.not_found") : e.message, { type: "warning" });
    }
  }

  const results = h("div", { class: "search-results" });
  const searchInput = h("input", { class: "input", type: "search", placeholder: t("pharmacy.sales.scan"), autocomplete: "off" });
  searchInput.addEventListener("input", debounce(async (e) => {
    const q = e.target.value.trim();
    if (q.length < 2) return mount(results);
    try {
      const res = await api.get("/pharmacy/medications", { query: { clinic_id: currentClinicId, q, in_stock: true, per_page: 8 } });
      mount(results, res.items.map((m) => h("button", { class: "search-result", type: "button",
        onClick: () => { add(m); searchInput.value = ""; mount(results); searchInput.focus(); } },
      h("strong", m.name), " ", h("span", { class: "muted" }, `${formatMoney(m.selling_price)} · ${m.available}`))));
    } catch (err) { toastApiError(err); }
  }, 250));
  const stopScan = listenBarcode((code) => { searchInput.value = ""; mount(results); addByCode(code); });

  const setPatient = (p) => {
    patient = p;
    invoice.disabled = !p || !can("billing.create");
    invoice.checked = !invoice.disabled;
    mount(patientBox, p ? h("div", { class: "row-between card card-body" }, h("strong", p.full_name),
      h("button", { class: "btn btn-sm", type: "button", "aria-label": t("core.cancel"), onClick: () => setPatient(null) }, "×")) : ps.el);
  };
  const ps = patientSearch({ onSelect: setPatient });
  const patientBox = h("div", ps.el);

  const submit = h("button", { class: "btn btn-primary", type: "button" }, icon("check"), t("pharmacy.sales.new"));
  submit.addEventListener("click", async () => {
    generalErr.hidden = true;
    const items = cart.filter((l) => l.quantity > 0).map((l) => ({ inventory_item_id: l.id, quantity: l.quantity, unit_price: String(l.unit_price) }));
    if (!items.length) { generalErr.textContent = t("pharmacy.sales.no_items"); generalErr.hidden = false; return; }
    submit.disabled = true;
    try {
      await api.post("/pharmacy/sales", { clinic_id: currentClinicId, patient_id: patient?.id, customer_name: customer.value.trim() || undefined,
        paid_amount: paid.value === "" ? total().toFixed(2) : Number(paid.value).toFixed(2), create_invoice: invoice.checked, items });
      modal.close();
      toastSuccess(t("pharmacy.sales.done"));
      onDone && onDone();
    } catch (e) {
      const details = e?.details && typeof e.details === "object" ? Object.values(e.details).join(" · ") : "";
      generalErr.textContent = details ? `${e.message}: ${details}` : (e.message || String(e));
      generalErr.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });

  const modal = openModal({ title: t("pharmacy.sales.new"), size: "lg", onClose: () => stopScan && stopScan(),
    body: h("div", { class: "stack gap-md" },
      generalErr,
      h("div", { class: "search-box" }, icon("search"), searchInput, results),
      h("table", { class: "table" }, h("thead", h("tr", h("th", t("pharmacy.col.name")), h("th", t("pharmacy.col.qty")),
        h("th", t("pharmacy.col.price")), h("th"))), cartBody),
      h("div", { class: "row-between wrap" }, h("span", t("pharmacy.sales.total")), totalEl),
      h("div", { class: "form-grid" },
        h("div", { class: "field" }, h("label", t("pharmacy.sales.paid")), paid, changeEl),
        h("div", { class: "field" }, h("label", t("pharmacy.sales.customer")), customer),
        h("div", { class: "field span-2" }, h("label", t("pharmacy.sales.patient")), patientBox),
        can("billing.create") ? h("label", { class: "check span-2" }, invoice, t("pharmacy.sales.invoice")) : null),
      h("div", { class: "row-end gap-sm" }, h("button", { class: "btn", type: "button", onClick: () => modal.close() }, t("core.cancel")), submit)) });
  render();
  setTimeout(() => searchInput.focus(), 50);
}

// ---------------------------------------------------------------- catalog
function renderCatalog(ctx) {
  return deferred(ctx, "pharmacy.tab.catalog", (actions) => {
    const inStock = h("input", { type: "checkbox", onChange: (e) => table.setQuery({ in_stock: e.target.checked || undefined }) });
    actions.append(h("label", { class: "check" }, inStock, t("pharmacy.catalog.in_stock")));
    const table = dataTable({
      columns: [
        { key: "name", label: t("pharmacy.col.name"), render: (r) => h("span", h("strong", r.name), r.category ? h("span", { class: "muted" }, ` · ${r.category}`) : null) },
        { key: "available", label: t("pharmacy.col.available"), render: (r) => h("span", { class: "row gap-xs" }, `${r.available}${r.unit ? ` ${r.unit}` : ""}`,
          r.low ? h("span", { class: "pill pill--warning" }, t("pharmacy.catalog.low")) : null) },
        { key: "price", label: t("pharmacy.col.price"), render: (r) => formatMoney(r.selling_price) },
        { key: "nearest_expiry", label: t("pharmacy.col.nearest_expiry"), render: (r) => r.nearest_expiry ? formatDate(r.nearest_expiry, { year: "always" }) : "—" },
        { key: "code", label: "SKU / Barcode", render: (r) => h("span", { class: "ltr muted" }, [r.sku, r.barcode].filter(Boolean).join(" · ")) },
      ],
      search: { placeholder: t("pharmacy.sales.scan") },
      fetch: (q) => api.get("/pharmacy/medications", { query: { ...q, clinic_id: currentClinicId } }),
      empty: { icon: "pill", title: t("pharmacy.catalog.empty") },
    });
    return table;
  });
}

// ---------------------------------------------------------------- expiry
function renderExpiry(ctx) {
  return deferred(ctx, "pharmacy.tab.expiry", (actions) => {
    const days = h("select", { class: "select", style: "max-width:200px", "aria-label": t("pharmacy.expiry.days"),
      onChange: (e) => table.setQuery({ days: e.target.value }) },
    [30, 60, 90, 180].map((d) => h("option", { value: d }, `${t("pharmacy.expiry.days")} ${d}`)));
    actions.append(days);
    const table = dataTable({
      columns: [
        { key: "item", label: t("pharmacy.col.name"), render: (r) => h("strong", r.item?.name || "") },
        { key: "lot", label: t("pharmacy.col.lot"), render: (r) => h("span", { class: "ltr" }, r.lot_code || "—") },
        { key: "expiry", label: t("pharmacy.col.expiry"), render: (r) => formatDate(r.expiry_date, { year: "always" }) },
        { key: "days_left", label: t("pharmacy.col.days_left"), render: (r) => String(r.days_left) },
        { key: "qty", label: t("pharmacy.col.qty"), render: (r) => r.quantity },
        { key: "status", label: t("pharmacy.col.status"), render: (r) => statusPill(r.status, "pharmacy.status", r.status === "expired" ? "danger" : "warning") },
      ],
      query: { days: 30 },
      fetch: (q) => api.get("/pharmacy/expiry", { query: { ...q, clinic_id: currentClinicId } }),
      empty: { icon: "check", title: t("pharmacy.expiry.empty") },
    });
    return table;
  });
}
