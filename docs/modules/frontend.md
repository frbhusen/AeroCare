# Frontend core (workstream 9)

## Purpose
Shell, design system and shared JS infrastructure that every module UI plugs into. Vanilla ES modules, no build step, strict CSP (no inline scripts/handlers). Arabic/English with RTL/LTR. **Module authors: read `web/js/core/README.md` (the contract).**

## Layout
| Path | Content |
|---|---|
| `web/index.html` | single page; loads CSS + `js/core/boot.js` |
| `web/css/` | `tokens` (palette, branding/accent vars), `base` (reset, typography, grid), `components` (buttons, forms, tables, cards, dept cards, pills, modals, drawers, toasts, tabs, states), `shell` (topbar, sidebar, login, panels), `media` (uploader, image viewer), `print` |
| `web/js/core/` | `api` (fetch client, ApiError, CSRF, 401, offline/cache options, upload), `router` (hash, guards), `state`, `perm`, `i18n` (+ `locales/en,ar`), `registry`, `dom`, `events`, `shell`, `topbar`, `department` (dept dashboard), `boot`, `index` (barrel), `README.md` |
| `web/js/components/` | data table, form builder, modal/drawer/confirm/popover, toast + undo, tabs, patient search, uploader, image viewer (zoom/rotate/pan/fullscreen/pen/arrow/text), print, barcode (USB scanner bursts), connectivity indicator, states, icons |
| `web/js/offline/` | IndexedDB (`hc-offline`: `queue`, `cache`), mutation queue + ordered replay with `X-Op-Id`, sync status, read cache, sync-issues review drawer |
| `web/js/auth/` | login screen (platform branding), session (me/login/logout/change password/support enter-exit) |
| `web/js/portal/` | superadmin shell: dashboard, 7 slots (Coming soon until admin UI registers them), Enter center (support view) |
| `web/js/center/` | center overview: large department cards + center-wide nav slots |
| `web/js/modules.js` | module entry list (dynamic import, missing ones skipped) |
| `web/sw.js`, `web/manifest.json`, `web/img/` | app-shell service worker (network-first, never `/api/`), PWA manifest, icons |

## Behaviour summary
- Portals from `/auth/me.portal`: `superadmin` → `#/admin`; `center` → `#/center` (department cards → `#/d/<id>` with "Back to overview"); `department` → first visible department; switcher only when >1 visible department. Out-of-scope department ids → "Page not found".
- Center branding (`primary_color`, `secondary_color`, logo) and department accent (`departments[].color`) applied as CSS variables; `data-env` on `<body>` (dentistry gets the AeroDent warm canvas).
- 401 → login screen with reason (`session_replaced`, `center_inactive`, `account_inactive`). 403 `csrf_token` → CSRF refreshed from `/auth/me` and retried once.
- Offline: `{offline:true}` mutations queue on network failure; replay on `online`, on first successful request and every 30 s; 2xx removes, 5xx/429/`op_in_progress`/network keep (order preserved), other 4xx → "Sync issue — requires attention" (review: details / retry / discard). Queue + cache are partitioned by user id; cache cleared on logout/user change.
- localStorage holds only `hc.lang`.
- Dates: Asia/Damascus via Intl, month/day order (`10/04`, year when not current), `HH:MM` 24 h.

## Endpoints used
`POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/change-password`, `POST /auth/support/enter|exit`, `GET /notifications`, `POST /notifications/read`, `POST /undo`, `GET /platform/branding` (optional), `GET /admin/centers` (optional, support picker), `GET /patients?q=` (patient search; degrades if absent), `PATCH /files/<id>` + `GET /files/<id>/content` (viewer).

## Status
Implemented and verified in the browser pane against `healthcenter_dev` (desktop 1280×800 and mobile 375×812, EN and AR): login, center overview cards, department environment + switcher (receptionist with 2 departments), doctor (no switcher, no center access), superadmin portal + support enter/exit with banner, session-replaced logout message, offline queue (queued → replayed → applied; 404 → sync issue → discard), data table, form field errors from `error.details`, patient search, undo toast, image viewer annotations with rotation. All JS passes `node --check`; named imports cross-checked.

### Demo logins (healthcenter_dev, "Frontend Demo Center")
Password for all: the value used for `HC_DEMO_PASSWORD` / `HC_SUPERADMIN_PASSWORD` when seeding (kept outside the repo; not written here).
- `devadmin_3@aerodent.com` — superadmin (created with `flask admin create-superadmin --username devadmin`)
- `fe-manager@demo.local` — center manager (Dentistry, Dermatology, Laboratory, General Medicine; 1 clinic each)
- `fe-doctor@demo.local` — doctor, Dentistry Clinic 1
- `fe-reception@demo.local` — receptionist scoped to Dentistry + Dermatology departments

## Known issues
- Service worker registration is refused by the embedded browser pane used for verification ("unknown error when fetching the script" although `/sw.js` is served 200 `text/javascript`); verify in a normal Chrome/Edge on localhost.
- Reloading the app while fully offline shows a retry screen (`/auth/me` is not cached on purpose — it carries the CSRF token); an already-open app keeps working offline.
- Missing module entry files log a console error per module (the dev server answers unknown paths with `index.html`); harmless.

## Needs from others
- Admin module: register routes/menus with area `admin` and paths `centers, modules, plans, users, storage, audit, settings`; `/platform/branding` fields used: `platform_name`/`name`, `login_message`, `logo_url`, `primary_color`.
- Center-admin module: center slots `staff`, `settings`; patients/appointments/billing/inventory/reports: center slots `patients, appointments, financial, inventory, reports` and department slots `patients, appointments`.
- Files API: `PATCH /files/<id>` accepting `{annotations, version}` and returning the file JSON with new `version`.
- Patients API: `GET /patients?q=&per_page=` returning `{items:[{id, name|full_name|first_name/last_name, code, phone, date_of_birth}]}`.
- Lead: add new module names to `web/js/modules.js` when created; keep `.env`/dev DB schema current (see below).

## Core changes made
- None to backend code. **Dev DB repair (healthcenter_dev only, no data loss):** the `users` unique indexes were stale (`lower('email'::text)` / `lower('username'::text)` — constant expressions allowing only one user in the whole table), recreated as `lower(email)` / `(health_center_id, lower(username))` matching `models/users.py`; and ran the idempotent `flask db init-schema` because the dev RLS policies predated the current core (login of center users failed on `audit_logs` RLS). Test DBs were already correct.
