// Reusable files panel for a patient (optionally one visit): upload (drag & drop, multiple), list, preview,
// image viewer with annotations, rename, explicit sharing, delete with undo. Backend: /api/v1/files.
//   import { filesPanel } from "../files/panel.js";
//   mount(el, filesPanel({ ctx, patient, visit, compact }))
import {
  api, h, mount, t, can, icon, formatDateTime, formatBytes, toastSuccess, toastApiError, openModal, confirmDialog,
  deleteWithUndo, createForm, handleFormError, loadingState, errorState, emptyState,
} from "../core/index.js";
import { createUploader } from "../components/uploader.js";
import { openImageViewer } from "../components/image-viewer.js";

const VIEWABLE_IMAGES = ["image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"];
let metaPromise = null;
const loadMeta = () => (metaPromise ||= api.get("/files/meta").catch((e) => { metaPromise = null; throw e; }));
const catLabel = (c) => t(`files.cat.${c}`, c);

export function filesPanel({ ctx, patient, visit, compact = false } = {}) {
  const container = h("div", { class: ["files-panel", compact && "files-panel--compact"] });
  const toolbar = h("div", { class: "files-toolbar row-between wrap gap-sm" });
  const uploaderWrap = h("div", { class: "files-uploader-wrap" });
  const listEl = h("div", { class: "files-grid" });
  const usage = h("div", { class: "text-sm muted" });
  let meta = null;
  let categoryFilter = "";
  let uploaderOpen = false;

  async function load() {
    mount(listEl, loadingState());
    try {
      meta = await loadMeta();
      const res = await api.get("/files", { query: { patient_id: patient?.id, visit_id: visit?.id || undefined,
        category: categoryFilter || undefined, per_page: 100 } });
      renderToolbar();
      const files = res.items || [];
      mount(listEl, files.length ? files.map(fileCard) : emptyState({ icon: "file", title: t("files.empty") }));
      if (!compact) api.get("/files/storage").then((s) => {
        usage.textContent = t("files.storage", { used: formatBytes(s.used_bytes), quota: formatBytes(s.quota_bytes) });
      }).catch(() => {});
    } catch (e) {
      mount(listEl, errorState(e, load));
    }
  }

  function renderToolbar() {
    const sel = h("select", { class: "select select-sm", "aria-label": t("files.category"),
      onChange: (e) => { categoryFilter = e.target.value; load(); } },
    h("option", { value: "" }, t("files.all")), meta.categories.filter((c) => c !== "branding").map((c) => h("option", { value: c }, catLabel(c))));
    sel.value = categoryFilter;
    const canUpload = can("files.upload") && (meta.clinics || []).length;
    mount(toolbar, h("div", { class: "row gap-sm" }, sel, usage),
      canUpload ? h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: toggleUploader }, icon("upload"), t("files.upload")) : null);
  }

  function uploadClinics() {
    if (visit?.clinic_id) return meta.clinics.filter((c) => c.id === visit.clinic_id);
    const deptIds = new Set((ctx?.dept?.clinics || []).map((c) => c.id));
    return deptIds.size ? meta.clinics.filter((c) => deptIds.has(c.id)) : meta.clinics;
  }

  function toggleUploader() {
    uploaderOpen = !uploaderOpen;
    if (!uploaderOpen) return mount(uploaderWrap);
    const clinics = uploadClinics();
    const catSel = h("select", { class: "select" }, meta.upload_categories.map((c) => h("option", { value: c }, catLabel(c))));
    catSel.value = meta.upload_categories.includes(categoryFilter) ? categoryFilter : "document";
    const clinicSel = h("select", { class: "select" }, clinics.map((c) => h("option", { value: c.id }, c.department_name ? `${c.department_name} — ${c.name}` : c.name)));
    const desc = h("input", { class: "input", type: "text", maxlength: 2000 });
    const uploader = createUploader({
      url: "/files",
      fieldName: "files",
      fields: () => ({ patient_id: patient.id, visit_id: visit?.id, clinic_id: clinicSel.value, category: catSel.value,
        description: desc.value.trim() || undefined }),
      onUploaded: () => { toastSuccess(t("core.saved")); load(); },
      onError: (err) => err && toastApiError(err),
    });
    mount(uploaderWrap, h("div", { class: "card card-body stack gap-sm" },
      h("div", { class: "row-between" }, h("strong", t("files.upload")),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", "aria-label": t("core.close", { default: "Close" }), onClick: toggleUploader }, icon("x"))),
      h("div", { class: "form-grid" },
        h("div", { class: "field" }, h("label", t("files.category")), catSel),
        clinics.length > 1 ? h("div", { class: "field" }, h("label", t("files.clinic")), clinicSel) : null,
        h("div", { class: "field span-2" }, h("label", t("files.description")), desc)),
      uploader.el));
  }

  function fileCard(f) {
    const url = `/api/v1/files/${f.id}/content`;
    const isImage = VIEWABLE_IMAGES.includes(f.mime_type);
    const actions = [
      h("a", { class: "btn btn-sm btn-ghost", href: `${url}?download=1`, title: t("files.download"), "aria-label": t("files.download") }, icon("download")),
      f.can_manage && can("files.edit") ? h("button", { class: "btn btn-sm btn-ghost", type: "button", title: t("files.rename"),
        "aria-label": t("files.rename"), onClick: () => renameFile(f) }, icon("edit")) : null,
      f.can_manage && can("files.share") ? h("button", { class: "btn btn-sm btn-ghost", type: "button", title: t("files.share"),
        "aria-label": t("files.share"), onClick: () => shareFile(f) }, icon("users")) : null,
      f.can_manage && can("files.delete") ? h("button", { class: "btn btn-sm btn-ghost text-danger", type: "button", title: t("core.delete"),
        "aria-label": t("core.delete"), onClick: () => deleteFile(f) }, icon("trash")) : null,
    ];
    return h("div", { class: "card file-card" },
      h("button", { class: "file-card-preview", type: "button", title: t("files.open"), onClick: () => openFile(f) },
        isImage ? h("img", { src: url, alt: f.display_name, class: "file-thumb-img", loading: "lazy" })
          : icon("file", "file-thumb-icon")),
      h("div", { class: "file-card-info" },
        h("div", { class: "file-card-name text-truncate", title: f.display_name, dir: "auto" }, f.display_name),
        h("div", { class: "file-card-meta text-xs text-muted" },
          `${catLabel(f.category)} · ${formatBytes(f.size_bytes)} · ${formatDateTime(f.created_at)}`),
        f.description ? h("div", { class: "text-xs", dir: "auto" }, f.description) : null),
      h("div", { class: "file-card-actions row gap-xs" }, actions));
  }

  function openFile(f) {
    const url = `/api/v1/files/${f.id}/content`;
    if (!VIEWABLE_IMAGES.includes(f.mime_type)) return window.open(url, "_blank", "noopener");
    openImageViewer({
      src: url, title: f.display_name, annotations: f.annotations || [],
      editable: !!(f.can_manage && can("files.edit")),
      onSave: async (annotations) => {
        try {
          const res = await api.patch(`/files/${f.id}`, { annotations, version: f.version });
          Object.assign(f, res);
          toastSuccess(t("core.saved"));
        } catch (e) {
          toastApiError(e);
          throw e;
        }
      },
    });
  }

  function renameFile(f) {
    const modal = openModal({ title: t("files.rename.title"), size: "sm", body: h("div") });
    const form = createForm({
      columns: 1,
      fields: [{ name: "display_name", label: t("files.name"), required: true, maxLength: 200 }],
      values: { display_name: f.display_name },
      onCancel: () => modal.close(),
      onSubmit: async (v) => {
        try {
          await api.patch(`/files/${f.id}`, { display_name: v.display_name, version: f.version });
          modal.close();
          load();
        } catch (e) { handleFormError(form, e); }
      },
    });
    mount(modal.body, form.el);
  }

  async function shareFile(f) {
    const body = h("div", loadingState());
    const modal = openModal({ title: t("files.share.title"), size: "md", body });
    let targets;
    try {
      targets = await api.get("/files/share-targets");
    } catch (e) {
      return mount(body, errorState(e));
    }
    const current = h("div", { class: "stack gap-xs" });
    async function refresh() {
      const shares = await api.get(`/files/${f.id}/shares`).catch((e) => { toastApiError(e); return []; });
      const list = Array.isArray(shares) ? shares : shares.items || [];
      mount(current, list.length ? list.map((s) => h("div", { class: "row-between card card-body" },
        h("span", h("span", { class: "pill" }, t(`files.share.type.${s.target_type}`)), " ", s.target_name || `#${s.target_id}`),
        h("button", { class: "btn btn-sm btn-danger", type: "button", onClick: async () => {
          try { await api.del(`/files/${f.id}/shares/${s.id}`); refresh(); } catch (e) { toastApiError(e); }
        } }, t("files.share.revoke")))) : h("p", { class: "muted" }, t("files.share.none")));
    }
    const typeSel = h("select", { class: "select" }, ["department", "clinic", "user"].map((k) => h("option", { value: k }, t(`files.share.type.${k}`))));
    const targetSel = h("select", { class: "select" });
    const fillTargets = () => {
      const src = { department: targets.departments, clinic: targets.clinics, user: targets.users }[typeSel.value] || [];
      mount(targetSel, src.map((x) => h("option", { value: x.id }, x.name)));
    };
    typeSel.addEventListener("change", fillTargets);
    fillTargets();
    const addBtn = h("button", { class: "btn btn-primary", type: "button", onClick: async () => {
      try {
        await api.post(`/files/${f.id}/shares`, { target_type: typeSel.value, target_id: Number(targetSel.value) });
        toastSuccess(t("files.share.added"));
        refresh();
      } catch (e) { toastApiError(e); }
    } }, icon("plus"), t("files.share"));
    mount(body, h("div", { class: "stack gap-md" },
      h("h4", t("files.share.current")), current,
      h("h4", t("files.share.add")),
      h("div", { class: "row gap-sm wrap" }, typeSel, targetSel, addBtn)));
    refresh();
  }

  async function deleteFile(f) {
    if (!(await confirmDialog({ danger: true, message: t("core.confirm.message") }))) return;
    await deleteWithUndo(`/files/${f.id}`, { message: t("files.deleted"), onDone: load, onUndone: load }).catch(() => {});
  }

  mount(container, toolbar, uploaderWrap, listEl);
  load();
  return container;
}
