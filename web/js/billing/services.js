// Services & prices management: catalog CRUD (services.manage), price overrides per department/clinic.
import { api, h, t, mount, dataTable, createForm, openModal, toast, toastApiError, confirmDialog, deleteWithUndo,
  can, icon, getDepartments, clinicsOf, getClinics, localName, isCenterWide, managesDepartment, canClinic, formatMoney,
  loadingState, errorState } from "../core/index.js";
import { meta, money, clinicName, deptName } from "./util.js";
import { frame } from "./home.js";

export async function renderServices(ctx) {
  const m = await meta();
  const inDept = ctx.area === "department";
  const manage = can("services.manage");
  const query = { active: "", ...(inDept ? { department_id: ctx.dept.id } : {}) };
  const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v != null));

  const activeOnly = h("label", { class: "check" }, h("input", { type: "checkbox" }), t("billing.services.filter_active"));
  activeOnly.querySelector("input").addEventListener("change", (e) => table.setQuery({ active: e.target.checked ? "true" : "" }));

  const levelLabel = (s) => (s.level === "clinic" ? `${t("billing.services.level.clinic")}: ${clinicName(s.clinic_id)}`
    : s.level === "department" ? `${t("billing.services.level.department")}: ${deptName(s.department_id)}` : t("billing.services.level.center"));
  const canManage = (s) => manage && (s.level === "center" ? isCenterWide()
    : s.level === "department" ? managesDepartment(s.department_id) : canClinic(s.clinic_id));

  const table = dataTable({
    columns: [
      { key: "name", label: t("billing.services.name"), render: (s) => h("span", h("strong", s.name),
        s.category ? h("div", { class: "text-sm text-muted" }, s.category) : null) },
      { key: "level", label: t("billing.services.level"), render: levelLabel },
      { key: "kind", label: t("billing.services.kind"), render: (s) => t(`billing.kind.${s.kind}`) },
      { key: "price", label: t("billing.services.price"), class: "num", render: (s) => money(s.price) },
      { key: "cost", label: t("billing.services.cost"), class: "num", render: (s) => (s.cost != null ? money(s.cost) : "—") },
      { key: "duration", label: t("billing.services.duration"), class: "num", render: (s) => s.duration_minutes ?? "—" },
      { key: "active", label: t("billing.status"), render: (s) => h("span", { class: `pill pill--${s.is_active ? "active" : "archived"}` },
        t(s.is_active ? "billing.services.active" : "billing.services.inactive")) },
      { key: "actions", label: "", class: "actions", render: (s) => h("div", { class: "btn-group" },
        h("button", { class: "btn btn-sm", type: "button", onClick: () => openPrices(s) }, icon("tag"), t("billing.services.prices")),
        canManage(s) ? h("button", { class: "btn btn-sm btn-ghost btn-icon", type: "button", "aria-label": t("billing.services.edit"), onClick: () => openForm(s) }, icon("edit")) : null,
        canManage(s) ? h("button", { class: "btn btn-sm btn-ghost btn-icon", type: "button", "aria-label": t("core.delete"), onClick: () => remove(s) }, icon("trash")) : null) },
    ],
    query,
    perPage: 50,
    search: { placeholder: t("billing.services.search") },
    toolbar: [activeOnly, manage ? h("button", { class: "btn btn-primary", type: "button", onClick: () => openForm(null) }, icon("plus"), t("billing.services.new")) : null],
    fetch: (q) => api.get("/billing/services", { query: clean(q), cache: true }),
    empty: { icon: "tag" },
  });

  async function remove(s) {
    if (!(await confirmDialog({ danger: true }))) return;
    try {
      await deleteWithUndo(`/billing/services/${s.id}`, { message: t("billing.services.deleted"), onDone: table.reload, onUndone: table.reload });
    } catch { /* toast shown */ }
  }

  function levelFields() {
    const depts = getDepartments().filter((d) => isCenterWide() || managesDepartment(d.id));
    const clinics = (inDept ? clinicsOf(ctx.dept.id) : getClinics()).filter((c) => canClinic(c.id));
    const levels = [isCenterWide() && !inDept ? "center" : null, depts.length ? "department" : null, clinics.length ? "clinic" : null].filter(Boolean);
    return [
      { name: "level", label: t("billing.services.level"), type: "select", required: true, empty: false,
        options: levels.map((l) => ({ value: l, label: t(`billing.services.level.${l}`) })) },
      { name: "department_id", label: t("billing.department"), type: "select", numeric: true,
        options: depts.map((d) => ({ value: d.id, label: localName(d, d.name) })) },
      { name: "clinic_id", label: t("billing.clinic"), type: "select", numeric: true, options: clinics.map((c) => ({ value: c.id, label: c.name })) },
    ];
  }

  function openForm(s) {
    const base = [
      { name: "name", label: t("billing.services.name"), required: true, maxLength: 200, span: 2 },
      { name: "category", label: t("billing.services.category"), maxLength: 100, attrs: { list: "billing-cats" } },
      { name: "kind", label: t("billing.services.kind"), type: "select", empty: false, options: m.item_kinds.map((k) => ({ value: k, label: t(`billing.kind.${k}`) })) },
      { name: "price", label: t("billing.services.price"), type: "money", required: true, min: 0 },
      { name: "cost", label: t("billing.services.cost"), type: "money", min: 0 },
      { name: "duration_minutes", label: t("billing.services.duration"), type: "number", min: 1, max: 1440 },
      { name: "is_active", label: t("billing.services.active"), type: "checkbox" },
    ];
    const fields = s ? base : [...levelFields(), ...base];
    const values = s ? { ...s } : { kind: "service", is_active: true, level: inDept ? "department" : undefined, department_id: inDept ? ctx.dept.id : undefined };
    const form = createForm({
      fields, values,
      onSubmit: async (v) => {
        const body = { name: v.name, category: v.category, kind: v.kind, price: v.price, cost: v.cost,
          duration_minutes: v.duration_minutes, is_active: v.is_active };
        if (s) {
          await api.put(`/billing/services/${s.id}`, { ...body, version: s.version });
        } else {
          if (v.level === "department") body.department_id = v.department_id;
          if (v.level === "clinic") body.clinic_id = v.clinic_id;
          await api.post("/billing/services", body);
        }
        modal.close();
        toast(t("billing.services.saved"), { type: "success" });
        table.reload();
      },
    });
    form.el.append(h("datalist", { id: "billing-cats" }, (m.categories || []).map((c) => h("option", { value: c }))));
    const modal = openModal({ title: s ? t("billing.services.edit") : t("billing.services.new"), body: form.el, size: "lg" });
  }

  function openPrices(s) {
    const body = h("div", { class: "stack" }, loadingState());
    const modal = openModal({ title: t("billing.services.price_overrides", { name: s.name }), body, size: "lg" });
    const load = async () => {
      try {
        const res = await api.get(`/billing/services/${s.id}/prices`);
        const rows = res.items;
        const list = rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
          h("thead", h("tr", h("th", t("billing.services.override_level")), h("th", { class: "num" }, t("billing.services.price")), h("th", ""))),
          h("tbody", rows.map((r) => h("tr",
            h("td", { "data-label": t("billing.services.override_level") }, r.clinic_id ? `${t("billing.services.level.clinic")}: ${clinicName(r.clinic_id)}`
              : `${t("billing.services.level.department")}: ${deptName(r.department_id)}`),
            h("td", { class: "num", "data-label": t("billing.services.price") }, money(r.price)),
            h("td", { class: "actions" }, manage ? h("button", { class: "btn btn-sm btn-ghost btn-icon", type: "button", "aria-label": t("core.delete"),
              onClick: async () => {
                try {
                  await api.del(`/billing/services/${s.id}/prices/${r.id}`);
                  toast(t("billing.services.override_removed"), { type: "success" });
                  load();
                } catch (e) { toastApiError(e); }
              } }, icon("trash")) : null))))))
          : h("p", { class: "text-muted" }, t("billing.services.no_overrides"));
        mount(body, h("p", h("strong", t("billing.services.default_price", { price: formatMoney(res.service.price) }))),
          h("p", { class: "text-sm text-muted" }, t("billing.services.override_hint")), list, manage ? overrideForm() : null);
      } catch (e) {
        mount(body, errorState(e, load));
      }
    };
    function overrideForm() {
      // Targets compatible with the service's level and the user's scope.
      const targets = [];
      if (s.level !== "clinic") {
        getDepartments().filter((d) => (s.level === "center" || d.id === s.department_id) && (isCenterWide() || managesDepartment(d.id)))
          .forEach((d) => targets.push({ value: `d:${d.id}`, label: `${t("billing.services.level.department")}: ${localName(d, d.name)}` }));
      }
      getClinics().filter((c) => canClinic(c.id) && (s.level === "center" || (s.level === "department" && c.department_id === s.department_id)
        || c.id === s.clinic_id)).forEach((c) => targets.push({ value: `c:${c.id}`, label: `${t("billing.services.level.clinic")}: ${c.name}` }));
      if (!targets.length) return null;
      const form = createForm({
        columns: 2,
        fields: [{ name: "target", label: t("billing.services.override_level"), type: "select", required: true, options: targets },
          { name: "price", label: t("billing.services.price"), type: "money", required: true, min: 0 }],
        submitLabel: t("billing.services.add_override"),
        onSubmit: async (v) => {
          const [kind, id] = v.target.split(":");
          await api.put(`/billing/services/${s.id}/prices`, { [kind === "c" ? "clinic_id" : "department_id"]: Number(id), price: v.price });
          load();
        },
      });
      return h("div", { class: "card card-pad" }, form.el);
    }
    load();
    return modal;
  }

  return frame(ctx, "services", table.el);
}
