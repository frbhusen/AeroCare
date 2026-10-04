// X-ray gallery: upload (core uploader), viewer (core image viewer), metadata edit, delete + undo.
import {
  api, h, t, icon, can, mount, createUploader, createForm, openModal, confirmDialog, deleteWithUndo, openFileViewer,
  openImageViewer, formatDate, formatBytes, loadingState, errorState, emptyState, offlineCopyBanner, todayISO,
} from "../core/index.js";
import { dentUrl, fileSrc, filterSelect, mutationError, savedNotice, xrayTypeLabel } from "./common.js";

const ACCEPT = "image/jpeg,image/png,image/gif,image/webp,image/bmp,image/tiff,.jpg,.jpeg,.png,.gif,.webp,.bmp,.tif,.tiff,.dcm";

export function renderXrays(panel, { patientId, clinicId, meta }) {
  let type = null;
  const canUpload = can("medical_records.create") && can("files.upload");
  const canEdit = can("medical_records.edit");
  const canDelete = can("medical_records.delete");
  const typeOptions = meta.xray_types.map((x) => ({ value: x, label: xrayTypeLabel(x) }));
  const grid = h("div", { class: "dent-xray-grid" });

  // upload metadata applied to the next files
  const upType = h("select", { class: "select", "aria-label": t("dentistry.field.xray_type") },
    typeOptions.map((o) => h("option", { value: o.value }, o.label)));
  upType.value = "periapical";
  const upTooth = h("input", { class: "input", maxlength: 100, placeholder: t("dentistry.field.tooth_tag") });
  const upDate = h("input", { class: "input", type: "date", value: todayISO() });
  const uploader = canUpload ? createUploader({
    url: dentUrl(`/patients/${patientId}/xrays`),
    accept: ACCEPT,
    fields: () => ({ clinic_id: clinicId, type: upType.value, tooth_tag: upTooth.value.trim() || null, date: upDate.value || null }),
    label: t("dentistry.xray.drop"),
    onUploaded: () => load(),
  }) : null;

  mount(panel,
    uploader ? h("details", { class: "card dent-xray-upload no-print" },
      h("summary", { class: "card-header" }, icon("upload"), h("strong", t("dentistry.xray.upload"))),
      h("div", { class: "card-body stack" },
        h("div", { class: "grid-3" },
          h("div", { class: "field" }, h("label", t("dentistry.field.xray_type")), upType),
          h("div", { class: "field" }, h("label", t("dentistry.field.tooth_tag")), upTooth),
          h("div", { class: "field" }, h("label", t("dentistry.field.date")), upDate)),
        uploader.el)) : null,
    h("div", { class: "row row-between dent-xray-toolbar no-print" },
      filterSelect(t("dentistry.all_types"), typeOptions, type, (v) => { type = v; load(); })),
    grid);

  async function load() {
    mount(grid, loadingState());
    try {
      const res = await api.get(dentUrl(`/patients/${patientId}/xrays`), { query: { clinic_id: clinicId, type }, cache: true });
      if (!res.items.length) return mount(grid, emptyState({ icon: "image", title: t("dentistry.xray.empty") }));
      mount(grid, offlineCopyBanner(res), res.items.map(card));
    } catch (e) {
      mount(grid, errorState(e, load));
    }
  }

  function card(x) {
    const isImg = x.file.is_image && x.file.mime_type !== "image/tiff";
    return h("article", { class: "card dent-xray-card" },
      h("button", { type: "button", class: "dent-xray-thumb", "aria-label": `${t("dentistry.xray.open")}: ${x.filename}`, onClick: () => view(x) },
        isImg ? h("img", { src: fileSrc(x.file.id), alt: x.filename, loading: "lazy" }) : h("span", { class: "dent-xray-icon" }, icon("image"),
          h("span", { class: "text-xs" }, x.file.mime_type))),
      h("div", { class: "dent-xray-meta" },
        h("div", { class: "row row-between" }, h("strong", { class: "dent-xray-name" }, x.filename),
          h("span", { class: "badge" }, xrayTypeLabel(x.type))),
        h("div", { class: "text-sm text-muted" }, formatDate(x.date, { year: "always" }), x.time ? ` ${x.time}` : "",
          x.tooth_tag ? h("span", " · ", t("dentistry.tooth"), " ", h("span", { class: "ltr" }, x.tooth_tag)) : null),
        x.notes ? h("div", { class: "text-sm" }, x.notes) : null,
        h("div", { class: "text-xs text-muted" }, x.uploaded_by, " · ", formatBytes(x.file.size_bytes)),
        h("div", { class: "btn-group no-print" },
          h("button", { type: "button", class: "btn btn-sm", onClick: () => view(x) }, icon("eye"), t("dentistry.xray.open")),
          canEdit ? h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-label": t("core.edit"), title: t("core.edit"),
            onClick: () => edit(x) }, icon("edit")) : null,
          canDelete ? h("button", { type: "button", class: "btn btn-sm btn-ghost", "aria-label": t("core.delete"), title: t("core.delete"),
            onClick: () => remove(x) }, icon("trash")) : null)));
  }

  async function view(x) {
    try {
      // full file record (annotations + version) so the viewer can save annotations when allowed
      const rec = await api.get(`/files/${x.file.id}`);
      openFileViewer(rec, { editable: can("files.edit") && !!rec.can_manage });
    } catch {
      if (x.file.is_image) openImageViewer({ src: fileSrc(x.file.id), title: x.filename });
      else window.open(fileSrc(x.file.id), "_blank", "noopener");
    }
  }

  function edit(x) {
    const form = createForm({
      fields: [
        { name: "filename", label: t("dentistry.field.filename"), required: true, maxLength: 255, span: 2 },
        { name: "type", label: t("dentistry.field.xray_type"), type: "select", options: typeOptions, empty: false },
        { name: "tooth_tag", label: t("dentistry.field.tooth_tag"), maxLength: 100 },
        { name: "date", label: t("dentistry.field.date"), type: "date", required: true },
        { name: "time", label: t("dentistry.field.time"), type: "time" },
        { name: "notes", label: t("dentistry.field.notes"), type: "textarea", span: 2, maxLength: 5000 },
      ],
      values: x,
      onSubmit: async (v) => {
        try {
          const res = await api.patch(dentUrl(`/xrays/${x.id}`), { ...v, version: x.version }, { offline: true, label: t("dentistry.xray.title") });
          modal.close();
          savedNotice(res);
          load();
        } catch (e) {
          if (e.code === "version_conflict") {
            modal.close();
            mutationError(e, load);
            return;
          }
          throw e;
        }
      },
      onCancel: () => modal.close(),
    });
    const verify = h("button", { type: "button", class: "btn btn-sm btn-ghost", onClick: async () => {
      try {
        const r = await api.get(dentUrl(`/xrays/${x.id}/verify`));
        mount(verify, icon(r.verified ? "check" : "alert"), t(r.verified ? "dentistry.xray.verified" : "dentistry.xray.verify_failed"));
      } catch (e) { mutationError(e); }
    } }, icon("shield"), t("dentistry.xray.verify"));
    const modal = openModal({ title: t("dentistry.xray.edit"), body: [form.el, h("div", { class: "row" }, verify)], size: "lg" });
  }

  async function remove(x) {
    if (!(await confirmDialog({ danger: true, message: t("dentistry.xray.confirm_delete") }))) return;
    await deleteWithUndo(dentUrl(`/xrays/${x.id}`), { message: t("dentistry.deleted"), onDone: load, onUndone: load }).catch(() => {});
  }

  load();
  return { reload: load };
}
