# Permissions (authoritative)

Code: `backend/app/authz/permissions.py` (catalog, `ROLE_DEFAULTS`, `ROLE_FORBIDDEN`), `authz/principal.py` (scope).
Frontend hiding is never security: every endpoint checks `authenticated → center → role → department → clinic → permission`.

## Roles
| Role | Center | Scope (clinics accessible) | Notes |
|---|---|---|---|
| `superadmin` | none (platform) | Platform portal; support view of a center = read-only medical (`SUPPORT_READ`) | Never edits medical history |
| `center_manager` | one | all active clinics (`center_wide`) | Full permissions; password resets |
| `department_manager` | one | all clinics of `users.department_id` | Head doctor; max one per department (`health_center_departments.head_user_id`) |
| `doctor` | one | exactly `users.clinic_id` | Reassignment = change clinic_id → immediate access switch |
| `receptionist` | one | union of `user_scopes`: center (both NULL) / department / clinic | May span departments |

Inactive modules (Superadmin deactivated) and inactive/deleted departments/clinics are removed from every scope.

## Effective permissions
`ROLE_DEFAULTS[role]` ± center overrides (`role_permissions`) ± user overrides (`user_permissions`) − `ROLE_FORBIDDEN[role]`.
Managed by `permissions.manage` (center manager; department manager for users in own department). Revocable.

Defaults summary:
| Permission group | Manager | Dept mgr | Doctor | Receptionist |
|---|---|---|---|---|
| patients.view/create/edit/delete | ✓ | ✓ | ✓ | ✓ |
| patients.delete_with_history | ✓ | ✓ | – | – |
| appointments.* | ✓ | ✓ | ✓ | ✓ |
| medical_records.view | ✓ | ✓ | ✓ | ✓ (in scope) |
| medical_records.create/edit/delete | ✓ | ✓ | ✓ | – (grant per user) |
| files.view/upload | ✓ | ✓ | ✓ | ✓ |
| files.edit/delete/share | ✓ | ✓ | ✓ | – |
| billing.view/create/edit | ✓ | ✓ | ✓ | ✓ |
| billing.delete, services.manage | ✓ | ✓ | – | – |
| inventory.view/edit | ✓ | ✓ | ✓ | ✓ |
| inventory.delete | ✓ | ✓ | – | – |
| pharmacy.dispense | ✓ | ✓ | ✓ | ✓ |
| lab.request / radiology.request | ✓ | ✓ | ✓ | ✓ |
| lab.process / radiology.process | ✓ | ✓ | ✓ (only in lab/radiology clinics) | – |
| lab.manage_tests | ✓ | ✓ (lab dept manager) | – | ✗ forbidden |
| staff.view | ✓ | ✓ | ✓ | – |
| staff.create/edit/delete | ✓ | ✓ (own department) | – | – |
| settings.view / settings.edit | ✓ / ✓ | ✓ / ✓ (own dept & clinics) | ✓ / – | – |
| permissions.manage, audit.view | ✓ | ✓ (own dept) | ✗ | ✗ |
| reports.view / reports.export | ✓ | ✓ | view (scoped) | view (scoped) |
| backup.create | ✓ | ✗ | ✗ | ✗ |

## Scope rules
- **Out of scope ⇒ 404**, in scope but missing permission ⇒ 403.
- **Department isolation**: navigation lists only `visible_department_ids`; APIs reject other departments' objects.
- **Clinic isolation**: medical data (visits, specialty records, prescriptions, files) is owned by `clinic_id`. Doctors see all records of their current clinic regardless of author; never other clinics.
- **Patients**: one identity per center. Visible if linked (`patient_clinic_links`) to an accessible clinic; center-wide principals see all. Profile shows *departments with records* (high-level indicator) and marks inaccessible ones as restricted — no details leak.
- **Patient summary**: built only from data the principal can access.
- **Receptionists**: medical records view in scope; edit only with explicit per-user grant (`user_permissions`).
- **Department manager** manages staff/settings/inventory/reports of own department only; cannot touch other departments.
- **Health Center Manager** has every department-manager capability for departments without a head doctor (and all others).

## Files
Visible if `files.view` and one of: owning clinic in scope; department-level file in a managed department; `center_wide` (finalized lab reports, branding); explicit `file_shares` to one of the principal's clinics/departments or the user; center-wide principal. Manage (rename/annotate/delete/share) requires owning clinic in scope (or managed department / center-wide). Shares revocable.

## Lab / Radiology results
- Finalized lab results/reports: readable by any staff with `medical_records.view` who can see the patient (center-wide availability, spec §104). Does not grant lab workflow/admin access.
- Radiology final report: requesting clinic, radiology department, managers, plus explicit shares.
- Lab/radiology staff only see requests addressed to their department plus the patient's general profile — never unrelated specialty histories.

## Financial
Controlled only by `billing.*` (no role-based hiding). Managers have full visibility in scope. Discounts allowed for anyone with `billing.edit`/`billing.create`.

## Audit logs
Superadmin: all. Center manager: own center. Department manager: entries with own `department_id`. Others: none.

## Superadmin
Platform: centers, modules, plans/limits, subscription status, users, storage quotas, platform settings/branding, audit, account resets. Support view of a center via `/api/v1/auth/support/enter` (read-only medical; staff/settings management allowed).
