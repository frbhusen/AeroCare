// Module entry files loaded at startup: web/js/<name>/index.js exporting register(registry).
// Missing modules are skipped (parallel development). Order = registration order (menus sort by `order`).
export const MODULES = [
  "patients",
  "appointments",
  "billing",
  "inventory",
  "files",
  "reports",
  "admin",
  "center-admin",
  "dentistry",
  "dermatology",
  "ophthalmology",
  "radiology",
  "laboratory",
  "pharmacy",
  "generic",
];
