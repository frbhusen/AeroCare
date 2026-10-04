// Data table with server pagination (API list shape {items, page, per_page, total}).
import { h, mount, debounce } from "../core/dom.js";
import { t, formatNumber } from "../core/i18n.js";
import { loadingState, emptyState, errorState, offlineCopyBanner } from "./states.js";
import { icon } from "./icons.js";

/**
 * dataTable({
 *   columns: [{key, label, render?: (row) => Node|string, class?, width?}],
 *   fetch?: ({page, per_page, ...query}) => Promise<{items, total, page, per_page}>,   // server mode
 *   rows?: [...],                                                                      // static mode
 *   query?: {}            initial filters passed to fetch
 *   perPage?: 25, onRowClick?: (row) => void, rowClass?: (row) => string,
 *   search?: {placeholder, param: "q"}   adds a debounced search input in the toolbar
 *   toolbar?: Node[]      extra toolbar nodes (filters, buttons)
 *   empty?: {title, message, icon, action}
 * }) -> {el, reload(), setQuery(patch), getQuery(), setRows(rows)}
 */
export function dataTable(opts) {
  const { columns, fetch, perPage = 25, onRowClick, rowClass, search, toolbar, empty } = opts;
  let query = { ...(opts.query || {}) };
  let page = 1;
  let rows = opts.rows || [];
  let seq = 0;

  const body = h("div");
  const pager = h("div", { class: "pagination" });
  const toolbarEl = (search || toolbar)
    ? h("div", { class: "table-toolbar" },
      search ? h("div", { class: "search-box", style: "flex:1;min-width:200px;max-width:340px" }, icon("search"),
        h("input", { class: "input", type: "search", placeholder: search.placeholder || t("core.search"),
          value: query[search.param || "q"] || "",
          onInput: debounce((e) => setQuery({ [search.param || "q"]: e.target.value.trim() }), 300) })) : null,
      toolbar || null)
    : null;
  const el = h("div", { class: "card data-table" }, toolbarEl, body, pager);

  function renderRows(items, banner) {
    if (!items.length) {
      mount(body, banner, emptyState(empty || {}));
      return;
    }
    const thead = h("thead", h("tr", columns.map((c) => h("th", { class: c.class, style: c.width ? `width:${c.width}` : null }, c.label ?? ""))));
    const tbody = h("tbody", items.map((row) => {
      const tr = h("tr", { class: [onRowClick && "is-clickable", rowClass && rowClass(row)] },
        columns.map((c) => {
          const v = c.render ? c.render(row) : row[c.key];
          return h("td", { class: c.class, "data-label": typeof c.label === "string" ? c.label : "" }, v ?? "");
        }));
      if (onRowClick) {
        tr.tabIndex = 0;
        tr.addEventListener("click", (e) => {
          if (e.target.closest("button, a, input, select, label")) return;
          onRowClick(row);
        });
        tr.addEventListener("keydown", (e) => e.key === "Enter" && e.target === tr && onRowClick(row));
      }
      return tr;
    }));
    mount(body, banner, h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" }, thead, tbody)));
  }

  function renderPager(total, per) {
    if (!fetch) return mount(pager);
    const pages = Math.max(1, Math.ceil(total / per));
    const from = total ? (page - 1) * per + 1 : 0;
    const to = Math.min(total, page * per);
    mount(pager,
      h("span", t("core.table.range", { from: formatNumber(from), to: formatNumber(to), total: formatNumber(total) })),
      h("div", { class: "btn-group" },
        h("button", { class: "btn btn-sm", type: "button", disabled: page <= 1, onClick: () => go(page - 1), "aria-label": t("core.table.prev") },
          icon("chevronLeft", "flip-rtl")),
        h("span", { class: "nowrap", style: "align-self:center" }, t("core.table.page", { page: formatNumber(page), pages: formatNumber(pages) })),
        h("button", { class: "btn btn-sm", type: "button", disabled: page >= pages, onClick: () => go(page + 1), "aria-label": t("core.table.next") },
          icon("chevronRight", "flip-rtl"))));
  }

  async function load() {
    if (!fetch) {
      renderRows(rows);
      return;
    }
    const my = ++seq;
    mount(body, loadingState());
    try {
      const res = await fetch({ ...query, page, per_page: perPage });
      if (my !== seq) return;
      const items = Array.isArray(res) ? res : res?.items || [];
      renderRows(items, offlineCopyBanner(res));
      renderPager(res?.total ?? items.length, res?.per_page || perPage);
    } catch (e) {
      if (my !== seq) return;
      mount(body, errorState(e, load));
      mount(pager);
    }
  }

  function go(p) {
    page = Math.max(1, p);
    load();
  }

  function setQuery(patch) {
    query = { ...query, ...patch };
    page = 1;
    return load();
  }

  load();
  return {
    el,
    reload: load,
    setQuery,
    getQuery: () => ({ ...query }),
    setRows(next) {
      rows = next || [];
      renderRows(rows);
    },
  };
}
