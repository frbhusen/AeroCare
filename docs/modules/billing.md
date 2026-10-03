# Billing module + shared PDF/document engine

Spec §51–56, 61 (revenue/outstanding basics), 63–66, 68. Backend only (UI next round).

## Files
- `backend/app/modules/billing/` — `models.py`, `pricing.py` (services/prices), `service.py` (invoices/payments/history), `summary.py`, `printing.py` (JSON serializers + invoice/receipt PDFs), `templates.py` (document template CRUD), `api.py`.
- `backend/app/services/pdf.py` — the PDF engine shared by every module.
- `backend/app/services/documents.py` — template inheritance + one-call branded rendering.
- Tests: `tests/test_billing_invoices.py`, `tests/test_billing_services.py`, `tests/test_pdf_engine.py`, helpers in `tests/test_billing_helpers.py`.

## Data models
| Table | Notes |
|---|---|
| `billing_services` | center-wide (department NULL), department-level or clinic-level; name, category, kind (default item kind), cost, price, duration_minutes, is_active, notes; version; delete+undo |
| `billing_service_prices` | override for exactly one department **or** clinic (unique per service+level). Effective price: clinic → department → service.price |
| `invoices` | number (per-center `invoice_seq`, shown `INV-000001`, unique), patient, department, clinic (required), doctor_user_id + doctor_name snapshot, status draft/issued/partially_paid/paid/void, subtotal, invoice_discount, discount_total, total, paid_total, balance, currency (from center), notes, issued_at, voided_at/void_reason, author snapshot, version, delete+undo. DB CHECKs: `total = subtotal - discount_total`, `balance = total - paid_total`, `paid_total <= total` |
| `invoice_items` | kind (consultation/treatment/procedure/lab_test/radiology/medicine/product/service/other), service_id (nullable), description, qty, unit_price, list_price (catalog price at the time), discount_percent or discount_amount, line_total (CHECK = round(qty*unit_price,2) − discount), reference_type/reference_id |
| `payments` | seq per invoice (receipt no. `INV-000001-2`), amount > 0, method CHECK IN ('cash'), paid_at, received-by author snapshot, notes, void flag (+voided_at/by/reason). Never edited; corrected by voiding |
| `document_templates` | center (department NULL) or department; kind in prescription/invoice/receipt/lab_report/radiology_report/visit_summary/patient_summary/appointment_slip; title, header_text, footer_text, show_logo (NULL = inherit), accent_color, extra JSON; one live row per level+kind |

Money: NUMERIC(14,2), Decimal everywhere, serialized as strings (`"380.00"`). Rounding ROUND_HALF_UP.

## Status rules
draft → (issue) issued → payments → partially_paid → paid. Paying a draft issues it first (needs ≥1 item). Only drafts are editable (items replaced as a whole). Void only when no active payments (void the payments first). Overpayment → 422 `overpayment`. Payment adds/voids lock the invoice row (`FOR UPDATE`). Discounts: anyone with billing.create/edit (no manager-only rule).

## Endpoints (`/api/v1/billing`)
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/meta` | billing.view | currency, statuses, item kinds, methods (`["cash"]`), template kinds, categories, `can` flags |
| GET | `/services` | billing.view | filters `clinic_id` (applicable services + `effective_price`/`price_source`), `department_id`, `level=center`, `active`, `category`, `q`; paginated |
| POST | `/services` | services.manage | level from `department_id`/`clinic_id`; center-wide services need center-wide scope |
| GET/PUT/DELETE | `/services/<id>` | billing.view / services.manage | PUT needs `version`; DELETE → 202 undo token |
| GET | `/services/<id>/prices` | billing.view | overrides visible in scope |
| PUT | `/services/<id>/prices` | services.manage | upsert `{clinic_id | department_id, price}` |
| DELETE | `/services/<id>/prices/<pid>` | services.manage | removes override (hard delete; reverts to inherited price) |
| GET | `/services/<id>/effective-price?clinic_id=` | billing.view | `{price, source: clinic|department|service}` |
| GET | `/invoices` | billing.view | filters patient_id, clinic_id, department_id, doctor_user_id, status (comma list), date_from/date_to (local dates, on issued_at or created_at), q (number or patient name); returns `sums` (total/paid/balance of non-draft, non-void) |
| POST | `/invoices` | billing.create (+clinic scope) | `{patient_id, clinic_id, doctor_user_id?, notes?, invoice_discount?, items:[{kind?, service_id?, description?, qty?, unit_price?, discount_amount? | discount_percent?, reference_type?, reference_id?}], issue?}`. unit_price defaults to the effective service price; custom prices allowed. Doctor defaults to the creating doctor in their clinic. Links patient↔clinic |
| GET | `/invoices/<id>` | billing.view | full invoice with items + payments |
| PUT | `/invoices/<id>` | billing.edit | drafts only, `version` required |
| POST | `/invoices/<id>/issue` | billing.create | optional `version` |
| POST | `/invoices/<id>/void` | billing.edit | `{reason?, version?}` |
| DELETE | `/invoices/<id>` | billing.delete | 202 + undo (`POST /api/v1/undo`) |
| POST | `/invoices/<id>/payments` | billing.create | `{amount, method?="cash", paid_at?, notes?}` → `{payment, invoice}` |
| POST | `/invoices/<id>/payments/<pid>/void` | billing.edit | `{reason?}` |
| GET | `/invoices/<id>/pdf?lang=ar|en` | billing.view | application/pdf (inline); draft/void are marked in the title |
| GET | `/invoices/<id>/receipt?lang=&payment_id=` | billing.view | A5 receipt for one payment or all active payments; 422 `no_payments` |
| GET | `/patients/<pid>/history` | billing.view | invoices + payments in the caller's clinic scope + totals (billed/paid/outstanding/discounts) |
| GET | `/summary` | billing.view | `date_from`, `date_to`, `department_id`, `clinic_id`, `doctor_user_id`, `group_by=none|department|clinic|doctor` → revenue (issued in range), payments_received (paid_at in range), outstanding_in_period, outstanding_total (all open invoices now) |
| GET | `/templates` | settings.view | `department_id` (id or `center`), `kind` |
| GET | `/templates/effective?kind=&department_id=` | settings.view | merged template + `sources` |
| POST/GET/PUT/DELETE | `/templates[/<id>]` | settings.edit (view for GET) | center level needs center-wide scope; department level needs department-level access; PUT needs version; DELETE → undo |

Scope: every invoice query uses `p.clinic_clause(Invoice.clinic_id)` (doctor = own clinic, receptionist = assigned clinics/departments, department manager = their department, center manager = all). Out of scope or other tenant → 404.

## PDF engine API (for lab / radiology / prescriptions / patients / appointments)
Recommended call, after you have authorized access to the record:
```python
from backend.app.services import documents
pdf = documents.render(center_id, department_id, "lab_report", title, sections, lang="ar",
                       subtitle="LAB-000123", page_size="A4")   # or "A5"
return documents.pdf_response(pdf, "lab-report-123.pdf")      # inline application/pdf, no-store
```
`render` loads the center (name, address, phone, primary_color, document_footer, logo from `logo_file_id`), the department (name, color) and the effective template (`documents.get_template(center_id, department_id, kind)`: department → center → defaults). Accent color: template.accent_color → department.color → center.primary_color. The footer shows template footer_text or center.document_footer, "Page n of N" and the print time (Asia/Damascus).

Low-level: `services.pdf.render_document(center, department, kind, title, sections, lang, template=None, logo_bytes=None, subtitle=None, page_size="A4")` takes ORM rows or plain dicts.

Section dicts (texts may be Arabic, English or mixed; RTL layout mirrors columns automatically when `lang="ar"`):
- `{"type": "heading", "text": ...}`
- `{"type": "paragraph", "text": "...\n...", "size": 9}` / `{"type": "note", "text": ...}` (small grey)
- `{"type": "key_values", "items": [[label, value], ...], "columns": 2}` (1–3 columns)
- `{"type": "table", "columns": [...], "rows": [[...]], "widths": [3,1,1], "align": ["start","center","end"]}` (header row repeats on new pages)
- `{"type": "totals", "items": [[label, value], [label, value, True]]}` (3rd item = bold with rule)
- `{"type": "signature", "labels": ["Doctor", "Patient"]}`
- `{"type": "image", "data": bytes, "width": mm, "caption": ...}`, `{"type": "spacer", "height": mm}`, `{"type": "page_break"}`
Helpers: `pdf.visual(text)` (shape + bidi one line), `pdf.format_money(amount, currency)`, `pdf.format_dt(dt)` (local `YYYY-MM-DD HH:MM`), `pdf.t(key, lang)`.

Fonts: `PDF_FONT_PATH` (+ `PDF_FONT_BOLD_PATH`) env → DejaVuSans / Noto Sans Arabic (Linux paths) → `C:/Windows/Fonts/tahoma.ttf`/`tahomabd.ttf` → arial. If none is found it falls back to Helvetica: no crash, but Arabic glyphs will not render. **Production Linux must have `fonts-dejavu-core` installed or set PDF_FONT_PATH.** No fonts are vendored.

## Status
Done (backend): models, services, API, PDFs, templates. Tests: 16 billing/pdf tests + test_core_auth (7) + test_security_routes pass on healthcenter_test_4.

## Known issues / notes
- Arabic shaping and bidi are tested only for not crashing and returning `%PDF`. Nobody has checked the RTL layout by eye yet, because this machine cannot render PDFs (no poppler).
- Services: a staged-deleted service that gets purged nulls `invoice_items.service_id` through a before_purge hook. Items keep their description and price.
- The doctor on an invoice must be a user of this center with role doctor, department_manager or center_manager. The name is stored as a snapshot.
- Observation (core): composite tenant FKs with `ondelete="SET NULL"` (e.g. `fk_rx_visit`, `fk_file_visit`) would also null `health_center_id` (NOT NULL), so purging a referenced visit would fail. Billing avoids SET NULL composite FKs. Lead should review.

## Needs from others
- Lab / radiology / dental modules: create invoice lines with `reference_type` (e.g. `lab_request`, `radiology_study`, `dental_treatment`) and `reference_id` through `POST /billing/invoices`, or reuse `service.create_invoice(p, data)` with the same validated shape.
- Reports module: may reuse `modules/billing/summary.summary(p, args, start, end)`.
- Frontend: the UI is cash only. Use `/billing/meta` for form choices.

## Core changes made
None.
