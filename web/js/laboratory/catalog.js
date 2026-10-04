// Lab test catalog management (categories, tests, units, reference ranges). Editing needs lab.manage_tests and a
// center-wide or laboratory-manager scope (meta.can.manage_tests); others get a read-only view.
import {
  api, h, mount, t, dataTable, createForm, openModal, deleteWithUndo, confirmDialog, icon, tabs, formatMoney,
  loadingState, errorState,
} from "../core/index.js";
import { refRange } from "./common.js";

const lines = (v) => (v ? String(v).split(/\r?\n/).map((s) => s.trim()).filter(Boolean) : []);

export async function renderCatalog(ctx) {
  ctx.setTitle(t("laboratory.catalog.title"));
  const page = h("div", { class: "page" }, loadingState());
  let meta;
  try {
    meta = await api.get("/lab/meta");
  } catch (e) {
    if (e.status === 403 || e.status === 404) throw e;
    mount(page, errorState(e));
    return page;
  }
  const manage = !!meta.can?.manage_tests;
  let categories = [];
  const loadCategories = async () => { categories = (await api.get("/lab/categories")).items || []; };
  await loadCategories();

  let catFilter = "";
  const testTable = dataTable({
    columns: [
      { key: "code", label: t("laboratory.col.code"), render: (r) => h("span", { class: "ltr" }, r.code) },
      { key: "name", label: t("laboratory.col.name"), render: (r) => h("strong", r.name) },
      { key: "category_name", label: t("laboratory.col.category") },
      { key: "result_type", label: t("laboratory.col.type"), render: (r) => t(`laboratory.result_type.${r.result_type}`) },
      { key: "unit", label: t("laboratory.col.unit") },
      { key: "range", label: t("laboratory.col.range"), render: (r) => h("bdi", rangeSummary(r)) },
      { key: "price", label: t("laboratory.col.price"), render: (r) => (r.price != null ? formatMoney(r.price) : "") },
      { key: "is_active", label: t("laboratory.col.active"), render: (r) => (r.is_active ? icon("check") : h("span", { class: "pill pill--neutral" }, "—")) },
      manage ? { key: "actions", label: "", class: "actions", render: (r) => h("button", { class: "btn btn-sm btn-ghost", type: "button",
        "aria-label": t("core.delete"), onClick: () => removeTest(r) }, icon("trash")) } : null,
    ].filter(Boolean),
    fetch: (q) => api.get("/lab/tests", { query: { q: q.q || undefined, category_id: catFilter || undefined } }),
    search: {},
    onRowClick: manage ? (r) => editTest(r) : null,
    toolbar: [categorySelect(), manage ? h("button", { class: "btn btn-primary", type: "button", onClick: () => editTest(null) },
      icon("plus"), t("laboratory.catalog.new_test")) : null],
    empty: { icon: "flask", title: t("laboratory.catalog.empty") },
  });

  function categorySelect() {
    const sel = h("select", { class: "select", style: "width:auto", "aria-label": t("laboratory.col.category") },
      h("option", { value: "" }, t("laboratory.catalog.all_categories")), categories.map((c) => h("option", { value: c.id }, c.name)));
    sel.addEventListener("change", () => { catFilter = sel.value; testTable.reload(); });
    return sel;
  }

  const catTable = dataTable({
    columns: [
      { key: "name", label: t("laboratory.col.name"), render: (r) => h("strong", r.name) },
      { key: "sort_order", label: t("laboratory.catalog.sort_order"), render: (r) => h("span", { class: "num" }, r.sort_order) },
      { key: "is_active", label: t("laboratory.col.active"), render: (r) => (r.is_active ? icon("check") : "—") },
      manage ? { key: "actions", label: "", class: "actions", render: (r) => h("button", { class: "btn btn-sm btn-ghost", type: "button",
        "aria-label": t("core.delete"), onClick: () => removeCategory(r) }, icon("trash")) } : null,
    ].filter(Boolean),
    fetch: async () => { await loadCategories(); return { items: categories, total: categories.length }; },
    onRowClick: manage ? (r) => editCategory(r) : null,
    toolbar: manage ? [h("button", { class: "btn btn-primary", type: "button", onClick: () => editCategory(null) },
      icon("plus"), t("laboratory.catalog.new_category"))] : null,
  });

  function editCategory(c) {
    const form = createForm({
      columns: 1,
      values: c || { sort_order: 100, is_active: true },
      fields: [
        { name: "name", label: t("laboratory.col.name"), required: true, maxLength: 150 },
        { name: "sort_order", label: t("laboratory.catalog.sort_order"), type: "number", min: 0, max: 100000 },
        { name: "is_active", label: t("laboratory.catalog.is_active"), type: "checkbox" },
      ],
      onSubmit: async (v) => {
        if (c) await api.patch(`/lab/categories/${c.id}`, { ...v, version: c.version });
        else await api.post("/lab/categories", v);
        modal.close();
        catTable.reload();
        testTable.reload();
      },
    });
    const modal = openModal({ title: t(c ? "laboratory.catalog.edit_category" : "laboratory.catalog.new_category"), body: form.el, size: "sm" });
  }

  function editTest(tst) {
    const v0 = tst ? { ...tst, choices: (tst.choices || []).join("\n"), normal_choices: (tst.normal_choices || []).join("\n") }
      : { result_type: "numeric", is_active: true, sort_order: 100 };
    const fields = [
      { name: "code", label: t("laboratory.col.code"), required: true, maxLength: 40, attrs: { dir: "ltr" } },
      { name: "name", label: t("laboratory.col.name"), required: true, maxLength: 200 },
      { name: "category_id", label: t("laboratory.col.category"), type: "select", numeric: true,
        options: categories.map((c) => ({ value: c.id, label: c.name })) },
      { name: "result_type", label: t("laboratory.catalog.result_type"), type: "select", empty: false, required: true,
        options: ["numeric", "text", "choice"].map((x) => ({ value: x, label: t(`laboratory.result_type.${x}`) })) },
      { name: "unit", label: t("laboratory.catalog.unit"), maxLength: 40 },
      { name: "price", label: t("laboratory.col.price"), type: "money", min: 0 },
      { type: "section", label: t("laboratory.catalog.ranges") },
      { name: "ref_low", label: t("laboratory.catalog.ref_low"), type: "number", step: "any" },
      { name: "ref_high", label: t("laboratory.catalog.ref_high"), type: "number", step: "any" },
      { name: "ref_low_male", label: t("laboratory.catalog.ref_low_male"), type: "number", step: "any" },
      { name: "ref_high_male", label: t("laboratory.catalog.ref_high_male"), type: "number", step: "any" },
      { name: "ref_low_female", label: t("laboratory.catalog.ref_low_female"), type: "number", step: "any" },
      { name: "ref_high_female", label: t("laboratory.catalog.ref_high_female"), type: "number", step: "any" },
      { name: "ref_text", label: t("laboratory.catalog.ref_text"), maxLength: 255, span: 2 },
      { name: "choices", label: t("laboratory.catalog.choices"), type: "textarea", rows: 3 },
      { name: "normal_choices", label: t("laboratory.catalog.normal_choices"), type: "textarea", rows: 3 },
      { name: "sort_order", label: t("laboratory.catalog.sort_order"), type: "number", min: 0, max: 100000 },
      { name: "is_active", label: t("laboratory.catalog.is_active"), type: "checkbox" },
      { name: "notes", label: t("laboratory.catalog.notes"), type: "textarea", rows: 2, span: 2, maxLength: 2000 },
    ];
    const form = createForm({
      fields, values: v0,
      onSubmit: async (v) => {
        const body = { ...v, choices: lines(v.choices), normal_choices: lines(v.normal_choices) };
        for (const k of ["ref_low", "ref_high", "ref_low_male", "ref_high_male", "ref_low_female", "ref_high_female"]) {
          if (body[k] != null) body[k] = String(body[k]);
        }
        if (tst) await api.patch(`/lab/tests/${tst.id}`, { ...body, version: tst.version });
        else await api.post("/lab/tests", body);
        modal.close();
        testTable.reload();
      },
    });
    // Show only the inputs relevant to the result type.
    const sync = () => {
      const type = form.el.elements.namedItem("result_type").value;
      const show = (name, on) => { const w = form.el.querySelector(`[data-field="${name}"]`); if (w) w.hidden = !on; };
      ["ref_low", "ref_high", "ref_low_male", "ref_high_male", "ref_low_female", "ref_high_female"].forEach((n) => show(n, type === "numeric"));
      ["choices", "normal_choices"].forEach((n) => show(n, type === "choice"));
    };
    form.el.addEventListener("change", (e) => e.target.name === "result_type" && sync());
    sync();
    const modal = openModal({ title: t(tst ? "laboratory.catalog.edit_test" : "laboratory.catalog.new_test"), body: form.el, size: "lg" });
  }

  async function removeTest(r) {
    if (!(await confirmDialog({ danger: true }))) return;
    await deleteWithUndo(`/lab/tests/${r.id}`, { message: t("laboratory.catalog.deleted"), onDone: testTable.reload, onUndone: testTable.reload })
      .catch(() => {});
  }

  async function removeCategory(r) {
    if (!(await confirmDialog({ danger: true }))) return;
    await deleteWithUndo(`/lab/categories/${r.id}`, { message: t("laboratory.catalog.deleted"),
      onDone: () => { catTable.reload(); testTable.reload(); }, onUndone: () => { catTable.reload(); testTable.reload(); } }).catch(() => {});
  }

  const tb = tabs([
    { key: "tests", label: t("laboratory.catalog.tests"), render: (p) => mount(p, testTable.el) },
    { key: "categories", label: t("laboratory.catalog.categories"), render: (p) => mount(p, catTable.el) },
  ]);
  mount(page, h("div", { class: "page-header" }, h("h1", t("laboratory.catalog.title"))),
    manage ? null : h("div", { class: "alert alert-info" }, icon("lock"), h("div", t("laboratory.catalog.no_permission"))),
    tb.el);
  return page;
}

function rangeSummary(r) {
  const parts = [];
  const general = refRange(r);
  if (general) parts.push(general);
  if (r.ref_low_male != null || r.ref_high_male != null) parts.push(`♂ ${refRange({ ref_low: r.ref_low_male, ref_high: r.ref_high_male })}`);
  if (r.ref_low_female != null || r.ref_high_female != null) parts.push(`♀ ${refRange({ ref_low: r.ref_low_female, ref_high: r.ref_high_female })}`);
  if (r.result_type === "choice" && r.normal_choices?.length) parts.push(r.normal_choices.join(" / "));
  return parts.join(" · ");
}
