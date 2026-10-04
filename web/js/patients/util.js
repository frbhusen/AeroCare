// Small UI helpers shared by the patients / generic / files UIs.
import { h, t, icon, handleFormError } from "../core/index.js";

/**
 * Handle an onSubmit error: a 409 version_conflict shows the standard message plus a "Reload" button
 * (onReload), anything else is rethrown so createForm maps it (422 -> field errors).
 */
export function conflictOr(form, err, onReload) {
  if (err?.code !== "version_conflict") throw err;
  handleFormError(form, err);
  form.el.querySelector(".form-error-summary")?.append(" ", h("button", { class: "btn btn-sm", type: "button", onClick: onReload },
    icon("refresh"), t("patients.reload")));
}
