// Center-level settings tabs: general settings + branding/logo, plan limits & storage, audit log, backup export.
// Backend: /api/v1/center/{settings,settings/logo,limits,storage,audit,backup/export}.
import {
  api, upload, h, mount, t, can, icon, dataTable, formatDateTime, formatBytes, createForm, handleFormError,
  toastSuccess, toastApiError, loadingState, errorState,
} from "../core/index.js";

export const centerDict = {
  en: {
    "center-admin.center.tab": "Center",
    "center-admin.center.general": "General & branding",
    "center-admin.center.name": "Health center name",
    "center-admin.center.currency": "Currency",
    "center-admin.center.phone": "Phone",
    "center-admin.center.address": "Address",
    "center-admin.center.primary": "Primary color",
    "center-admin.center.secondary": "Secondary color",
    "center-admin.center.footer": "Document footer",
    "center-admin.center.login_message": "Message for staff",
    "center-admin.center.logo": "Logo",
    "center-admin.center.logo_upload": "Upload logo",
    "center-admin.center.logo_remove": "Remove logo",
    "center-admin.center.saved": "Settings saved",
    "center-admin.center.plan": "Plan & limits",
    "center-admin.center.limit": "Limit",
    "center-admin.center.used": "Used",
    "center-admin.center.max": "Maximum",
    "center-admin.center.unlimited": "Unlimited",
    "center-admin.center.storage": "Storage",
    "center-admin.center.storage_line": "{used} of {quota} used ({pct}%)",
    "center-admin.center.status": "Status",
    "center-admin.center.until": "until {date}",
    "center-admin.audit.tab": "Audit log",
    "center-admin.audit.when": "When",
    "center-admin.audit.who": "By",
    "center-admin.audit.what": "Action",
    "center-admin.audit.target": "Target",
    "center-admin.audit.all": "All categories",
    "center-admin.audit.cat.login": "Login",
    "center-admin.audit.cat.department": "Department",
    "center-admin.audit.cat.clinic": "Clinic",
    "center-admin.audit.cat.user": "User",
    "center-admin.backup.tab": "Backup",
    "center-admin.backup.help": "Download a complete export of this health center (all records and uploaded files) as a ZIP archive. Keep it somewhere safe.",
    "center-admin.backup.download": "Download backup",
  },
  ar: {
    "center-admin.center.tab": "المركز",
    "center-admin.center.general": "عام والهوية البصرية",
    "center-admin.center.name": "اسم المركز الصحي",
    "center-admin.center.currency": "العملة",
    "center-admin.center.phone": "الهاتف",
    "center-admin.center.address": "العنوان",
    "center-admin.center.primary": "اللون الأساسي",
    "center-admin.center.secondary": "اللون الثانوي",
    "center-admin.center.footer": "تذييل المستندات",
    "center-admin.center.login_message": "رسالة للموظفين",
    "center-admin.center.logo": "الشعار",
    "center-admin.center.logo_upload": "رفع الشعار",
    "center-admin.center.logo_remove": "إزالة الشعار",
    "center-admin.center.saved": "تم حفظ الإعدادات",
    "center-admin.center.plan": "الخطة والحدود",
    "center-admin.center.limit": "الحد",
    "center-admin.center.used": "المستخدم",
    "center-admin.center.max": "الأقصى",
    "center-admin.center.unlimited": "غير محدود",
    "center-admin.center.storage": "التخزين",
    "center-admin.center.storage_line": "{used} من {quota} مستخدم ({pct}%)",
    "center-admin.center.status": "الحالة",
    "center-admin.center.until": "حتى {date}",
    "center-admin.audit.tab": "سجل التدقيق",
    "center-admin.audit.when": "الوقت",
    "center-admin.audit.who": "بواسطة",
    "center-admin.audit.what": "الإجراء",
    "center-admin.audit.target": "الهدف",
    "center-admin.audit.all": "كل الفئات",
    "center-admin.audit.cat.login": "تسجيل الدخول",
    "center-admin.audit.cat.department": "قسم",
    "center-admin.audit.cat.clinic": "عيادة",
    "center-admin.audit.cat.user": "مستخدم",
    "center-admin.backup.tab": "النسخ الاحتياطي",
    "center-admin.backup.help": "نزّل نسخة كاملة من بيانات هذا المركز (جميع السجلات والملفات المرفوعة) كملف ZIP، واحفظها في مكان آمن.",
    "center-admin.backup.download": "تنزيل النسخة الاحتياطية",
  },
};

const LIMIT_KEYS = { max_departments: "departments", max_clinics: "clinics", max_doctors: "doctors",
  max_receptionists: "receptionists", max_head_doctors: "head doctors" };

export async function centerTab(el) {
  mount(el, loadingState());
  let s, lim;
  try {
    [s, lim] = await Promise.all([api.get("/center/settings"), api.get("/center/limits")]);
  } catch (e) {
    return mount(el, errorState(e, () => centerTab(el)));
  }
  const editable = s.can_edit;
  const fields = [
    { name: "name", label: t("center-admin.center.name"), required: true, maxLength: 200, disabled: !editable },
    { name: "currency", label: t("center-admin.center.currency"), required: true, maxLength: 10, disabled: !editable, attrs: { dir: "ltr" } },
    { name: "phone", label: t("center-admin.center.phone"), type: "tel", maxLength: 40, disabled: !editable, attrs: { dir: "ltr" } },
    { name: "address", label: t("center-admin.center.address"), maxLength: 300, disabled: !editable },
    { name: "primary_color", label: t("center-admin.center.primary"), type: "color", disabled: !editable },
    { name: "secondary_color", label: t("center-admin.center.secondary"), type: "color", disabled: !editable },
    { name: "document_footer", label: t("center-admin.center.footer"), type: "textarea", rows: 2, span: 2, maxLength: 500, disabled: !editable },
    { name: "login_message", label: t("center-admin.center.login_message"), maxLength: 300, span: 2, disabled: !editable },
  ];
  const form = createForm({
    fields, values: s, actions: editable,
    onSubmit: async (v) => {
      try {
        const res = await api.patch("/center/settings", { ...v, version: s.version });
        Object.assign(s, res);
        toastSuccess(t("center-admin.center.saved"));
      } catch (e) { handleFormError(form, e); }
    },
  });

  const logoBox = h("div", { class: "row gap-md wrap" });
  const renderLogo = () => mount(logoBox,
    s.logo_url ? h("img", { src: `${s.logo_url}?v=${s.version}`, alt: t("center-admin.center.logo"), style: "max-height:72px;max-width:220px" }) : h("span", { class: "muted" }, "—"),
    editable ? h("label", { class: "btn btn-sm" }, icon("upload"), t("center-admin.center.logo_upload"),
      h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true, onChange: async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append("file", file, file.name);
        try { Object.assign(s, await upload("/center/settings/logo", fd)); renderLogo(); } catch (err) { toastApiError(err); }
      } })) : null,
    editable && s.logo_url ? h("button", { class: "btn btn-sm btn-danger", type: "button", onClick: async () => {
      try { Object.assign(s, await api.del("/center/settings/logo")); renderLogo(); } catch (err) { toastApiError(err); }
    } }, t("center-admin.center.logo_remove")) : null);
  renderLogo();

  const st = lim.storage || {};
  const pct = st.quota_bytes ? Math.round((1000 * st.used_bytes) / st.quota_bytes) / 10 : 0;
  mount(el, h("div", { class: "stack gap-md" },
    h("section", { class: "card card-body stack gap-sm" }, h("h3", t("center-admin.center.general")),
      h("div", { class: "field" }, h("label", t("center-admin.center.logo")), logoBox), form.el),
    h("section", { class: "card card-body stack gap-sm" }, h("h3", t("center-admin.center.plan")),
      h("div", { class: "muted" }, `${lim.plan?.name || "—"} · ${t("center-admin.center.status")}: ${lim.status}`,
        lim.subscription_ends_at || lim.trial_ends_at ? ` · ${t("center-admin.center.until", { date: formatDateTime(lim.subscription_ends_at || lim.trial_ends_at) })}` : ""),
      h("table", { class: "table" },
        h("thead", h("tr", h("th", t("center-admin.center.limit")), h("th", t("center-admin.center.used")), h("th", t("center-admin.center.max")))),
        h("tbody", lim.limits.map((l) => h("tr", h("td", t(`center-admin.limit.${l.key}`, LIMIT_KEYS[l.key] || l.label)), h("td", String(l.used)),
          h("td", l.max == null ? t("center-admin.center.unlimited") : String(l.max)))))),
      h("h4", t("center-admin.center.storage")),
      h("div", { class: "progress" }, h("span", { style: `width:${Math.min(100, pct)}%` })),
      h("div", { class: "text-sm muted" }, t("center-admin.center.storage_line",
        { used: formatBytes(st.used_bytes || 0), quota: formatBytes(st.quota_bytes || 0), pct }))),
  ));
}

export function auditTab(el) {
  const cat = h("select", { class: "select", style: "max-width:200px", onChange: (e) => table.setQuery({ category: e.target.value || undefined }) },
    h("option", { value: "" }, t("center-admin.audit.all")),
    ["login", "department", "clinic", "user"].map((c) => h("option", { value: c }, t(`center-admin.audit.cat.${c}`))));
  const table = dataTable({
    columns: [
      { key: "created_at", label: t("center-admin.audit.when"), render: (r) => h("span", { class: "nowrap" }, formatDateTime(r.created_at)) },
      { key: "actor", label: t("center-admin.audit.who"), render: (r) => r.actor_name || "—" },
      { key: "what", label: t("center-admin.audit.what"), render: (r) => `${t(`center-admin.audit.cat.${r.category}`, r.category)} · ${r.action}` },
      { key: "target", label: t("center-admin.audit.target"), render: (r) => h("span", { dir: "auto" }, r.target_label || "") },
    ],
    perPage: 50,
    toolbar: [cat],
    fetch: (q) => api.get("/center/audit", { query: q }),
    empty: { icon: "clipboard", title: "—" },
  });
  mount(el, table.el);
}

export function backupTab(el) {
  mount(el, h("div", { class: "card card-body stack gap-md" },
    h("p", t("center-admin.backup.help")),
    h("div", h("a", { class: "btn btn-primary", href: "/api/v1/center/backup/export", download: "" }, icon("download"), t("center-admin.backup.download")))));
}

export const canSeeCenterSettings = () => can("settings.view");
