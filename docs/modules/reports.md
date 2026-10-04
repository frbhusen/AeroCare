# Reports & exports

Package: `backend/app/modules/reports/` (common, clinical, financial, operations, service, export, api). Tests: `tests/test_reports_*.py`.

## Endpoints
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/reports` | reports.view | Catalog of reports the caller may run: filters, group_by, views, en/ar labels, export formats, default range, in-scope departments/clinics/doctors |
| GET | `/reports/<key>` | reports.view + data perm | JSON `{columns, rows, totals, meta, notes, truncated}`; rows capped at 1000 |
| GET | `/reports/<key>/export?format=xlsx\|pdf&lang=en\|ar&columns=a,b` | reports.export + same checks | xlsx (openpyxl, RTL sheets for Arabic, text cells never formulas) or PDF (`services.pdf.render_document`, kind `report`) |

Keys: patients, appointments, doctor_activity, clinic_activity, department_activity, revenue, outstanding, services, treatments (dental), inventory (views stock/low_stock/expiry/movements), laboratory, radiology.

Filters: `date_from`/`date_to` (Asia/Damascus local dates; default last 30 days; max 1830 days), `department_id`, `clinic_id`, `doctor_id`, `group_by`, `view`, `location_id`, `days`, `columns`. Out-of-scope filter values → 404 (filters only narrow).

## Permission chain
`reports.view` → report data permission → scope (tenant + clinic/department clauses on every aggregate query).
Data permissions: billing reports `billing.view`; patients `patients.view`; appointments `appointments.view`; activity reports `appointments.view` + `medical_records.view`; inventory `inventory.view`; lab/radiology request/process permission or `medical_records.view`. `department_activity` needs department-level access (doctors → 403).

## Notes / known issues
- Doctors and receptionists lack `reports.export` by default (grant via role/user permissions).
- Visits/prescriptions attributed to author; dental treatments to assigned doctor.
- Services report does not distribute invoice-level discounts; revenue report shows net.
- Outstanding report ignores the date range (current balances).
- Center-wide users include data from deactivated clinics.
- Arabic PDF layout not visually verified.

## UI
Build from the catalog endpoint; column keys drive the column picker.
