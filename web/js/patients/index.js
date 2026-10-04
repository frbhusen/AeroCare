// Patients module registration
import { dict } from "./i18n.js";
import { renderPatientList } from "./list.js";
import { renderPatientProfile } from "./profile.js";
import { renderPatientSummary } from "./summary.js";

export function register(registry) {
  registry.i18n(dict);

  for (const area of ["center", "department"]) {
    const isDept = area === "department";
    const envOpts = isDept ? { env: "*" } : {};

    registry.route({
      area,
      ...envOpts,
      path: "patients",
      title: "patients.title",
      perm: "patients.view",
      render: renderPatientList,
    });

    registry.route({
      area,
      ...envOpts,
      path: "patients/:id",
      title: "patients.title",
      perm: "patients.view",
      render: renderPatientProfile,
    });

    registry.route({
      area,
      ...envOpts,
      path: "patients/:id/summary",
      title: "patients.summary.title",
      perm: "patients.view",
      render: renderPatientSummary,
    });

    registry.menu({
      area,
      ...envOpts,
      key: "patients",
      path: "patients",
      label: "patients.title",
      icon: "users",
      perm: "patients.view",
      order: 10,
    });
  }
}
