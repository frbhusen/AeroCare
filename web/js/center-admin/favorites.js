// Manage clinical favorites (note templates, favorite diagnoses, prescription sets, procedures with default
// prices) for one department (departmentId) or the whole center (departmentId = null). Backend: /api/v1/favorites.
import {
  api, h, t, mount, icon, can, dataTable, createForm, handleFormError, openModal, deleteWithUndo, confirmDialog,
  formatMoney,
} from "../core/index.js";

export const favoritesDict = {
  en: {
    "favorites.tab": "Favorites",
    "favorites.help": "Reusable text and sets for daily work: note templates, common diagnoses, prescription sets and procedures with default prices.",
    "favorites.kind": "Type",
    "favorites.kind.snippet": "Note template",
    "favorites.kind.diagnosis": "Diagnosis",
    "favorites.kind.rx_set": "Prescription set",
    "favorites.kind.procedure": "Procedure",
    "favorites.all": "All types",
    "favorites.title": "Name",
    "favorites.body": "Text",
    "favorites.field": "Only for field (optional, e.g. examination)",
    "favorites.price": "Default price",
    "favorites.code": "Code",
    "favorites.scope": "Scope",
    "favorites.scope.center": "Whole center",
    "favorites.scope.department": "This department",
    "favorites.new": "New favorite",
    "favorites.edit": "Edit favorite",
    "favorites.items": "{n} medications",
    "favorites.rx_hint": "Prescription sets are created from the prescription form (“Save as set”).",
    "favorites.deleted": "Favorite deleted",
    "favorites.empty": "No favorites yet",
  },
  ar: {
    "favorites.tab": "المفضلة",
    "favorites.help": "نصوص ومجموعات جاهزة للعمل اليومي: قوالب الملاحظات، التشخيصات الشائعة، مجموعات الوصفات والإجراءات بأسعارها الافتراضية.",
    "favorites.kind": "النوع",
    "favorites.kind.snippet": "قالب ملاحظة",
    "favorites.kind.diagnosis": "تشخيص",
    "favorites.kind.rx_set": "مجموعة وصفة",
    "favorites.kind.procedure": "إجراء",
    "favorites.all": "كل الأنواع",
    "favorites.title": "الاسم",
    "favorites.body": "النص",
    "favorites.field": "لحقل محدد فقط (اختياري، مثل examination)",
    "favorites.price": "السعر الافتراضي",
    "favorites.code": "الرمز",
    "favorites.scope": "النطاق",
    "favorites.scope.center": "كامل المركز",
    "favorites.scope.department": "هذا القسم",
    "favorites.new": "إضافة إلى المفضلة",
    "favorites.edit": "تعديل",
    "favorites.items": "{n} أدوية",
    "favorites.rx_hint": "تُنشأ مجموعات الوصفات من نموذج الوصفة («حفظ كمجموعة»).",
    "favorites.deleted": "تم حذف العنصر",
    "favorites.empty": "لا توجد عناصر مفضلة بعد",
  },
};

const KINDS = ["snippet", "diagnosis", "procedure", "rx_set"];

export function favoritesTab(el, { departmentId = null } = {}) {
  const kindSel = h("select", { class: "select", style: "max-width:200px", "aria-label": t("favorites.kind"),
    onChange: (e) => table.setQuery({ kind: e.target.value || undefined }) },
  h("option", { value: "" }, t("favorites.all")), KINDS.map((k) => h("option", { value: k }, t(`favorites.kind.${k}`))));
  const addBtn = can("medical_records.create") ? h("button", { class: "btn btn-primary", type: "button", onClick: () => openEditor() },
    icon("plus"), t("favorites.new")) : null;
  const table = dataTable({
    columns: [
      { key: "kind", label: t("favorites.kind"), render: (r) => h("span", { class: "pill" }, t(`favorites.kind.${r.kind}`)) },
      { key: "title", label: t("favorites.title"), render: (r) => h("strong", { dir: "auto" }, r.title) },
      { key: "detail", label: t("favorites.body"), render: (r) => r.kind === "rx_set" ? t("favorites.items", { n: (r.payload.items || []).length })
        : r.kind === "procedure" ? (r.payload.price ? formatMoney(r.payload.price) : "—") : h("span", { class: "text-sm", dir: "auto" }, (r.body || "").slice(0, 120)) },
      { key: "scope", label: t("favorites.scope"), render: (r) => r.department_id ? t("favorites.scope.department") : t("favorites.scope.center") },
      { key: "actions", label: "", render: (r) => r.can_manage ? h("span", { class: "row gap-xs" },
        r.kind !== "rx_set" ? h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": t("favorites.edit"),
          onClick: (e) => { e.stopPropagation(); openEditor(r); } }, icon("edit")) : null,
        h("button", { class: "btn btn-sm btn-ghost text-danger", type: "button", "aria-label": t("core.delete"), onClick: async (e) => {
          e.stopPropagation();
          if (!(await confirmDialog({ danger: true, message: t("core.confirm.message") }))) return;
          await deleteWithUndo(`/favorites/${r.id}`, { message: t("favorites.deleted"), onDone: () => table.reload(), onUndone: () => table.reload() }).catch(() => {});
        } }, icon("trash"))) : null },
    ],
    query: { department_id: departmentId || undefined },
    toolbar: [kindSel],
    fetch: (q) => api.get("/favorites", { query: q }),
    empty: { icon: "file", title: t("favorites.empty") },
  });

  function openEditor(row = null) {
    const kind = row?.kind || "snippet";
    const modal = openModal({ title: row ? t("favorites.edit") : t("favorites.new"), size: "md", body: h("div") });
    const fieldsFor = (k) => [
      row ? null : { name: "kind", label: t("favorites.kind"), type: "select", empty: false,
        options: KINDS.filter((x) => x !== "rx_set").map((x) => ({ value: x, label: t(`favorites.kind.${x}`) })) },
      { name: "title", label: t("favorites.title"), required: true, maxLength: 200, span: 2 },
      k === "procedure" ? { name: "price", label: t("favorites.price"), type: "money", min: 0 } : null,
      k === "procedure" ? { name: "code", label: t("favorites.code"), maxLength: 40 } : null,
      k !== "procedure" ? { name: "body", label: t("favorites.body"), type: "textarea", rows: 4, span: 2, required: true, maxLength: 10000, snippets: false } : null,
      k === "snippet" ? { name: "field", label: t("favorites.field"), maxLength: 60, span: 2, attrs: { dir: "ltr" } } : null,
    ].filter(Boolean);
    const render = (k, values) => {
      const form = createForm({
        fields: fieldsFor(k), values, columns: 2,
        onCancel: () => modal.close(),
        onSubmit: async (v) => {
          const body = { title: v.title, body: v.body ?? undefined, field: v.field || null };
          if (k === "procedure") body.payload = { price: v.price || undefined, code: v.code || undefined };
          try {
            if (row) await api.patch(`/favorites/${row.id}`, { ...body, version: row.version });
            else await api.post("/favorites", { ...body, kind: k, department_id: departmentId });
            modal.close();
            table.reload();
          } catch (e) { handleFormError(form, e); }
        },
      });
      const kindCtl = form.el.elements.namedItem("kind");
      if (kindCtl) {
        kindCtl.value = k;
        kindCtl.addEventListener("change", () => render(kindCtl.value, { ...form.values(), kind: kindCtl.value }));
      }
      mount(modal.body, k === "rx_set" ? h("p", t("favorites.rx_hint")) : null, form.el);
    };
    render(kind, row ? { ...row, price: row.payload?.price, code: row.payload?.code } : { kind });
  }

  mount(el, h("div", { class: "stack gap-md" },
    h("div", { class: "row-between wrap gap-sm" }, h("p", { class: "text-muted" }, t("favorites.help")), addBtn),
    table.el));
}
