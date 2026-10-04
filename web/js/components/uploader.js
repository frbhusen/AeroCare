// File uploader: drag & drop, picker, multiple, 15 MB client check, progress, image previews.
// One multipart request per file (server re-validates type, size and quota).
import { h, mount } from "../core/dom.js";
import { t, formatBytes } from "../core/i18n.js";
import { upload } from "../core/api.js";
import { icon } from "./icons.js";

export const MAX_FILE_BYTES = 15 * 1024 * 1024;

/**
 * createUploader({url: "/files", fields: {patient_id, clinic_id, category} | (file) => ({...}),
 *   fieldName: "file", accept: "image/*,.pdf", multiple: true, maxBytes, onUploaded(json, file), onError(err, file)})
 *   -> {el, open(), reset()}
 */
export function createUploader({ url, fields = {}, fieldName = "file", accept, multiple = true, maxBytes = MAX_FILE_BYTES,
  onUploaded, onError, label } = {}) {
  const input = h("input", { type: "file", hidden: true, accept, multiple });
  const list = h("div", { class: "upload-list" });
  const zone = h("div", { class: "dropzone", role: "button", tabindex: 0, "aria-label": t("core.upload.drop") },
    icon("upload"), h("strong", label || t("core.upload.drop")),
    h("span", { class: "text-xs" }, t("core.upload.limit", { size: formatBytes(maxBytes) })));
  const el = h("div", { class: "uploader" }, zone, input, list);

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.click()));
  input.addEventListener("change", () => {
    handle([...input.files]);
    input.value = "";
  });
  ["dragenter", "dragover"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove("is-over"); }));
  zone.addEventListener("drop", (e) => handle([...(e.dataTransfer?.files || [])]));

  function handle(files) {
    if (!multiple) files = files.slice(0, 1);
    files.forEach(uploadOne);
  }

  async function uploadOne(file) {
    const isImg = file.type.startsWith("image/");
    const preview = isImg ? URL.createObjectURL(file) : null;
    const bar = h("span");
    const meta = h("div", { class: "upload-meta" }, formatBytes(file.size));
    const item = h("div", { class: "upload-item" },
      h("div", { class: "upload-thumb" }, preview ? h("img", { src: preview, alt: "" }) : icon("file")),
      h("div", { style: "min-width:0" }, h("div", { class: "upload-name" }, file.name), meta, h("div", { class: "progress" }, bar)),
      h("div"));
    list.prepend(item);
    const fail = (msg, err) => {
      item.classList.add("is-error");
      mount(meta, msg);
      if (onError) onError(err, file);
    };
    if (file.size > maxBytes) return fail(t("core.upload.too_large", { size: formatBytes(maxBytes) }));
    if (file.size === 0) return fail(t("core.upload.empty"));
    const fd = new FormData();
    const extra = typeof fields === "function" ? fields(file) : fields;
    for (const [k, v] of Object.entries(extra || {})) if (v != null) fd.append(k, v);
    fd.append(fieldName, file, file.name);
    try {
      const res = await upload(url, fd, { onProgress: (f) => { bar.style.width = `${Math.round(f * 100)}%`; } });
      bar.style.width = "100%";
      item.classList.add("is-done");
      mount(meta, t("core.upload.done"));
      if (onUploaded) onUploaded(res, file);
    } catch (err) {
      fail(err.message, err);
    } finally {
      if (preview) setTimeout(() => URL.revokeObjectURL(preview), 60000);
    }
  }

  return { el, open: () => input.click(), reset: () => mount(list) };
}
