# Frontend contract (module UIs)

Vanilla ES modules, no build step. CSP: `script-src 'self'` — **no inline scripts, no `on*=` attributes, no `innerHTML` with data**. Style attributes are OK.

## 1. Your entry file
`web/js/<module>/index.js` must export `register(registry)`. It is listed in `web/js/modules.js` (frontend-core owns that list; ask the lead to add new names). If it throws or is missing, the app keeps running without it.

Import shared code via the barrel `../core/index.js` (or the individual files it re-exports).

## 2. Areas, URLs, environments
| area | URL | who |
|---|---|---|
| `admin` | `#/admin/<path>` | superadmin portal |
| `center` | `#/center/<path>` | center-wide principals (manager, center receptionist, superadmin support view) |
| `department` | `#/d/<deptId>/<path>` | isolated department environment (everyone, only visible departments) |

`env` (department area only): `"*"` (default) or array of `dentistry | dermatology | ophthalmology | radiology | laboratory | pharmacy | generic`. A user never sees routes/menus of departments outside their scope; an env-specific route beats a `"*"` route with the same path.

Reserved slots (register the same `area` + `path`/`key` to replace the "Coming soon" placeholder):
- admin: `centers, modules, plans, users, storage, audit, settings` (`support` and dashboard `""` are core)
- center: `patients, appointments, financial, inventory, staff, reports, settings` (overview `""` is core)
- department: `patients, appointments` (dashboard `""` is core; it shows your menu items as tiles + your widgets)

Menu `order` convention: dashboard 0, patients 10, appointments 20, specialty records 30–49, prescriptions 50, files 60, billing 70, inventory 80, lab/radiology requests 85, reports 90, staff 95, settings 99.

## 3. Registry API
```js
registry.i18n({ en: { "mymod.title": "..." }, ar: { "mymod.title": "..." } });   // keys MUST start with "<module>."
registry.route({ area, path: "items/:id", render(ctx), perm?, env?, title? /* i18n key */ });
registry.menu({ area, key, path, label /* i18n key */, icon, perm?, env?, order?, section? /* i18n key, admin/center */ });
registry.widget({ area: "center"|"department", key, title?, render(el, ctx), perm?, env?, order?, span?: 1|2 });
```
`perm`: string or array (any-of) — **UI hint only**; the API still decides (handle 403/404).
`render(ctx)` may be async and returns a Node (or `{node, cleanup}`), or fills `ctx.el` and returns nothing. Set `ctx.onLeave = fn` to stop timers/listeners.
`ctx = { el, area, path, params, query, dept /* {id,name,environment,color,icon,name_en,name_ar,managed} | null */, env, navigate, setTitle }`.
Throwing an ApiError with status 404/403 from render shows the standard not-found / no-permission page.

## 4. Core helpers (all from `core/index.js`)
- **api**: `api.get(url, {query, cache})`, `api.post/put/patch(url, body, {offline, label})`, `api.del(url)`. URLs are relative to `/api/v1`. Errors are `ApiError {status, code, message (localized), details}`; status 0 = network. 401 is handled globally (login screen).
  - `{offline: true}` on a mutation: if the network is down it is queued in IndexedDB and resolves `{queued: true, op_id}` (show "saved locally"; it syncs automatically with `X-Op-Id`). Only for idempotent-safe user actions (creates/updates with `version`). Listen to `onEvent("sync:applied", ({op, data}) => ...)` to refresh.
  - `{cache: true}` on a GET: last payload kept for offline reading; render `offlineCopyBanner(res)` (dataTable does it automatically).
  - `upload(url, formData, {onProgress})` for multipart.
- **dom**: `h(tag, attrs, ...children)` (text is always escaped; events via `onClick`), `mount(el, ...nodes)`, `html\`...\`` (escaped interpolation), `debounce`, `withBusy(btn, fn)`.
- **i18n**: `t(key, params)`, `localName(obj)`, `formatDate(v, {year: "auto"|"always", month: "numeric"|"short"})` (month/day order), `formatTime` (HH:MM), `formatDateTime`, `formatMoney(amountString)` (center currency), `formatNumber`, `toDateInput`, `toDateTimeInput` (send naive local values; server treats them as Asia/Damascus), `todayISO()`, `ageFrom(dob)`.
- **state/perm**: `getUser() getCenter() getDepartments() getDepartment(id) clinicsOf(deptId) getClinic(id) getActiveDepartment()`; `can(perm) canAny([...]) canClinic(id) managesDepartment(id) isCenterWide() isSupportMode()`.
- **router**: `navigate("/center/patients")`, `href(path, query)`, `deptHref(deptId, "patients/5")`, `areaHref(ctx, "patients")` (works in center and department areas).
- **components**: `dataTable`, `createForm`/`field`/`handleFormError`, `openModal`/`openDrawer`/`confirmDialog`/`popover`, `toast`/`toastApiError`/`undoToast`/`deleteWithUndo`, `tabs`, `patientSearch`, `createUploader` (15 MB/file), `openImageViewer`/`openFileViewer` (annotations saved via `PATCH /files/<id> {annotations, version}`), `printPdf(url)`/`printView()`/`printElement(node)`/`printButton(fn)`, `listenBarcode(onCode)` (returns stop; call it in `ctx.onLeave`), `statusPill(status, "mymod.status")`, `emptyState/errorState/loadingState/unavailableState`, `icon(name)`.

## 5. Complete minimal module
```js
// web/js/notes/index.js  (illustrative: "/notes" is a hypothetical endpoint)
import { api, h, t, dataTable, createForm, openModal, toast, deleteWithUndo, confirmDialog,
  formatDateTime, areaHref, icon, can } from "../core/index.js";

export function register(registry) {
  registry.i18n({
    en: { "notes.menu": "Notes", "notes.title": "Notes", "notes.new": "New note", "notes.text": "Text",
          "notes.saved_offline": "Saved on this device — will sync automatically", "notes.deleted": "Note deleted" },
    ar: { "notes.menu": "الملاحظات", "notes.title": "الملاحظات", "notes.new": "ملاحظة جديدة", "notes.text": "النص",
          "notes.saved_offline": "حُفظت على هذا الجهاز — ستُزامَن تلقائياً", "notes.deleted": "تم حذف الملاحظة" },
  });
  registry.menu({ area: "department", env: "*", key: "notes", path: "notes", label: "notes.menu", icon: "clipboard",
                  perm: "medical_records.view", order: 40 });
  registry.route({ area: "department", env: "*", path: "notes", title: "notes.title", perm: "medical_records.view", render });
}

function render(ctx) {
  const table = dataTable({
    columns: [
      { key: "text", label: t("notes.text") },
      { key: "created_at", label: "", render: (r) => formatDateTime(r.created_at) },
      { key: "actions", label: "", class: "actions", render: (r) => can("medical_records.delete")
          ? h("button", { class: "btn btn-sm btn-ghost", type: "button", "aria-label": t("core.delete"),
              onClick: async () => {
                if (!(await confirmDialog({ danger: true }))) return;
                await deleteWithUndo(`/notes/${r.id}`, { message: t("notes.deleted"), onDone: table.reload, onUndone: table.reload });
              } }, icon("trash")) : null },
    ],
    fetch: (q) => api.get("/notes", { query: { ...q, department_id: ctx.dept.id }, cache: true }),
    search: {},
    toolbar: [h("button", { class: "btn btn-primary", type: "button", onClick: openNew }, icon("plus"), t("notes.new"))],
  });

  function openNew() {
    const form = createForm({
      columns: 1,
      fields: [{ name: "text", label: t("notes.text"), type: "textarea", required: true }],
      onSubmit: async (v) => {
        const res = await api.post("/notes", { ...v, department_id: ctx.dept.id }, { offline: true, label: t("notes.new") });
        modal.close();
        if (res.queued) toast(t("notes.saved_offline"), { type: "warning" });
        else table.reload();
      },   // 422 details -> field errors automatically
    });
    const modal = openModal({ title: t("notes.new"), body: form.el });
  }

  return h("div", { class: "page" },
    h("div", { class: "page-header" }, h("h1", t("notes.title"))),
    table.el);
}
```

## 6. Conventions
- Files: `web/js/<module>/index.js` + small files per screen (`list.js`, `detail.js`, `form.js`, `i18n.js`); keep each < ~600 lines.
- i18n keys: `<module>.<screen>.<thing>`; always provide `en` and `ar`. Never concatenate translated fragments; use `{params}`.
- CSS: prefer the shared classes below. Module-specific styles live in your folder (`web/js/<module>/<module>.css`) and are loaded from `register()` with `loadStylesheet(new URL("./<module>.css", import.meta.url))`. Prefix module classes `<module>-` (e.g. `dent-chart`). Logical properties only (`margin-inline-start`, `inset-inline-end`, `text-align: start`); never `left/right` for layout. Wrap numbers/codes/phones in `.ltr`.
- Shared classes: layout `page page-header page-actions stack row row-between grid-2/3/4 grid-auto`; `card card-header card-body card-footer`; `btn btn-primary|danger|ghost|link btn-sm|lg btn-icon`; `input select textarea field`; `table table-stack` (cells need `data-label`, dataTable adds it); `pill pill--<status>`; `badge`; `alert alert-warning|danger|success`; `kv` (dl); `tabs`; `text-muted text-sm num ltr nowrap`; `no-print` / `print-only`.
- Department accent: use `var(--accent)` (set from the department color); center branding `var(--brand-primary)`.
- localStorage is reserved for the language preference. Do not store data there; IndexedDB is used only by core offline code.
- Every visible control must call a real endpoint or be shown as unavailable (`unavailableState()` / `comingSoon()`).
- Dates/times: display only via `formatDate/formatTime/formatDateTime`; send `YYYY-MM-DD` / `YYYY-MM-DDTHH:MM` (Damascus local).
- Money: the API sends strings; display with `formatMoney`, send strings (form `type: "money"` keeps strings).
- Optimistic locking: send the `version` you loaded; on `version_conflict` the form shows a reload message — reload the record.
- `node --check` every file you change.
