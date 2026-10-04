// Reusable Files panel for patient profile & visit drawer (upload, list, preview, annotate, share, delete).
import {
  api, h, mount, t, can, icon, formatDateTime, formatBytes, toast, toastSuccess, toastApiError,
  openModal, confirmDialog, deleteWithUndo, createForm, loadingState, errorState, emptyState,
} from "../core/index.js";
import { createUploader } from "../components/uploader.js";
import { openImageViewer } from "../components/image-viewer.js";

const PREVIEWABLE_IMAGES = ["image/jpeg", "image/png", "image/webp", "image/gif"];

export function filesPanel({ ctx, patient, visit, compact = false } = {}) {
  const container = h("div", { class: `files-panel ${compact ? "files-panel--compact" : ""}` });
  const toolbar = h("div", { class: "files-toolbar row-between" });
  const listEl = h("div", { class: "files-grid" });
  const uploaderWrap = h("div", { class: "files-uploader-wrap" });

  let meta = null;
  let files = [];
  let categoryFilter = "";

  async function load() {
    mount(listEl, loadingState());
    try {
      if (!meta) meta = await api.get("/files/meta").catch(() => null);
      const query = {
        patient_id: patient?.id,
        visit_id: visit?.id || undefined,
        category: categoryFilter || undefined,
      };
      const res = await api.get("/files", { query });
      files = res.items || [];
      render();
    } catch (e) {
      mount(listEl, errorState(e, load));
    }
  }

  function render() {
    renderToolbar();
    if (!files.length) {
      mount(listEl, emptyState({ icon: "file", title: t("core.empty.title") }));
      return;
    }

    mount(listEl, files.map((f) => renderFileCard(f)));
  }

  function renderToolbar() {
    const cats = meta?.categories || ["general", "xray", "prescription", "lab", "radiology", "report", "id", "consent", "other"];
    const catSelect = h("select", {
      class: "select select-sm",
      "aria-label": t("core.search"),
      onChange: (e) => {
        categoryFilter = e.target.value;
        load();
      },
    },
      h("option", { value: "" }, t("core.items", { count: files.length })),
      cats.map((c) => h("option", { value: c }, t(`files.cat.${c}`, c)))
    );
    catSelect.value = categoryFilter;

    const uploadBtn = can("files.upload") ? h("button", {
      class: "btn btn-sm btn-primary",
      type: "button",
      onClick: toggleUploader,
    }, icon("upload"), t("core.add")) : null;

    mount(toolbar, h("div", { class: "row gap-sm" }, catSelect), uploadBtn);
  }

  let uploaderOpen = false;
  function toggleUploader() {
    uploaderOpen = !uploaderOpen;
    if (!uploaderOpen) {
      mount(uploaderWrap);
      return;
    }

    const defaultClinic = visit?.clinic_id || (ctx?.dept ? ctx.dept.clinics?.[0]?.id : meta?.clinics?.[0]?.id);
    const uploader = createUploader({
      url: "/files",
      fields: (file) => ({
        patient_id: patient?.id,
        visit_id: visit?.id || null,
        clinic_id: defaultClinic || null,
        category: categoryFilter || "general",
      }),
      fieldName: "file",
      onUploaded: (res) => {
        toastSuccess(t("core.saved"));
        load();
      },
      onError: (err) => {
        toastApiError(err);
      },
    });

    mount(uploaderWrap, h("div", { class: "card card-body uploader-card" },
      h("div", { class: "row-between mb-sm" },
        h("strong", t("core.add")),
        h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: () => toggleUploader() }, icon("x"))
      ),
      uploader.el
    ));
  }

  function renderFileCard(f) {
    const isImage = PREVIEWABLE_IMAGES.includes(f.mime_type);
    const isPdf = f.mime_type === "application/pdf";
    const contentUrl = `/api/v1/files/${f.id}/content`;

    const thumb = isImage
      ? h("img", { src: contentUrl, alt: f.display_name, class: "file-thumb-img", loading: "lazy" })
      : icon(isPdf ? "fileText" : "file", "file-thumb-icon");

    const card = h("div", { class: "card file-card" },
      h("div", {
        class: "file-card-preview",
        onClick: () => openFile(f),
      }, thumb),
      h("div", { class: "file-card-info" },
        h("div", { class: "file-card-name text-truncate", title: f.display_name }, f.display_name),
        h("div", { class: "file-card-meta text-xs text-muted" },
          formatBytes(f.size_bytes), " · ",
          formatDateTime(f.created_at)
        )
      ),
      h("div", { class: "file-card-actions row gap-xs" },
        h("button", {
          class: "btn btn-sm btn-ghost",
          type: "button",
          title: t("core.search"),
          onClick: () => openFile(f),
        }, icon("eye")),
        h("a", {
          class: "btn btn-sm btn-ghost",
          href: `${contentUrl}?download=1`,
          download: f.display_name,
          title: t("core.print"),
        }, icon("download")),
        can("files.delete") ? h("button", {
          class: "btn btn-sm btn-ghost text-danger",
          type: "button",
          title: t("core.delete"),
          onClick: () => deleteFile(f),
        }, icon("trash")) : null
      )
    );
    return card;
  }

  function openFile(f) {
    const isImage = PREVIEWABLE_IMAGES.includes(f.mime_type);
    const contentUrl = `/api/v1/files/${f.id}/content`;
    if (isImage) {
      openImageViewer({
        src: contentUrl,
        title: f.display_name,
        annotations: f.annotations || [],
        editable: can("files.edit"),
        onSave: async (annotations) => {
          await api.patch(`/files/${f.id}`, { annotations, version: f.version });
          f.annotations = annotations;
          f.version += 1;
          toastSuccess(t("core.saved"));
        },
      });
    } else {
      window.open(contentUrl, "_blank", "noopener,noreferrer");
    }
  }

  async function deleteFile(f) {
    if (!(await confirmDialog({ danger: true, message: t("core.confirm.message") }))) return;
    try {
      await deleteWithUndo(`/files/${f.id}`, {
        message: t("core.deleted"),
        onDone: load,
        onUndone: load,
      });
    } catch (e) {
      toastApiError(e);
    }
  }

  mount(container, toolbar, uploaderWrap, listEl);
  load();
  return container;
}
