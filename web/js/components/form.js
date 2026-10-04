// Form builder: consistent fields, value collection, API error.details -> field errors.
import { h, mount } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { toastApiError } from "./toast.js";
import { snippetButton } from "./snippets.js";

/**
 * Field spec: {name, label, type: "text"|"email"|"tel"|"password"|"number"|"date"|"time"|"datetime"|
 *   "textarea"|"select"|"checkbox"|"money"|"hidden"|"section", required, options: [{value, label}],
 *   placeholder, help, span: 2 (full width), min, max, step, maxLength, disabled, autocomplete,
 *   empty: true (select gets an empty first option), attrs: {...}}
 */
export function field(spec, value) {
  if (spec.type === "section") return h("div", { class: "form-section-title" }, spec.label);
  const id = `f-${spec.name}-${Math.random().toString(36).slice(2, 7)}`;
  const common = { id, name: spec.name, disabled: spec.disabled, required: spec.required, ...(spec.attrs || {}) };
  let control;
  const type = spec.type || "text";
  if (type === "custom") {
    control = typeof spec.render === "function" ? spec.render() : h("div");
  } else if (type === "textarea") {
    control = h("textarea", { class: "textarea", ...common, placeholder: spec.placeholder, maxlength: spec.maxLength, rows: spec.rows || 4 });
    control.value = value ?? "";
  } else if (type === "select") {
    const opts = (spec.options || []).map((o) => h("option", { value: String(o.value) }, o.label));
    if (spec.empty !== false && !spec.multiple) opts.unshift(h("option", { value: "" }, spec.placeholder || t("core.select_placeholder")));
    control = h("select", { class: "select", ...common, multiple: spec.multiple }, opts);
    if (spec.multiple && Array.isArray(value)) [...control.options].forEach((o) => { o.selected = value.map(String).includes(o.value); });
    else control.value = value == null ? "" : String(value);
  } else if (type === "checkbox") {
    control = h("input", { type: "checkbox", ...common, checked: !!value });
    const wrap = h("div", { class: ["field", spec.span === 2 && "span-2"], dataset: { field: spec.name } },
      h("label", { class: "check", for: id }, control, spec.label), spec.help ? h("div", { class: "field-help" }, spec.help) : null);
    return wrap;
  } else if (type === "hidden") {
    return h("input", { type: "hidden", name: spec.name, value: value ?? "" });
  } else {
    const htmlType = { datetime: "datetime-local", money: "number" }[type] || type;
    control = h("input", { class: "input", type: htmlType, ...common, placeholder: spec.placeholder, min: spec.min, max: spec.max,
      step: spec.step ?? (type === "money" ? "0.01" : null), maxlength: spec.maxLength, autocomplete: spec.autocomplete,
      inputmode: type === "money" ? "decimal" : null });
    control.value = value ?? "";
  }
  let labelEl = null;
  if (spec.label) {
    const snip = type === "textarea" ? snippetButton(control, spec.name, spec.snippets) : null;
    labelEl = snip
      ? h("div", { class: "field-label-row" },
        h("label", { for: id }, spec.label, spec.required ? h("span", { class: "req", "aria-hidden": "true" }, "*") : null),
        snip)
      : h("label", { for: id }, spec.label, spec.required ? h("span", { class: "req", "aria-hidden": "true" }, "*") : null);
  }
  return h("div", { class: ["field", spec.span === 2 && "span-2"], dataset: { field: spec.name } },
    labelEl,
    control,
    spec.help ? h("div", { class: "field-help" }, spec.help) : null);
}

/** Collect values from a form element according to specs (numbers -> Number, empty -> null). */
export function readValues(formEl, fields) {
  const out = {};
  for (const f of fields) {
    if (!f.name || f.type === "section" || f.type === "custom") continue;
    const ctl = formEl.elements.namedItem(f.name);
    if (!ctl) continue;
    if (f.type === "checkbox") out[f.name] = ctl.checked;
    else if (f.type === "select" && f.multiple) out[f.name] = [...ctl.selectedOptions].map((o) => o.value);
    else {
      const v = typeof ctl.value === "string" ? ctl.value.trim() : ctl.value;
      if (v === "") out[f.name] = null;
      else if (f.type === "number" || f.numeric) out[f.name] = Number(v);
      else out[f.name] = v; // money stays a string ("12.50") as the API expects
    }
  }
  return out;
}

/** Show API validation details {field: message} on the matching fields; returns unmatched messages. */
export function setFieldErrors(formEl, details) {
  clearFieldErrors(formEl);
  const unmatched = [];
  if (!details || typeof details !== "object") return unmatched;
  for (const [name, msg] of Object.entries(details)) {
    const text = Array.isArray(msg) ? msg.join(", ") : typeof msg === "object" ? JSON.stringify(msg) : String(msg);
    const wrap = formEl.querySelector(`[data-field="${CSS.escape(name)}"]`);
    if (!wrap) {
      unmatched.push(`${name}: ${text}`);
      continue;
    }
    wrap.classList.add("has-error");
    wrap.append(h("div", { class: "field-error", role: "alert" }, text));
    const ctl = wrap.querySelector("input, select, textarea");
    if (ctl) ctl.setAttribute("aria-invalid", "true");
  }
  const first = formEl.querySelector(".has-error input, .has-error select, .has-error textarea");
  if (first) first.focus();
  return unmatched;
}

export function clearFieldErrors(formEl) {
  formEl.querySelectorAll(".field-error").forEach((e) => e.remove());
  formEl.querySelectorAll(".has-error").forEach((e) => e.classList.remove("has-error"));
  formEl.querySelectorAll("[aria-invalid]").forEach((e) => e.removeAttribute("aria-invalid"));
  formEl.querySelector(".form-error-summary")?.remove();
}

/**
 * createForm({fields, values, onSubmit: async (values, form) => any, submitLabel, onCancel, cancelLabel,
 *             columns: 2 | 1, actions: true})
 *   -> {el, values(), setValues(v), setErrors(details), submit(), reset()}
 * onSubmit errors: ApiError validation_error -> field errors; version_conflict -> message; others -> toast.
 */
export function createForm({ fields, values = {}, onSubmit, submitLabel, onCancel, cancelLabel, columns = 2, actions = true } = {}) {
  const grid = h("div", { class: columns === 1 ? "form" : "form-grid" }, fields.map((f) => field(f, values[f.name])));
  const submitBtn = h("button", { class: "btn btn-primary", type: "submit" }, submitLabel || t("core.save"));
  const actionsEl = actions ? h("div", { class: "form-actions" },
    onCancel ? h("button", { class: "btn", type: "button", onClick: onCancel }, cancelLabel || t("core.cancel")) : null, submitBtn) : null;
  const el = h("form", { class: "form", novalidate: true }, grid, actionsEl);
  const api = {
    el,
    values: () => readValues(el, fields),
    setValues(v) {
      mount(grid, fields.map((f) => field(f, v[f.name])));
    },
    setErrors(details) {
      const rest = setFieldErrors(el, details);
      if (rest.length) el.prepend(h("div", { class: "form-error-summary", role: "alert" }, rest.join(" · ")));
    },
    showError(message) {
      el.querySelector(".form-error-summary")?.remove();
      el.prepend(h("div", { class: "form-error-summary", role: "alert" }, message));
    },
    clearErrors: () => clearFieldErrors(el),
    submit: () => el.requestSubmit(),
    reset: () => api.setValues(values),
    submitButton: submitBtn,
  };
  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearFieldErrors(el);
    const missing = {};
    for (const f of fields) {
      if (!f.required || !f.name) continue;
      const v = api.values()[f.name];
      if (v == null || v === "" || v === false || (Array.isArray(v) && !v.length)) missing[f.name] = t("core.form.required");
    }
    if (Object.keys(missing).length) return api.setErrors(missing);
    if (!onSubmit) return;
    submitBtn.classList.add("is-loading");
    submitBtn.disabled = true;
    try {
      await onSubmit(api.values(), api);
    } catch (err) {
      handleFormError(api, err);
    } finally {
      submitBtn.classList.remove("is-loading");
      submitBtn.disabled = false;
    }
  });
  return api;
}

/** Map an error from onSubmit onto the form. Exported for custom forms. */
export function handleFormError(form, err) {
  if (err?.status === 422 && err.details && typeof err.details === "object") {
    form.setErrors(err.details);
    if (err.code !== "validation_error") form.showError(err.message);
  } else if (err?.code === "version_conflict") {
    form.showError(t("core.error.version_conflict"));
  } else if (err?.status && err.status < 500 && err.status !== 401) {
    form.showError(err.message);
  } else {
    toastApiError(err);
  }
}
