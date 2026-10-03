# Inventory + Pharmacy modules

Spec §41, §42, §57-60, §59 (USB scanners), §76 (low-stock notification).
Code: `backend/app/modules/inventory/` (`models.py`, `service.py` catalog/locations/access, `stock.py` stock
operations, `reports.py` read views, `api.py`) and `backend/app/modules/pharmacy/` (`models.py`, `service.py`,
`api.py`). Tests: `tests/test_inventory_core.py`, `tests/test_inventory_concurrency.py`,
`tests/test_pharmacy_dispense.py`.

## Status
Backend complete (round 1). 15 module tests + `test_core_auth.py` pass. No UI yet.

## Data models
| Table | Notes |
|---|---|
| `inventory_items` | Center catalog: name, category, sku (unique per center, case-insensitive), barcode (unique per center when set), unit, cost, selling_price, low_stock_threshold, supplier, is_medication, `department_id` (owner; NULL = center-wide item), is_active, notes, version, undo-delete |
| `inventory_locations` | kind `clinic` (clinic_id + its department_id) / `department_pool` (department_id) / `center_pool`; one row per target (partial unique indexes); created on demand |
| `stock_lots` | item + location + optional lot_code + optional expiry_date, `quantity >= 0` (CHECK), unit_cost (weighted average when merged) |
| `stock_movements` | append-only ledger (UPDATE blocked by trigger): type receive/use/adjust/transfer_out/transfer_in/dispense/sale/write_off, signed quantity, balance_after (item total at the location), reason, reference_type/id, author snapshot |
| `stock_transfers`, `stock_transfer_items` | immediate (status `completed`) transfer; items keep the lots moved (JSON snapshot) |
| `pharmacy_dispensations`, `pharmacy_dispensation_items` | what was actually dispensed per prescription line: inventory item, qty, substitution flag + note, lots |
| `pharmacy_sales`, `pharmacy_sale_items` | OTC sale at a pharmacy clinic: optional patient / customer name, unit price, line total, total, paid_amount (change/balance computed) |

## Access rules
Item visibility: center-wide items visible to everyone with `inventory.view`; department items to principals who
see that department. Create/edit needs `inventory.edit` + seeing the owner department; center-wide items can be
created/edited only by center-wide principals (manager, center receptionist). Delete needs `inventory.delete`;
blocked (409 `item_in_use`) once the item has any movement — deactivate instead.

Locations:
| Kind | view / draw (use, transfer out/into, dispense, sale) | manage (receive, adjust, write-off) |
|---|---|---|
| clinic | clinic in scope | clinic in scope |
| department_pool | department visible (any clinic of it in scope) | department-level access (dept manager, dept receptionist, center-wide) |
| center_pool | center-wide | center-wide |

All mutations need `inventory.edit`. Not visible → 404; visible but not manageable → 403. Transfers need draw on
source and view on destination (a dent1 doctor can pull from the dentistry pool into dent1 or return to it, but
cannot push to dent2).

Pharmacy: `pharmacy.dispense` AND (a pharmacy-environment clinic in scope OR center-wide), otherwise 403
`no_pharmacy_scope`. Queue spans the whole center. Pharmacy payloads expose prescription lines + patient
name/code/age/gender/allergies only. Dispensing and sales act from a pharmacy clinic (`clinic_id`, defaults to the
only one in scope) and use that clinic's inventory location. Sales listing is limited to pharmacy clinics in scope.

## Concurrency
Each stock mutation locks the item row(s) (`FOR NO KEY UPDATE`, id order) then the lots (`FOR UPDATE`) before
reading balances; dispensing additionally locks the prescription and its items first. Concurrency test: 7 threads
each using 3 of 10 → exactly 3 succeed, final 1. FEFO = non-expired lots by expiry ascending, undated last;
expired lots are never auto-picked (explicit expired lot → 422 `lot_expired`, except adjust/write-off).
Insufficient stock → 409 `insufficient_stock` with `available`.

Low stock: threshold is per (item, location); a notification (`low_stock`, operational text only) is sent when a
decrement takes the location total from > threshold to <= threshold (clinic → clinic staff via
`notifications.notify(clinic_id)`, dept pool → department, center pool → managers).

## Endpoints — `/api/v1/inventory`
| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/meta` | inventory.view | locations (+can_manage), categories, units, departments, movement types, capability flags |
| GET | `/items` | inventory.view | `q, category, is_medication, department_id, active`, paginated |
| POST | `/items` | inventory.edit | `department_id` defaults to the user's single visible department |
| GET | `/items/<id>` | inventory.view | + `stock` per visible location |
| PATCH | `/items/<id>` | inventory.edit | `version` required |
| DELETE | `/items/<id>` | inventory.delete | staged, undo via `/undo` |
| GET | `/lookup?code=` | inventory.view | exact barcode, then case-insensitive SKU (USB scanner); + stock |
| GET | `/locations` | inventory.view | auto-creates rows for clinics/pools in scope |
| GET | `/stock` | inventory.view | per item×location: quantity, usable, expired, nearest_expiry, low; `location_id,item_id,q,category,is_medication,include_zero` |
| GET | `/lots?item_id=` | inventory.view | `location_id, include_empty` |
| POST | `/receive` | inventory.edit + manage | `location_id,item_id,quantity,lot_code,expiry_date,unit_cost,reason` |
| POST | `/use` | inventory.edit + draw | `quantity, lot_id?, reason, reference_type, reference_id` (FEFO) |
| POST | `/adjust` | inventory.edit + manage | `delta` (+/-), `reason` required, `lot_id?` |
| POST | `/write-off` | inventory.edit + manage | `lot_id` (+`quantity`) or all expired lots at location (`item_id?`) |
| POST | `/transfers` | inventory.edit | `from_location_id,to_location_id,items[{item_id,quantity,lot_id?}],notes`; atomic |
| GET | `/transfers`, `/transfers/<id>` | inventory.view | visible if either end is visible |
| GET | `/movements` | inventory.view | `location_id,item_id,type,reference_type,reference_id,date_from,date_to`, newest first |
| GET | `/low-stock` | inventory.view | `location_id?` |
| GET | `/expiry` | inventory.view | `days` (default 30), `location_id,item_id,is_medication`; status expired/expiring, days_left |

## Endpoints — `/api/v1/pharmacy` (all require pharmacy access as above)
| Method | Path | Notes |
|---|---|---|
| GET | `/meta` | pharmacy clinics in scope with their `location_id`, statuses |
| GET | `/queue` | `status` (open (default) / all / pending / partially_dispensed / dispensed / cancelled), `q` (name / PAT code), `patient_id`, dates |
| GET | `/prescriptions/<id>` | lines + patient brief + dispensations |
| POST | `/prescriptions/<id>/dispense` | `clinic_id?, version?, notes, complete?, items[{prescription_item_id, inventory_item_id? (defaults to the line's link), quantity, lot_id?, is_substitution?, note}]`. Substitution (different item than the linked one, or flagged) requires `note`. Cannot exceed prescribed qty. Status: pending → partially_dispensed → dispensed (all lines fulfilled, or `complete: true`). Closed → 409 `prescription_closed` |
| GET/POST | `/sales` | create: `clinic_id?, patient_id? (must be visible), customer_name, paid_amount (default total), notes, items[{inventory_item_id, quantity, unit_price? (default selling_price), lot_id?}]` |
| GET | `/sales/<id>` | with items |
| GET | `/medications` | active `is_medication` items with usable stock at the pharmacy location; `q, in_stock, clinic_id` |
| GET | `/expiry` | expiry report for the pharmacy location; `days, clinic_id` |

## Billing integration (not done)
Sales are self-contained (total, paid_amount). `modules/billing/service.create_invoice` exists but was in flux;
to integrate later, create an invoice from the sale lines after `create_sale` commits and store `invoice_id` on
`pharmacy_sales` (additive column via `register_sql`).

## Known issues / limits
- Low-stock list only includes (item, location) pairs that have ever held a lot.
- Transfers are immediate (no in-transit state); no transfer reversal endpoint (use a reverse transfer).
- Dispensing does not link the patient to the pharmacy clinic (patients module visibility unchanged).

## Needs from others
- Prescriptions module: when creating items with `inventory_item_id`, only link `is_medication` items (pharmacy
  validates on dispense anyway). Do not edit/cancel prescriptions with status `dispensed`.
- Frontend: `/inventory/lookup?code=` is designed for keyboard-wedge scanners (input + Enter).

## Core changes made
None.
