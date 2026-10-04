import { api, h, t, mount, icon, areaHref, emptyState, loadStylesheet } from "../core/index.js";
import { dict } from "./i18n.js";
import { renderChartPage } from "./chart.js";
import { registerPatientTab, registerVisitOpener } from "../patients/hooks.js";
import { renderOdontogram } from "./odontogram.js";
import { loadMeta, deptClinics } from "./common.js";

export function register(registry) {
  loadStylesheet(new URL("./dentistry.css", import.meta.url));
  registry.i18n(dict);

  // Dental Chart route inside Dentistry departments
  registry.route({
    area: "department",
    env: ["dentistry"],
    path: "chart/:patientId",
    title: "dentistry.chart.title",
    perm: "medical_records.view",
    render: renderChartPage,
  });

  // Odontogram tab on patient profile inside dentistry department
  registerPatientTab({
    key: "dentistry",
    label: "dentistry.tab.chart",
    env: ["dentistry"],
    order: 25,
    perm: "medical_records.view",
    render: async (panelEl, { patient, ctx }) => {
      const meta = await loadMeta();
      const clinics = deptClinics(meta, ctx);
      const clinicId = clinics[0]?.id;
      renderOdontogram(panelEl, { patientId: patient.id, clinicId, meta });
    },
  });

  // Visit opener for dentistry visits
  registerVisitOpener("dentistry", (ctx, visit) => {
    const deptId = ctx.area === "department" ? ctx.dept.id : visit.department_id;
    return `#/d/${deptId}/chart/${visit.patient_id}?clinic=${visit.clinic_id}&tab=treatments`;
  });

  // Department widget
  registry.widget({
    area: "department",
    env: ["dentistry"],
    key: "dentistry-today",
    title: "dentistry.summary.treatments",
    perm: "medical_records.view",
    order: 25,
    render: async (el, ctx) => {
      try {
        mount(el, h("div", { class: "p-sm text-sm" },
          h("a", { class: "btn btn-link", href: `#/d/${ctx.dept.id}/patients` },
            icon("tooth"), " ", t("dentistry.charts.title")
          )
        ));
      } catch (e) {
        mount(el, emptyState({ icon: "tooth", title: t("dentistry.title") }));
      }
    },
  });
}
