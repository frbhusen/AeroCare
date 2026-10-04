// Register patient with duplicate prevention: while typing name/phone, GET /patients/lookup shows existing
// center patients (minimal identity). Staff open an accessible one or link it to their clinic instead of
// creating a second profile.
import { api, h, t, mount, debounce, icon, can, toast, toastApiError, createForm, openModal, formatDate,
  withBusy } from "../core/index.js";
import { genderLabel } from "./header.js";
import { loadMeta, profileFields } from "./meta.js";

/** openRegisterPatient(ctx, {initialQuery, onCreated(patient), onLinked(patient)}) */
export async function openRegisterPatient(ctx, { initialQuery = "", onCreated, onLinked } = {}) {
  let meta;
  try {
    meta = await loadMeta();
  } catch (e) {
    return toastApiError(e);
  }
  const clinics = ctx.area === "department" ? meta.clinics.filter((c) => c.department_id === ctx.dept.id) : meta.clinics;
  if (!clinics.length) return toast(t("patients.register.no_clinic"), { type: "warning" });
  const isPhone = /^[+\d()\-\s]{3,}$/.test(initialQuery);
  const fields = [
    { name: "full_name", label: t("patients.field.full_name"), required: true, maxLength: 200, span: 2, autocomplete: "off" },
    { name: "phone", label: t("patients.field.phone"), type: "tel", maxLength: 40, attrs: { dir: "ltr" } },
    { name: "clinic_id", label: t("patients.field.clinic"), type: "select", required: true, numeric: true,
      options: clinics.map((c) => ({ value: c.id, label: ctx.area === "department" ? c.name : `${c.department_name} — ${c.name}` })) },
    ...profileFields(meta, { compact: true }),
  ];
  const dupBox = h("div", { class: "pat-dups", "aria-live": "polite" });
  const form = createForm({
    fields,
    values: { full_name: isPhone ? "" : initialQuery, phone: isPhone ? initialQuery : "", clinic_id: clinics.length === 1 ? clinics[0].id : "" },
    submitLabel: t("patients.register.submit"),
    onCancel: () => modal.close(),
    onSubmit: async (v) => {
      const res = await api.post("/patients", v, { offline: true, label: t("patients.register") });
      modal.close();
      if (res?.queued) return toast(t("patients.saved_offline"), { type: "warning" });
      toast(t("patients.register.created", { code: res.display_code }), { type: "success" });
      if (onCreated) onCreated(res);
    },
  });
  const modal = openModal({ title: t("patients.register"), size: "lg", body: [dupBox, form.el] });

  let seq = 0;
  const lookup = debounce(async () => {
    const v = form.values();
    const q = [v.full_name, v.phone].filter((x) => x && x.length >= 2).join(" ").trim();
    if (q.length < 3) return mount(dupBox);
    const my = ++seq;
    try {
      const res = await api.get("/patients/lookup", { query: { q, date_of_birth: v.date_of_birth } });
      if (my !== seq) return;
      showDups(res.items || []);
    } catch (e) {
      if (my === seq) mount(dupBox); // offline / no permission: registration still works
    }
  }, 350);
  for (const name of ["full_name", "phone", "date_of_birth"]) form.el.elements.namedItem(name)?.addEventListener("input", lookup);
  if (initialQuery) lookup();

  function showDups(items) {
    if (!items.length) return mount(dupBox);
    mount(dupBox, h("div", { class: "alert alert-warning pat-dup-alert" }, icon("alert"),
      h("div", { class: "stack-sm", style: "flex:1;min-width:0" },
        h("strong", t("patients.dup.title")), h("div", { class: "text-sm" }, t("patients.dup.hint")),
        h("ul", { class: "pat-dup-list" }, items.map((p) => h("li", { class: "pat-dup" },
          h("div", { style: "min-width:0" },
            h("strong", p.full_name), " ",
            h("span", { class: "text-sm text-muted" }, [h("span", { class: "ltr" }, p.display_code),
              p.date_of_birth ? ` · ${formatDate(p.date_of_birth, { year: "always" })}` : "",
              p.gender ? ` · ${genderLabel(p.gender)}` : "",
              p.phone_masked ? [" · ", h("span", { class: "ltr" }, p.phone_masked)] : ""])),
          p.accessible
            ? h("button", { class: "btn btn-sm", type: "button", onClick: () => { modal.close(); onCreated?.(p); } }, icon("eye"), t("patients.dup.open"))
            : can("patients.create") ? h("button", { class: "btn btn-sm btn-primary", type: "button", onClick: (e) => link(e.currentTarget, p) },
              icon("plus"), t("patients.dup.link")) : null))))));
  }

  async function link(btn, p) {
    const clinicId = form.values().clinic_id;
    if (!clinicId) return form.setErrors({ clinic_id: t("patients.dup.choose_clinic") });
    await withBusy(btn, async () => {
      try {
        const res = await api.post(`/patients/${p.id}/link`, { clinic_id: clinicId });
        modal.close();
        toast(t("patients.dup.linked", { name: res.full_name }), { type: "success" });
        (onLinked || onCreated)?.(res);
      } catch (e) {
        toastApiError(e);
      }
    });
  }
}
