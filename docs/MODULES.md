# Modules

Detail per module: `docs/modules/<m>.md`. Environment = which working UI/data model a department type uses.

| Module | Type | Environment | Status |
|---|---|---|---|
| Dentistry | Specialized | dentistry (AeroDent) | In progress |
| Dermatology (+ Laser Hair Removal submodule) | Specialized | dermatology | In progress |
| Ophthalmology | Specialized | ophthalmology | In progress |
| Radiology | Specialized | radiology | In progress |
| Laboratory | Specialized | laboratory | In progress |
| Pharmacy | Specialized | pharmacy | In progress |
| General Medicine | Generic | generic | In progress |
| Pediatrics | Generic | generic | In progress |
| Cardiology | Generic | generic | In progress |
| Neurology | Generic | generic | In progress |
| Nutrition | Generic | generic | In progress |
| Custom departments (Superadmin-defined) | Generic | generic | In progress |

## Shared platform modules
| Module | Status |
|---|---|
| Auth / sessions / permissions / tenancy (core) | Implemented |
| Admin (superadmin portal) + Center management | In progress |
| Patients / visits / prescriptions / files | In progress |
| Appointments | In progress |
| Billing / documents (PDF) | In progress |
| Inventory | In progress |
| Reports / exports (Excel, PDF) | Not started |
| Offline sync (frontend queue + X-Op-Id) | Backend implemented; frontend in progress |
| Notifications | Backend implemented |
