// Patient search box: GET /api/v1/patients?q=... (scope-filtered by the server).
// Degrades gracefully while the patients endpoint is not deployed (404 / network error).
import { h, mount, debounce } from "../core/dom.js";
import { t, formatDate } from "../core/i18n.js";
import { api } from "../core/api.js";
import { icon } from "./icons.js";

/**
 * patientSearch({onSelect(patient), placeholder, query: {clinic_id, ...extra filters}, minChars: 2, autofocus})
 *   -> {el, input, clear(), focus()}
 * Patient fields used for display (if present): name | full_name | first_name/last_name, code, phone, date_of_birth.
 */
export function patientSearch({ onSelect, placeholder, query = {}, minChars = 2, autofocus = false } = {}) {
  const results = h("div", { class: "search-results", role: "listbox", hidden: true });
  const input = h("input", { class: "input", type: "search", autocomplete: "off", placeholder: placeholder || t("core.patient_search.placeholder"),
    role: "combobox", "aria-expanded": "false", "aria-autocomplete": "list", autofocus });
  const el = h("div", { class: "search-box" }, icon("search"), input, results);
  let items = [];
  let active = -1;
  let seq = 0;

  const close = () => {
    results.hidden = true;
    input.setAttribute("aria-expanded", "false");
  };
  const show = (...nodes) => {
    mount(results, ...nodes);
    results.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };

  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < minChars) return close();
    const my = ++seq;
    show(h("div", { class: "search-hint" }, t("core.loading")));
    try {
      const res = await api.get("/patients", { query: { ...query, q, per_page: 8 } });
      if (my !== seq) return;
      items = res?.items || (Array.isArray(res) ? res : []);
      active = -1;
      if (!items.length) return show(h("div", { class: "search-hint" }, t("core.patient_search.none")));
      show(items.map((p, i) => h("button", { class: "search-result", type: "button", role: "option", dataset: { i },
        onMouseDown: (e) => { e.preventDefault(); pick(i); } },
      h("span", { class: "search-result-name" }, patientName(p)),
      h("span", { class: "search-result-meta" }, [p.code && h("span", { class: "ltr" }, p.code), p.phone && h("span", { class: "ltr" }, p.phone),
        p.date_of_birth && formatDate(p.date_of_birth, { year: "always" })].filter(Boolean).flatMap((x, j) => (j ? [" · ", x] : [x]))))));
    } catch (e) {
      if (my !== seq) return;
      const msg = e.status === 404 || e.status === 405 ? t("core.patient_search.unavailable")
        : e.isNetwork ? t("core.error.network_error") : e.message;
      show(h("div", { class: "search-hint" }, msg));
    }
  }, 250);

  function pick(i) {
    const p = items[i];
    if (!p) return;
    close();
    input.value = patientName(p);
    if (onSelect) onSelect(p);
  }

  function highlight(i) {
    const btns = [...results.querySelectorAll(".search-result")];
    if (!btns.length) return;
    active = (i + btns.length) % btns.length;
    btns.forEach((b, j) => b.classList.toggle("is-active", j === active));
    btns[active].scrollIntoView({ block: "nearest" });
  }

  input.addEventListener("input", run);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); highlight(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); highlight(active - 1); }
    else if (e.key === "Enter" && !results.hidden && active >= 0) { e.preventDefault(); pick(active); }
    else if (e.key === "Escape") close();
  });
  input.addEventListener("blur", () => setTimeout(close, 150));

  return { el, input, focus: () => input.focus(), clear: () => { input.value = ""; close(); } };
}

export function patientName(p) {
  if (!p) return "";
  return p.full_name || p.name || [p.first_name, p.father_name, p.last_name].filter(Boolean).join(" ") || `#${p.id}`;
}
