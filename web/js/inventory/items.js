// Item catalog: list, create/edit form, item drawer (stock per location, lots, recent movements).
import {
  api, h, mount, dataTable, createForm, openModal, openDrawer, toastSuccess, deleteWithUndo, confirmDialog, icon,
  formatMoney, formatDate, formatDateTime, loadingState, errorState, listenBarcode,
} from "../core/index.js";
import { tt, getMeta, locById, locLabel, qty, qtyCell, deptQuery, lookupCode } from "./shared.js";
import { openStockOp, openWriteOff, openTransfer } from "./ops.js";

function itemFields(meta, item, ctx) {
  const deptOpts = (meta.departments || []).map((d) => ({ value: d.id, label: d.name }));
  if (meta.can_edit_center_items) deptOpts.unshift({ value: "center", label: tt("item.center_wide") });
  const fields = [
    { name: "name", label: tt("f.name"), required: true, maxLength: 200, span: 2 },
    { name: "category", label: tt("f.category"), maxLength: 100, attrs: { list: "inv-categories" } },
    { name: "unit", label: tt("f.unit"), maxLength: 40, attrs: { list: "inv-units" }, placeholder: tt("f.unit_ph") },
    { name: "sku", label: tt("f.sku"), maxLength: 100 },
    { name: "barcode", label: tt("f.barcode"), maxLength: 100, help: tt("f.barcode_help"), attrs: { "data-barcode": "keep" } },
    { name: "cost", label: tt("f.cost"), type: "money", min: 0 },
    { name: "selling_price", label: tt("f.selling_price"), type: "money", min: 0 },
    { name: "low_stock_threshold", label: tt("f.low_stock_threshold"), type: "number", min: 0, step: "any" },
    { name: "supplier", label: tt("f.supplier"), maxLength: 200 },
  ];
  if (deptOpts.length > 1 || meta.can_edit_center_items) {
    fields.push({ name: "department_id", label: tt("f.department"), type: "select", options: deptOpts, empty: false });
  }
  fields.push({ name: "is_medication", label: tt("f.is_medication"), type: "checkbox" });
  if (item) fields.push({ name: "is_active", label: tt("f.is_active"), type: "checkbox" });
  fields.push({ name: "notes", label: tt("f.notes"), type: "textarea", rows: 2, span: 2, maxLength: 2000 });
  return fields;
}

/** Create (item = null) or edit an item. */
export async function openItemForm(ctx, item, { onSaved, defaults = {} } = {}) {
  const meta = await getMeta();
  const fields = itemFields(meta, item, ctx);
  const defDept = ctx.area === "department" ? ctx.dept.id : (meta.departments?.length === 1 && !meta.can_edit_center_items
    ? meta.departments[0].id : "center");
  const values = item ? { ...item, department_id: item.department_id ?? "center" }
    : { department_id: defDept, is_medication: ctx.dept?.environment === "pharmacy", ...defaults };
  const form = createForm({
    fields, values,
    submitLabel: item ? tt("action.save") : tt("item.create"),
    onSubmit: async (v) => {
      const body = { ...v };
      if ("department_id" in body) body.department_id = body.department_id === "center" || !body.department_id ? null : Number(body.department_id);
      else if (!item && ctx.area === "department") body.department_id = ctx.dept.id;
      const res = item ? await api.patch(`/inventory/items/${item.id}`, { ...body, version: item.version })
        : await api.post("/inventory/items", body);
      modal.close();
      toastSuccess(item ? tt("item.saved") : tt("item.created"));
      getMeta(true);
      if (onSaved) onSaved(res);
    },
  });
  form.el.append(
    h("datalist", { id: "inv-categories" }, (meta.categories || []).map((c) => h("option", { value: c }))),
    h("datalist", { id: "inv-units" }, (meta.units || []).map((c) => h("option", { value: c }))));
  // A scan while the form is open fills the barcode field.
  const stop = listenBarcode((code) => {
    const ctl = form.el.elements.namedItem("barcode");
    if (ctl) ctl.value = code;
  });
  const modal = openModal({ title: item ? tt("item.edit") : tt("item.new"), size: "lg", body: form.el, onClose: stop });
}

/** Item drawer: details, stock per location, lots (with write-off), recent movements. */
export async function openItemDrawer(ctx, itemId, { onChanged } = {}) {
  const body = h("div", { class: "stack" }, loadingState());
  const drawer = openDrawer({ title: tt("item.details"), size: "lg", body });
  const changed = () => { load(); if (onChanged) onChanged(); };
  async function load() {
    try {
      const [meta, item] = await Promise.all([getMeta(), api.get(`/inventory/items/${itemId}`)]);
      const [lots, moves] = await Promise.all([
        api.get("/inventory/lots", { query: { item_id: itemId } }),
        api.get("/inventory/movements", { query: { item_id: itemId, per_page: 10, ...deptQuery(ctx) } }),
      ]);
      render(meta, item, lots.items || [], moves.items || []);
    } catch (e) {
      mount(body, errorState(e, load));
    }
  }
  function render(meta, item, lots, moves) {
    const canEdit = meta.can_edit;
    const actions = h("div", { class: "row inv-actions" },
      canEdit ? h("button", { class: "btn btn-sm", type: "button", onClick: () => openItemForm(ctx, item, { onSaved: changed }) }, icon("edit"), tt("action.edit")) : null,
      canEdit ? h("button", { class: "btn btn-sm", type: "button", onClick: () => openStockOp("receive", ctx, { item, onDone: changed }) }, icon("download"), tt("op.receive.short")) : null,
      canEdit ? h("button", { class: "btn btn-sm", type: "button", onClick: () => openStockOp("use", ctx, { item, onDone: changed }) }, icon("minus"), tt("op.use.short")) : null,
      canEdit ? h("button", { class: "btn btn-sm", type: "button", onClick: () => openTransfer(ctx, { item, onDone: changed }) }, icon("arrowRight", "flip-rtl"), tt("op.transfer.short")) : null,
      meta.can_delete ? h("button", { class: "btn btn-sm btn-danger", type: "button", onClick: async () => {
        if (!(await confirmDialog({ danger: true, message: tt("item.delete_confirm", { name: item.name }) }))) return;
        await deleteWithUndo(`/inventory/items/${item.id}`, { message: tt("item.deleted"), onDone: () => { drawer.close(); if (onChanged) onChanged(); }, onUndone: onChanged });
      } }, icon("trash"), tt("action.delete")) : null);
    const kv = h("dl", { class: "kv" },
      ...[[tt("f.category"), item.category], [tt("f.sku"), item.sku && h("span", { class: "ltr" }, item.sku)],
        [tt("f.barcode"), item.barcode && h("span", { class: "ltr" }, item.barcode)], [tt("f.unit"), item.unit],
        [tt("f.cost"), item.cost && formatMoney(item.cost)], [tt("f.selling_price"), item.selling_price && formatMoney(item.selling_price)],
        [tt("f.low_stock_threshold"), item.low_stock_threshold && qty(item.low_stock_threshold)], [tt("f.supplier"), item.supplier],
        [tt("f.department"), item.department_id ? (meta.departments.find((d) => d.id === item.department_id)?.name || "—") : tt("item.center_wide")],
        [tt("f.notes"), item.notes]].filter(([, v]) => v).flatMap(([k, v]) => [h("dt", k), h("dd", v)]));
    const stockRows = item.stock || [];
    const stockTable = stockRows.length ? h("table", { class: "table" },
      h("thead", h("tr", h("th", tt("f.location")), h("th", { class: "num" }, tt("f.quantity")))),
      h("tbody", stockRows.map((s) => h("tr", h("td", locLabel(locById(meta, s.location_id)) || `#${s.location_id}`),
        h("td", { class: "num" }, qtyCell(s.quantity, item.unit))))))
      : h("p", { class: "text-muted" }, tt("stock.none"));
    const today = new Date().toISOString().slice(0, 10);
    const lotsTable = lots.length ? h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
      h("thead", h("tr", h("th", tt("f.location")), h("th", tt("f.lot_code")), h("th", tt("f.expiry_date")),
        h("th", { class: "num" }, tt("f.quantity")), h("th", ""))),
      h("tbody", lots.map((l) => {
        const loc = locById(meta, l.location_id);
        const expired = l.expiry_date && l.expiry_date < today;
        return h("tr", { class: expired ? "inv-expired" : null },
          h("td", { "data-label": tt("f.location") }, locLabel(loc)),
          h("td", { "data-label": tt("f.lot_code") }, h("span", { class: "ltr" }, l.lot_code || "—")),
          h("td", { "data-label": tt("f.expiry_date") }, l.expiry_date ? formatDate(l.expiry_date, { year: "always" }) : "—",
            expired ? h("span", { class: "pill pill--danger", style: "margin-inline-start:6px" }, tt("expiry.expired")) : null),
          h("td", { class: "num", "data-label": tt("f.quantity") }, qtyCell(l.quantity, item.unit)),
          h("td", { class: "actions" }, canEdit && loc?.can_manage ? h("button", { class: "btn btn-sm btn-ghost", type: "button",
            onClick: () => openWriteOff(ctx, { lot: l, onDone: changed }) }, tt("op.write_off.short")) : null));
      })))) : h("p", { class: "text-muted" }, tt("stock.none"));
    const movesList = moves.length ? h("ul", { class: "inv-moves" }, moves.map((m) => h("li",
      h("span", { class: `pill pill--${Number(m.quantity) < 0 ? "warning" : "success"}` }, tt(`type.${m.type}`)),
      h("span", { class: "num ltr" }, `${Number(m.quantity) > 0 ? "+" : ""}${qty(m.quantity)}`),
      h("span", { class: "text-muted text-sm" }, `${locLabel(locById(meta, m.location_id))} · ${m.author_name} · ${formatDateTime(m.created_at)}`),
      m.reason ? h("span", { class: "text-sm" }, m.reason) : null)))
      : h("p", { class: "text-muted" }, tt("movements.none"));
    mount(body,
      h("div", { class: "row row-between" }, h("h3", { class: "inv-item-title" }, item.name,
        item.is_medication ? h("span", { class: "badge" }, icon("pill"), tt("item.medication")) : null,
        item.is_active ? null : h("span", { class: "pill pill--cancelled" }, tt("item.inactive")))),
      actions, kv,
      h("h4", tt("stock.by_location")), stockTable,
      h("h4", tt("lots.title")), lotsTable,
      h("h4", tt("movements.recent")), movesList);
  }
  load();
}

/** Catalog tab. */
export function itemsTab(ctx, panel) {
  let metaCache = null;
  const catSel = h("select", { class: "select inv-filter", "aria-label": tt("f.category"),
    onChange: () => table.setQuery({ category: catSel.value || undefined }) }, h("option", { value: "" }, tt("filter.all_categories")));
  const kindSel = h("select", { class: "select inv-filter", "aria-label": tt("filter.kind"),
    onChange: () => table.setQuery({ is_medication: kindSel.value || undefined }) },
  h("option", { value: "" }, tt("filter.all_kinds")), h("option", { value: "true" }, tt("item.medications")), h("option", { value: "false" }, tt("item.supplies")));
  const activeSel = h("select", { class: "select inv-filter", "aria-label": tt("f.is_active"),
    onChange: () => table.setQuery({ active: activeSel.value || undefined }) },
  h("option", { value: "true" }, tt("filter.active")), h("option", { value: "false" }, tt("filter.inactive")), h("option", { value: "" }, tt("filter.all")));
  const newBtn = h("button", { class: "btn btn-primary", type: "button", hidden: true,
    onClick: () => openItemForm(ctx, null, { onSaved: () => table.reload() }) }, icon("plus"), tt("item.new"));
  const table = dataTable({
    columns: [
      { key: "name", label: tt("f.name"), render: (r) => h("div", h("div", { class: "inv-name" }, r.name,
        r.is_medication ? h("span", { class: "inv-med", title: tt("item.medication") }, icon("pill")) : null),
      r.category ? h("div", { class: "text-muted text-sm" }, r.category) : null) },
      { key: "code", label: tt("f.sku_barcode"), render: (r) => h("div", { class: "ltr text-sm" }, [r.sku, r.barcode].filter(Boolean).join(" · ")) },
      { key: "unit", label: tt("f.unit") },
      { key: "selling_price", label: tt("f.selling_price"), class: "num", render: (r) => (r.selling_price ? formatMoney(r.selling_price) : "") },
      { key: "low_stock_threshold", label: tt("f.low_stock_threshold"), class: "num", render: (r) => qty(r.low_stock_threshold) },
      { key: "is_active", label: "", render: (r) => (r.is_active ? null : h("span", { class: "pill pill--cancelled" }, tt("item.inactive"))) },
    ],
    query: { active: "true", ...(ctx.area === "department" ? { department_id: ctx.dept.id, include_center: true } : {}) },
    fetch: (q) => api.get("/inventory/items", { query: q, cache: true }),
    search: { placeholder: tt("search.items") },
    toolbar: [catSel, kindSel, activeSel, newBtn],
    onRowClick: (r) => openItemDrawer(ctx, r.id, { onChanged: () => table.reload() }),
    empty: { icon: "box", title: tt("item.empty"), message: tt("item.empty_msg") },
    perPage: 50,
  });
  getMeta().then((m) => {
    metaCache = m;
    newBtn.hidden = !m.can_edit;
    (m.categories || []).forEach((c) => catSel.append(h("option", { value: c }, c)));
  }).catch(() => {});
  // Scan anywhere on the catalog -> open that item (or offer to create it with the code).
  const stop = scanToItemOrCreate(ctx, (it) => openItemDrawer(ctx, it.id, { onChanged: () => table.reload() }),
    (code) => metaCache?.can_edit && openItemForm(ctx, null, { defaults: { barcode: code }, onSaved: () => table.reload() }));
  mount(panel, table.el);
  return stop;
}

function scanToItemOrCreate(ctx, onItem, onMissing) {
  return listenBarcode(async (code) => {
    if (document.querySelector(".overlay")) return; // a dialog handles its own scans
    try {
      onItem(await api.get("/inventory/lookup", { query: { code } }));
    } catch (e) {
      if (e.status === 404 && onMissing) onMissing(code);
      else await lookupCode(code);
    }
  });
}

