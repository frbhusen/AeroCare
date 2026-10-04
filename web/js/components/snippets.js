// "Templates" button for clinical textareas: inserts saved snippets (and favorite diagnoses for diagnosis
// fields) from /api/v1/favorites, and saves the current text as a new template. Server-backed (no hard-coded
// clinical text); center-wide templates + those of the active department.
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { api } from "../core/api.js";
import { can } from "../core/perm.js";
import { getActiveDepartment } from "../core/state.js";
import { icon } from "./icons.js";
import { popover } from "./modal.js";

// Fields where templates make no sense (administrative text).
const SKIP = new Set(["address", "document_footer", "login_message", "description", "reason", "void_reason", "notes_admin"]);
const DIAGNOSIS_FIELDS = new Set(["diagnosis", "condition", "impression", "assessment"]);

function append(textarea, text) {
  const cur = textarea.value.trim();
  textarea.value = cur ? `${cur}\n${text}` : text;
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.focus();
}

/** Returns the trigger button for a textarea, or null when templates don't apply. */
export function snippetButton(textarea, fieldName, enabled) {
  if (enabled === false || !fieldName || SKIP.has(fieldName) || !can("medical_records.view")) return null;
  const label = t("core.snippets.btn", { default: "Templates" });
  const btn = h("button", { class: "snippet-trigger-btn", type: "button", title: label, "aria-label": label },
    icon("file"), h("span", t("core.snippets.title", { default: "Templates" })));

  btn.addEventListener("click", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    const dept = getActiveDepartment();
    const list = h("div", { class: "snippet-popover-list" }, h("div", { class: "text-sm muted" }, "…"));
    const saveBtn = can("medical_records.create") && dept ? h("button", { class: "btn btn-sm", type: "button", onClick: save },
      icon("plus"), t("core.snippets.save", { default: "Save current text as template" })) : null;
    const pop = popover(btn, h("div", { class: "snippet-popover-body" },
      h("div", { class: "snippet-popover-header" }, h("strong", t("core.snippets.header", { default: "Templates" }))),
      list, saveBtn), { className: "snippet-popover" });

    async function load() {
      try {
        const q = { field: fieldName, department_id: dept?.id };
        const [snips, diags] = await Promise.all([
          api.get("/favorites", { query: { ...q, kind: "snippet" } }),
          DIAGNOSIS_FIELDS.has(fieldName) ? api.get("/favorites", { query: { department_id: dept?.id, kind: "diagnosis" } }) : { items: [] },
        ]);
        const items = [...diags.items, ...snips.items];
        list.replaceChildren(...(items.length ? items.map((f) => h("button", { class: "snippet-item", type: "button",
          onClick: () => { append(textarea, f.body || f.title); pop?.close?.(); } },
        h("strong", f.title), f.body && f.body !== f.title ? h("div", { class: "text-sm muted" }, f.body) : null))
          : [h("div", { class: "text-sm muted" }, t("core.snippets.none", { default: "No templates yet." }))]));
      } catch {
        list.replaceChildren(h("div", { class: "text-sm muted" }, t("core.snippets.none", { default: "No templates yet." })));
      }
    }

    async function save() {
      const text = textarea.value.trim();
      if (!text) return;
      const title = window.prompt(t("core.snippets.name", { default: "Template name" }), text.slice(0, 60));
      if (!title) return;
      try {
        await api.post("/favorites", { kind: DIAGNOSIS_FIELDS.has(fieldName) ? "diagnosis" : "snippet",
          department_id: dept.id, field: DIAGNOSIS_FIELDS.has(fieldName) ? null : fieldName, title, body: text });
        load();
      } catch (err) {
        list.prepend(h("div", { class: "field-error" }, err.message || String(err)));
      }
    }
    load();
  });
  return btn;
}
