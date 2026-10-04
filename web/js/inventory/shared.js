// Shared inventory UI helpers: meta, location labels, quantities, item picker (search + USB scanner).
import { api, h, mount, debounce, t, formatNumber, icon, listenBarcode, toast } from "../core/index.js";

export const tt = (key, params) => t(`inventory.${key}`, params);

let metaPromise = null;
/** GET /inventory/meta (cached for the page; pass force after item/location changes). */
export function getMeta(force = false) {
  if (!metaPromise || force) {
    metaPromise = api.get("/inventory/meta", { cache: true }).catch((e) => {
      metaPromise = null;
      throw e;
    });
  }
  return metaPromise;
}

/** Locations relevant to the page: a department page shows that department's clinics + pool only. */
export function pageLocations(meta, ctx) {
  const locs = meta?.locations || [];
  return ctx.area === "department" ? locs.filter((l) => l.department_id === ctx.dept.id) : locs;
}

export function locLabel(l) {
  if (!l) return "";
  if (l.kind === "clinic") return l.name;
  if (l.kind === "department_pool") return tt("loc.pool", { name: l.name });
  return tt("loc.center");
}

export function locById(meta, id) {
  return (meta?.locations || []).find((l) => l.id === Number(id)) || null;
}

export function locOptions(locs) {
  return locs.map((l) => ({ value: l.id, label: locLabel(l) }));
}

/** Quantity string from the API ("12.5") -> localized number with optional unit. */
export function qty(v, unit) {
  if (v == null || v === "") return "";
  const n = formatNumber(v, { max: 3 });
  return unit ? `${n} ${unit}` : n;
}

export function qtyCell(v, unit) {
  return h("span", { class: "num ltr nowrap" }, qty(v, unit));
}

export function itemLabel(i) {
  if (!i) return "";
  const code = i.sku || i.barcode;
  return code ? `${i.name} (${code})` : i.name;
}

/** Department filter for list/report queries on department pages. */
export const deptQuery = (ctx) => (ctx.area === "department" ? { department_id: ctx.dept.id } : {});

/** Look an item up by scanned/typed barcode or SKU. Returns the item or null (toast on miss). */
export async function lookupCode(code) {
  try {
    return await api.get("/inventory/lookup", { query: { code } });
  } catch (e) {
    if (e.status === 404) toast(tt("scan.not_found", { code }), { type: "warning" });
    else toast(e.message, { type: "error" });
    return null;
  }
}

/**
 * Item picker: search box (name / SKU / barcode) with a result list; Enter on an exact code or a
 * USB scan selects the item directly.
 * itemPicker({onSelect(item|null), query: {is_medication, ...}, value: item, autofocus})
 *   -> {el, get(), set(item), focus()}
 */
export function itemPicker({ onSelect, query = {}, value = null, autofocus = false, placeholder } = {}) {
  let current = null;
  let items = [];
  let active = -1;
  let seq = 0;
  const results = h("div", { class: "search-results", role: "listbox", hidden: true });
  const input = h("input", { class: "input", type: "search", autocomplete: "off", autofocus,
    placeholder: placeholder || tt("picker.placeholder"), role: "combobox", "aria-expanded": "false" });
  const searchBox = h("div", { class: "search-box" }, icon("search"), input, results);
  const chip = h("div", { class: "inv-chip", hidden: true });
  const el = h("div", { class: "inv-picker" }, searchBox, chip);

  const close = () => {
    results.hidden = true;
    input.setAttribute("aria-expanded", "false");
  };
  const show = (...nodes) => {
    mount(results, ...nodes);
    results.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };

  function set(item, silent = false) {
    current = item || null;
    if (current) {
      mount(chip, icon("box"), h("span", { class: "inv-chip-name" }, current.name),
        current.sku || current.barcode ? h("span", { class: "text-muted text-sm ltr" }, current.sku || current.barcode) : null,
        h("button", { class: "btn btn-ghost btn-icon btn-sm", type: "button", "aria-label": tt("picker.clear"),
          onClick: () => { set(null); input.focus(); } }, icon("x")));
      chip.hidden = false;
      searchBox.hidden = true;
      close();
    } else {
      chip.hidden = true;
      searchBox.hidden = false;
      input.value = "";
    }
    if (!silent && onSelect) onSelect(current);
  }

  const run = debounce(async () => {
    const q = input.value.trim();
    if (!q) return close();
    const my = ++seq;
    show(h("div", { class: "search-hint" }, t("core.loading")));
    try {
      const res = await api.get("/inventory/items", { query: { ...query, q, active: true, per_page: 10 } });
      if (my !== seq) return;
      items = res.items || [];
      active = -1;
      if (!items.length) return show(h("div", { class: "search-hint" }, tt("picker.none")));
      show(items.map((it, i) => h("button", { class: "search-result", type: "button", role: "option",
        onMouseDown: (e) => { e.preventDefault(); set(items[i]); } },
      h("span", { class: "search-result-name" }, it.name),
      h("span", { class: "search-result-meta" }, [it.category, it.sku && h("span", { class: "ltr" }, it.sku),
        it.barcode && h("span", { class: "ltr" }, it.barcode)].filter(Boolean).flatMap((x, j) => (j ? [" · ", x] : [x]))))));
    } catch (e) {
      if (my === seq) show(h("div", { class: "search-hint" }, e.message));
    }
  }, 250);

  input.addEventListener("input", run);
  input.addEventListener("keydown", async (e) => {
    const btns = [...results.querySelectorAll(".search-result")];
    if (e.key === "ArrowDown" && btns.length) {
      e.preventDefault();
      active = (active + 1) % btns.length;
    } else if (e.key === "ArrowUp" && btns.length) {
      e.preventDefault();
      active = (active - 1 + btns.length) % btns.length;
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (active >= 0 && items[active]) return set(items[active]);
      const code = input.value.trim();
      if (code) {
        const it = await lookupCode(code);
        if (it) set(it);
      }
      return;
    } else if (e.key === "Escape") {
      return close();
    } else {
      return;
    }
    btns.forEach((b, j) => b.classList.toggle("is-active", j === active));
  });
  input.addEventListener("blur", () => setTimeout(close, 150));
  if (value) set(value, true);
  return { el, get: () => current, set, focus: () => (current ? null : input.focus()) };
}

/** While a modal/page is open, USB scans call onItem(item). Returns stop(). */
export function scanToItem(onItem) {
  return listenBarcode(async (code) => {
    const it = await lookupCode(code);
    if (it) onItem(it);
  });
}

export function lowPill(low) {
  return low ? h("span", { class: "pill pill--warning" }, tt("stock.low")) : null;
}

export function scanHint() {
  return h("span", { class: "text-muted text-sm inv-scan-hint" }, icon("barcode"), tt("scan.hint"));
}
