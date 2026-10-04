// Patients list + fast search (name / phone). The API returns {items, has_more} (no COUNT on big tables).
import { api, h, t, mount, debounce, icon, can, formatDate, ageFrom, navigate, clinicsOf, canClinic,
  loadingState, emptyState, errorState, offlineCopyBanner } from "../core/index.js";
import { patientHref, genderLabel } from "./header.js";
import { openRegisterPatient } from "./register.js";

export function renderPatientList(ctx) {
  ctx.setTitle(t("patients.title"));
  const inDept = ctx.area === "department";
  const state = { q: ctx.query.q || "", clinic_id: ctx.query.clinic_id || "", page: 1, per_page: 25 };
  const body = h("div");
  const pager = h("div", { class: "pagination" });
  let seq = 0;

  const search = h("input", { class: "input", type: "search", value: state.q, autofocus: true, autocomplete: "off",
    placeholder: t("patients.search.placeholder"), "aria-label": t("patients.search.placeholder"),
    onInput: debounce((e) => { state.q = e.target.value.trim(); state.page = 1; load(); }, 250) });
  const clinics = inDept ? clinicsOf(ctx.dept.id).filter((c) => canClinic(c.id)) : [];
  const clinicSel = clinics.length > 1 ? h("select", { class: "select", "aria-label": t("patients.field.clinic"),
    onChange: (e) => { state.clinic_id = e.target.value; state.page = 1; load(); } },
  h("option", { value: "" }, t("patients.all_clinics")), clinics.map((c) => h("option", { value: c.id }, c.name))) : null;

  async function load() {
    const my = ++seq;
    mount(body, loadingState());
    const query = { page: state.page, per_page: state.per_page, q: state.q.length ? state.q : null,
      clinic_id: state.clinic_id || null, department_id: inDept && !state.clinic_id ? ctx.dept.id : null };
    try {
      const res = await api.get("/patients", { query, cache: !state.q });
      if (my !== seq) return;
      render(res);
    } catch (e) {
      if (my !== seq) return;
      if (e.status === 422) mount(body, emptyState({ icon: "search", title: t("patients.search.too_short") }));
      else mount(body, errorState(e, load));
      mount(pager);
    }
  }

  function render(res) {
    const items = res.items || [];
    if (!items.length) {
      mount(body, offlineCopyBanner(res), emptyState({ icon: "users",
        title: state.q ? t("patients.search.none") : t("patients.empty"),
        action: can("patients.create") ? h("button", { class: "btn btn-primary", type: "button", onClick: openNew },
          icon("plus"), t("patients.register")) : null }));
    } else {
      const cols = [t("patients.field.code"), t("patients.field.full_name"), t("patients.field.phone"),
        t("patients.field.date_of_birth"), t("patients.field.gender")];
      mount(body, offlineCopyBanner(res), h("div", { class: "table-wrap" }, h("table", { class: "table table-stack" },
        h("thead", h("tr", cols.map((c) => h("th", c)))),
        h("tbody", items.map((p) => {
          const tr = h("tr", { class: "is-clickable", tabindex: 0 },
            h("td", { "data-label": cols[0] }, h("span", { class: "ltr nowrap" }, p.display_code)),
            h("td", { "data-label": cols[1] }, h("a", { href: patientHref(ctx, p.id) }, h("strong", p.full_name))),
            h("td", { "data-label": cols[2] }, p.phone ? h("span", { class: "ltr nowrap" }, p.phone) : ""),
            h("td", { "data-label": cols[3] }, p.date_of_birth ? `${formatDate(p.date_of_birth, { year: "always" })} (${ageFrom(p.date_of_birth) ?? "-"})` : ""),
            h("td", { "data-label": cols[4] }, genderLabel(p.gender)));
          const go = () => navigate(patientHref(ctx, p.id));
          tr.addEventListener("click", (e) => { if (!e.target.closest("a, button")) go(); });
          tr.addEventListener("keydown", (e) => e.key === "Enter" && e.target === tr && go());
          return tr;
        })))));
    }
    mount(pager,
      h("span", { class: "text-muted" }, t("patients.page", { page: state.page })),
      h("div", { class: "btn-group" },
        h("button", { class: "btn btn-sm", type: "button", disabled: state.page <= 1, "aria-label": t("core.table.prev"),
          onClick: () => { state.page -= 1; load(); } }, icon("chevronLeft", "flip-rtl")),
        h("button", { class: "btn btn-sm", type: "button", disabled: !res.has_more, "aria-label": t("core.table.next"),
          onClick: () => { state.page += 1; load(); } }, icon("chevronRight", "flip-rtl"))));
  }

  function openNew() {
    openRegisterPatient(ctx, { initialQuery: state.q, onCreated: (p) => navigate(patientHref(ctx, p.id)) });
  }

  load();
  return h("div", { class: "page" },
    h("div", { class: "page-header" },
      h("div", h("h1", t("patients.title")), h("p", { class: "subtitle" }, inDept ? ctx.dept.name : t("patients.subtitle_center"))),
      can("patients.create") ? h("div", { class: "page-actions" },
        h("button", { class: "btn btn-primary", type: "button", onClick: openNew }, icon("plus"), t("patients.register"))) : null),
    h("div", { class: "card data-table" },
      h("div", { class: "table-toolbar" },
        h("div", { class: "search-box pat-search" }, icon("search"), search), clinicSel),
      body, pager));
}
