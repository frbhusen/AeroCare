// Stock operation dialogs: receive, use, adjust, write-off, transfer.
import { api, h, mount, createForm, openModal, toastSuccess, formatDate, icon, handleFormError, field, readValues } from "../core/index.js";
import { tt, getMeta, pageLocations, locOptions, locLabel, itemPicker, scanToItem, qty, itemLabel } from "./shared.js";

/** Lot <select> options for an item at a location (auto FEFO first). */
async function lotOptions(itemId, locationId, includeExpired = true) {
  if (!itemId || !locationId) return [];
  const res = await api.get("/inventory/lots", { query: { item_id: itemId, location_id: locationId } });
  const today = new Date().toISOString().slice(0, 10);
  return (res.items || []).filter((l) => includeExpired || !l.expiry_date || l.expiry_date >= today).map((l) => ({
    value: l.id,
    label: [l.lot_code || tt("lot.no_code"), l.expiry_date ? tt("lot.exp", { date: formatDate(l.expiry_date, { year: "always" }) }) : null,
      tt("lot.qty", { qty: qty(l.quantity) })].filter(Boolean).join(" · "),
  }));
}

function lotSelect() {
  const sel = h("select", { class: "select", name: "lot_id" });
  const wrap = h("div", { class: "field", dataset: { field: "lot_id" } }, h("label", tt("f.lot")), sel);
  async function load(itemId, locationId, includeExpired) {
    const opts = await lotOptions(itemId, locationId, includeExpired).catch(() => []);
    mount(sel, h("option", { value: "" }, tt("lot.auto")), opts.map((o) => h("option", { value: String(o.value) }, o.label)));
  }
  mount(sel, h("option", { value: "" }, tt("lot.auto")));
  return { el: wrap, load, value: () => (sel.value ? Number(sel.value) : null) };
}

/**
 * Generic single-item stock dialog.
 * kind: receive | use | adjust
 */
export async function openStockOp(kind, ctx, { item = null, locationId = null, onDone } = {}) {
  const meta = await getMeta();
  const all = pageLocations(meta, ctx);
  const locs = kind === "use" ? all : all.filter((l) => l.can_manage);
  if (!locs.length) return;
  const picker = itemPicker({ value: item, autofocus: !item, onSelect: () => refreshLots() });
  const lots = kind === "receive" ? null : lotSelect();
  const fields = [
    { name: "location_id", label: tt("f.location"), type: "select", required: true, options: locOptions(locs), empty: locs.length > 1 },
  ];
  if (kind === "adjust") {
    fields.push({ name: "delta", label: tt("f.delta"), type: "number", required: true, step: "any", help: tt("f.delta_help") });
  } else {
    fields.push({ name: "quantity", label: tt("f.quantity"), type: "number", required: true, min: 0, step: "any" });
  }
  if (kind === "receive") {
    fields.push(
      { name: "lot_code", label: tt("f.lot_code"), maxLength: 100 },
      { name: "expiry_date", label: tt("f.expiry_date"), type: "date" },
      { name: "unit_cost", label: tt("f.unit_cost"), type: "money", min: 0 },
    );
  }
  fields.push({ name: "reason", label: tt(kind === "adjust" ? "f.reason_required" : "f.reason"), required: kind === "adjust", span: 2, maxLength: 300 });
  const initialLoc = locationId && locs.some((l) => l.id === Number(locationId)) ? locationId : (locs.length === 1 ? locs[0].id : "");
  const form = createForm({
    fields,
    values: { location_id: initialLoc, unit_cost: item?.cost || "" },
    submitLabel: tt(`op.${kind}.submit`),
    onSubmit: async (v) => {
      const it = picker.get();
      if (!it) return form.showError(tt("picker.required"));
      const body = { ...v, item_id: it.id, location_id: Number(v.location_id) };
      if (lots && lots.value()) body.lot_id = lots.value();
      const res = await api.post(`/inventory/${kind}`, body);
      modal.close();
      toastSuccess(tt(`op.${kind}.done`, { item: it.name, qty: qty(res.quantity) }));
      if (onDone) onDone(res);
    },
  });
  const locSel = form.el.elements.namedItem("location_id");
  function refreshLots() {
    if (lots) lots.load(picker.get()?.id, locSel.value, kind !== "use");
  }
  locSel.addEventListener("change", refreshLots);
  if (lots) form.el.querySelector(".form-grid").append(lots.el);
  refreshLots();
  const stop = scanToItem((it) => { picker.set(it); });
  const modal = openModal({
    title: tt(`op.${kind}.title`), size: "lg", onClose: stop,
    body: [h("div", { class: "field" }, h("label", tt("f.item"), h("span", { class: "req" }, "*")), picker.el), form.el],
  });
}

/** Write off all expired lots at a location (optionally one item), or a single lot. */
export async function openWriteOff(ctx, { lot = null, item = null, onDone } = {}) {
  const meta = await getMeta();
  const locs = pageLocations(meta, ctx).filter((l) => l.can_manage);
  if (!locs.length) return;
  const fields = lot
    ? [{ name: "quantity", label: tt("f.quantity"), type: "number", step: "any", min: 0, help: tt("writeoff.qty_help", { qty: qty(lot.quantity) }) },
      { name: "reason", label: tt("f.reason"), maxLength: 300, span: 2 }]
    : [{ name: "location_id", label: tt("f.location"), type: "select", required: true, options: locOptions(locs), empty: locs.length > 1 },
      { name: "reason", label: tt("f.reason"), maxLength: 300 }];
  const form = createForm({
    fields,
    values: { location_id: locs.length === 1 ? locs[0].id : "", reason: tt("writeoff.default_reason") },
    submitLabel: tt("op.write_off.submit"),
    onSubmit: async (v) => {
      const body = lot ? { location_id: lot.location_id, lot_id: lot.id, quantity: v.quantity, reason: v.reason }
        : { location_id: Number(v.location_id), reason: v.reason, item_id: item?.id };
      const res = await api.post("/inventory/write-off", body);
      modal.close();
      const total = (res.written_off || []).reduce((s, x) => s + Number(x.quantity), 0);
      toastSuccess(res.written_off?.length ? tt("op.write_off.done", { qty: qty(total) }) : tt("op.write_off.nothing"));
      if (onDone) onDone(res);
    },
  });
  const intro = lot ? h("p", tt("writeoff.lot_intro", { lot: lot.lot_code || tt("lot.no_code"), qty: qty(lot.quantity) }))
    : h("p", item ? tt("writeoff.item_intro", { item: item.name }) : tt("writeoff.all_intro"));
  const modal = openModal({ title: tt("op.write_off.title"), body: [intro, form.el] });
}

/** Transfer one or more items between two locations. */
export async function openTransfer(ctx, { item = null, fromId = null, onDone } = {}) {
  const meta = await getMeta();
  const locs = pageLocations(meta, ctx);
  // Destinations: any visible location (a department page may also send to the center pool / other pools).
  const dests = meta.locations;
  const lines = [];
  const linesEl = h("div", { class: "stack inv-lines" });
  const picker = itemPicker({ value: null, autofocus: true, onSelect: (it) => { if (it) addLine(it); } });

  function addLine(it) {
    picker.set(null, true);
    const existing = lines.find((l) => l.item.id === it.id);
    if (existing) {
      existing.input.focus();
      return;
    }
    const input = h("input", { class: "input inv-qty-input", type: "number", min: "0", step: "any", value: "1", "aria-label": tt("f.quantity") });
    const line = { item: it, input };
    lines.push(line);
    renderLines();
    input.focus();
    input.select();
  }
  function renderLines() {
    mount(linesEl, lines.length ? lines.map((l, i) => h("div", { class: "row inv-line" },
      h("span", { class: "inv-line-name" }, itemLabel(l.item)), l.input,
      h("button", { class: "btn btn-ghost btn-icon btn-sm", type: "button", "aria-label": tt("action.remove"),
        onClick: () => { lines.splice(i, 1); renderLines(); } }, icon("trash"))))
      : h("p", { class: "text-muted text-sm" }, tt("transfer.no_lines")));
  }
  renderLines();
  if (item) addLine(item);

  const fieldsSpec = [
    { name: "from_location_id", label: tt("f.from"), type: "select", required: true, options: locOptions(locs) },
    { name: "to_location_id", label: tt("f.to"), type: "select", required: true, options: locOptions(dests) },
    { name: "notes", label: tt("f.notes"), maxLength: 500, span: 2 },
  ];
  const grid = h("div", { class: "form-grid" }, fieldsSpec.map((f) => field(f, f.name === "from_location_id" ? (fromId || (locs.length === 1 ? locs[0].id : "")) : "")));
  const formEl = h("form", { class: "form", novalidate: true }, grid,
    h("div", { class: "field" }, h("label", tt("transfer.items")), picker.el), linesEl);
  const formApi = {
    el: formEl,
    setErrors: (d) => { formApi.showError(Object.entries(d).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ")); },
    showError: (m) => { formEl.querySelector(".form-error-summary")?.remove(); formEl.prepend(h("div", { class: "form-error-summary", role: "alert" }, m)); },
  };
  const stop = scanToItem(addLine);
  const modal = openModal({
    title: tt("op.transfer.title"), size: "lg", onClose: stop, body: formEl,
    actions: [
      { label: tt("action.cancel") },
      { label: tt("op.transfer.submit"), variant: "primary", onClick: async () => {
        const v = readValues(formEl, fieldsSpec);
        if (!v.from_location_id || !v.to_location_id) return formApi.showError(tt("transfer.pick_locations")), false;
        if (v.from_location_id === v.to_location_id) return formApi.showError(tt("transfer.same_location")), false;
        if (!lines.length) return formApi.showError(tt("transfer.no_lines")), false;
        try {
          const tr = await api.post("/inventory/transfers", {
            from_location_id: Number(v.from_location_id), to_location_id: Number(v.to_location_id), notes: v.notes,
            items: lines.map((l) => ({ item_id: l.item.id, quantity: Number(l.input.value) })),
          });
          toastSuccess(tt("op.transfer.done", { from: locLabel(tr.from_location), to: locLabel(tr.to_location) }));
          if (onDone) onDone(tr);
          return true;
        } catch (e) {
          handleFormError(formApi, e);
          return false;
        }
      } },
    ],
  });
}
