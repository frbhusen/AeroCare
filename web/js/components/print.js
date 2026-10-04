// Printing (spec §63/64): official documents are backend PDFs; HTML views use window.print().
import { apiUrl } from "../core/api.js";
import { h } from "../core/dom.js";
import { t } from "../core/i18n.js";
import { icon } from "./icons.js";

/** Open a backend-generated PDF (e.g. "/documents/invoice/12.pdf") in a new tab for printing/saving. */
export function printPdf(url, query) {
  const w = window.open(apiUrl(url, query), "_blank", "noopener");
  if (!w) window.location.assign(apiUrl(url, query)); // popup blocked: same tab
}

/** Print the current page (chrome is hidden by print.css). */
export function printView() {
  window.print();
}

/** Print only `node` (cloned into #print-root). */
export function printElement(node) {
  const root = document.getElementById("print-root") || document.body.appendChild(h("div", { id: "print-root" }));
  root.replaceChildren(node.cloneNode(true));
  document.body.classList.add("printing-element");
  const done = () => {
    document.body.classList.remove("printing-element");
    root.replaceChildren();
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

/** Standard "Print" button. printButton(() => printPdf(...)) */
export function printButton(onClick, label) {
  return h("button", { class: "btn", type: "button", onClick }, icon("printer"), label || t("core.print"));
}
