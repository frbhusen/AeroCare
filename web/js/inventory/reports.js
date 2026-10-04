// Stock levels, movements, transfers, low-stock and expiry views.
import { api, h, mount, dataTable, openModal, icon, formatDate, formatDateTime, loadingState, errorState, listenBarcode } from "../core/index.js";
import { tt, getMeta, pageLocations, locById, locLabel, qty, qtyCell, lowPill, deptQuery, lookupCode, scanHint } from "./shared.js";
import { openItemDrawer } from "./items.js";
import { openStockOp, openWriteOff, openTransfer } from "./ops.js";

const MOVE_TYPES = ["receive", "use", "adjust", "transfer_out", "transfer_in", "dispense", "sale", "write_off"];

function locationSelect(meta, ctx, onChange, { allLabel = tt("filter.all_locations"), value = "" } = {}) {
  const sel = h("select", { class: "select inv-filter", "aria-label": tt("f.location"), onChange: () => onChange(sel.value ? Number(sel.value) : undefined) },
    h("option", { value: "" }, allLabel), pageLocations(meta, ctx).map((l) => h("option", { value: String(l.id) }, locLabel(l))));
  sel.value = String(value || "");
  return sel;
}

function itemCell(item) {
  return h("div", h("div", { class: "inv-name" }, item.name),
    [item.sku, item.barcode].some(Boolean) ? h("div", { class: "text-muted text-sm ltr" }, [item.sku, item.barcode].filter(Boolean).join(" · ")) : null);
}

/** Stock levels tab with the operation buttons. */
export async function stockTab(ctx, panel) {
  mount(panel, loadingState());
  let meta;
  try {
    meta = await getMeta();
  } catch (e) {
    mount(panel, errorState(e, () => stockTab(ctx, panel)));
    return null;
  }
  const initialLoc = ctx.query?.location_id ? Number(ctx.query.location_id) : undefined;
  const reload = () => table.reload();
  const zero = h("input", { type: "checkbox", onChange: () => table.setQuery({ include_zero: zero.checked || undefined }) });
  const ops = meta.can_edit ? h("div", { class: "row inv-ops" },
    h("button", { class: "btn btn-primary", type: "button", onClick: () => openStockOp("receive", ctx, { locationId: table.getQuery().location_id, onDone: reload }) }, icon("download"), tt("op.receive.short")),
    h("button", { class: "btn", type: "button", onClick: () => openStockOp("use", ctx, { locationId: table.getQuery().location_id, onDone: reload }) }, icon("minus"), tt("op.use.short")),
    h("button", { class: "btn", type: "button", onClick: () => openStockOp("adjust", ctx, { locationId: table.getQuery().location_id, onDone: reload }) }, icon("sliders"), tt("op.adjust.short")),
    h("button", { class: "btn", type: "button", onClick: () => openTransfer(ctx, { fromId: table.getQuery().location_id, onDone: reload }) }, icon("arrowRight", "flip-rtl"), tt("op.transfer.short")),
    h("button", { class: "btn", type: "button", onClick: () => openWriteOff(ctx, { onDone: reload }) }, icon("trash"), tt("op.write_off.short")),
    scanHint()) : null;
  const table = dataTable({
    columns: [
      { key: "item", label: tt("f.item"), render: (r) => itemCell(r.item) },
      { key: "location", label: tt("f.location"), render: (r) => locLabel(locById(meta, r.location_id)) },
      { key: "quantity", label: tt("f.quantity"), class: "num", render: (r) => h("span", qtyCell(r.quantity, r.item.unit), " ", lowPill(r.low)) },
      { key: "usable", label: tt("stock.usable"), class: "num", render: (r) => (r.expired_quantity !== "0" ? qtyCell(r.usable_quantity) : "") },
      { key: "expired", label: tt("stock.expired"), class: "num", render: (r) => (r.expired_quantity !== "0"
        ? h("span", { class: "inv-expired-qty" }, qtyCell(r.expired_quantity)) : "") },
      { key: "nearest_expiry", label: tt("stock.nearest_expiry"), render: (r) => (r.nearest_expiry ? formatDate(r.nearest_expiry, { year: "always" }) : "") },
    ],
    query: { location_id: initialLoc, ...deptQuery(ctx) },
    fetch: (q) => api.get("/inventory/stock", { query: q, cache: true }),
    search: { placeholder: tt("search.stock") },
    toolbar: [locationSelect(meta, ctx, (v) => table.setQuery({ location_id: v }), { value: initialLoc }),
      h("label", { class: "check inv-filter" }, zero, tt("stock.include_zero"))],
    onRowClick: (r) => openItemDrawer(ctx, r.item.id, { onChanged: reload }),
    empty: { icon: "box", title: tt("stock.empty"), message: meta.can_edit ? tt("stock.empty_msg") : null },
    perPage: 50,
  });
  // A scan on the stock page opens the scanned item.
  const stop = listenBarcode(async (code) => {
    if (document.querySelector(".overlay")) return;
    const it = await lookupCode(code);
    if (it) openItemDrawer(ctx, it.id, { onChanged: reload });
  });
  mount(panel, ops, table.el);
  return stop;
}

export async function movementsTab(ctx, panel) {
  const meta = await getMeta().catch(() => ({ locations: [] }));
  const typeSel = h("select", { class: "select inv-filter", "aria-label": tt("f.type"), onChange: () => table.setQuery({ type: typeSel.value || undefined }) },
    h("option", { value: "" }, tt("filter.all_types")), MOVE_TYPES.map((x) => h("option", { value: x }, tt(`type.${x}`))));
  const from = h("input", { class: "input inv-filter", type: "date", "aria-label": tt("f.date_from"), onChange: () => table.setQuery({ date_from: from.value || undefined }) });
  const to = h("input", { class: "input inv-filter", type: "date", "aria-label": tt("f.date_to"), onChange: () => table.setQuery({ date_to: to.value || undefined }) });
  const table = dataTable({
    columns: [
      { key: "created_at", label: tt("f.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.created_at)) },
      { key: "item_name", label: tt("f.item") },
      { key: "location", label: tt("f.location"), render: (r) => locLabel(locById(meta, r.location_id)) },
      { key: "type", label: tt("f.type"), render: (r) => h("span", { class: `pill pill--${Number(r.quantity) < 0 ? "warning" : "success"}` }, tt(`type.${r.type}`)) },
      { key: "quantity", label: tt("f.quantity"), class: "num", render: (r) => h("span", { class: "num ltr" }, `${Number(r.quantity) > 0 ? "+" : ""}${qty(r.quantity)}`) },
      { key: "balance_after", label: tt("movements.balance"), class: "num", render: (r) => qtyCell(r.balance_after) },
      { key: "reason", label: tt("f.reason"), render: (r) => r.reason || "" },
      { key: "author_name", label: tt("f.by") },
    ],
    query: deptQuery(ctx),
    fetch: (q) => api.get("/inventory/movements", { query: q, cache: true }),
    toolbar: [locationSelect(meta, ctx, (v) => table.setQuery({ location_id: v })), typeSel, from, to],
    empty: { icon: "layers", title: tt("movements.none") },
    perPage: 50,
  });
  mount(panel, table.el);
}

function openTransferDetail(id) {
  const body = h("div", loadingState());
  openModal({ title: tt("transfer.details"), size: "lg", body });
  api.get(`/inventory/transfers/${id}`).then((tr) => mount(body,
    h("dl", { class: "kv" }, h("dt", tt("f.from")), h("dd", locLabel(tr.from_location)), h("dt", tt("f.to")), h("dd", locLabel(tr.to_location)),
      h("dt", tt("f.date")), h("dd", formatDateTime(tr.created_at)), h("dt", tt("f.by")), h("dd", tr.author_name),
      tr.notes ? h("dt", tt("f.notes")) : null, tr.notes ? h("dd", tr.notes) : null),
    h("table", { class: "table", style: "margin-top:16px" },
      h("thead", h("tr", h("th", tt("f.item")), h("th", { class: "num" }, tt("f.quantity")), h("th", tt("lots.title")))),
      h("tbody", tr.items.map((i) => h("tr", h("td", i.item_name), h("td", { class: "num" }, qtyCell(i.quantity)),
        h("td", { class: "text-sm" }, i.lots.map((l) => `${l.lot_code || tt("lot.no_code")}${l.expiry_date ? ` (${formatDate(l.expiry_date, { year: "always" })})` : ""}: ${qty(l.quantity)}`).join(" · "))))))))
    .catch((e) => mount(body, errorState(e)));
}

export async function transfersTab(ctx, panel) {
  const meta = await getMeta().catch(() => ({ locations: [], can_edit: false }));
  const table = dataTable({
    columns: [
      { key: "created_at", label: tt("f.date"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.created_at)) },
      { key: "from", label: tt("f.from"), render: (r) => locLabel(r.from_location) },
      { key: "to", label: tt("f.to"), render: (r) => locLabel(r.to_location) },
      { key: "notes", label: tt("f.notes"), render: (r) => r.notes || "" },
      { key: "author_name", label: tt("f.by") },
    ],
    query: deptQuery(ctx),
    fetch: (q) => api.get("/inventory/transfers", { query: q, cache: true }),
    toolbar: [locationSelect(meta, ctx, (v) => table.setQuery({ location_id: v })),
      meta.can_edit ? h("button", { class: "btn btn-primary", type: "button", onClick: () => openTransfer(ctx, { onDone: () => table.reload() }) },
        icon("plus"), tt("op.transfer.title")) : null],
    onRowClick: (r) => openTransferDetail(r.id),
    empty: { icon: "layers", title: tt("transfer.none") },
  });
  mount(panel, table.el);
}

export async function lowStockTab(ctx, panel) {
  const meta = await getMeta().catch(() => ({ locations: [] }));
  const table = dataTable({
    columns: [
      { key: "item", label: tt("f.item"), render: (r) => itemCell(r.item) },
      { key: "location", label: tt("f.location"), render: (r) => locLabel(locById(meta, r.location_id)) },
      { key: "quantity", label: tt("f.quantity"), class: "num", render: (r) => qtyCell(r.quantity, r.item.unit) },
      { key: "threshold", label: tt("f.low_stock_threshold"), class: "num", render: (r) => qtyCell(r.item.low_stock_threshold) },
    ],
    query: deptQuery(ctx),
    fetch: (q) => api.get("/inventory/low-stock", { query: q, cache: true }),
    toolbar: [locationSelect(meta, ctx, (v) => table.setQuery({ location_id: v }))],
    onRowClick: (r) => openItemDrawer(ctx, r.item.id, { onChanged: () => table.reload() }),
    empty: { icon: "check", title: tt("low.none") },
  });
  mount(panel, table.el);
}

export function expiryStatus(r) {
  return r.status === "expired" ? h("span", { class: "pill pill--danger" }, tt("expiry.expired"))
    : h("span", { class: "pill pill--warning" }, tt("expiry.days_left", { n: r.days_left }));
}

export function daysSelect(onChange, value = 30) {
  const sel = h("select", { class: "select inv-filter", "aria-label": tt("expiry.window"), onChange: () => onChange(Number(sel.value)) },
    [0, 30, 60, 90, 180, 365].map((d) => h("option", { value: String(d) }, d ? tt("expiry.within", { n: d }) : tt("expiry.only_expired"))));
  sel.value = String(value);
  return sel;
}

export async function expiryTab(ctx, panel) {
  const meta = await getMeta().catch(() => ({ locations: [], can_edit: false }));
  const table = dataTable({
    columns: [
      { key: "item", label: tt("f.item"), render: (r) => itemCell(r.item) },
      { key: "location", label: tt("f.location"), render: (r) => locLabel(locById(meta, r.location_id)) },
      { key: "lot_code", label: tt("f.lot_code"), render: (r) => h("span", { class: "ltr" }, r.lot_code || "—") },
      { key: "expiry_date", label: tt("f.expiry_date"), render: (r) => formatDate(r.expiry_date, { year: "always" }) },
      { key: "status", label: "", render: expiryStatus },
      { key: "quantity", label: tt("f.quantity"), class: "num", render: (r) => qtyCell(r.quantity, r.item.unit) },
      { key: "actions", label: "", class: "actions", render: (r) => (meta.can_edit && locById(meta, r.location_id)?.can_manage
        ? h("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => openWriteOff(ctx, { lot: r, onDone: () => table.reload() }) },
          tt("op.write_off.short")) : null) },
    ],
    query: { days: 30, ...deptQuery(ctx) },
    fetch: (q) => api.get("/inventory/expiry", { query: q, cache: true }),
    toolbar: [locationSelect(meta, ctx, (v) => table.setQuery({ location_id: v })), daysSelect((d) => table.setQuery({ days: d }))],
    empty: { icon: "check", title: tt("expiry.none") },
  });
  mount(panel, table.el);
}
