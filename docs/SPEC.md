AeroDent-Online — Full Health Center Management Platform
ROLE
Act as the lead software architect and implementation engineer for this project.
Transform the current AeroDent-Online codebase into a secure, scalable, multi-tenant Health Center Management Platform while preserving and integrating the existing Dentistry/AeroDent functionality as the Dentistry department.
Do not treat AeroDent/Dentistry as the main platform anymore.
The final architecture must be:

```text
Platform
└── Health Center
    ├── Departments / Specialties
    │   ├── Clinics
    │   │   └── Doctors
    │   └── Department-level staff
    └── Center-level staff

```

The platform must support multiple health centers in the same system, with strict tenant isolation.
This is a production-oriented application handling medical, financial, patient, staff, and uploaded-file data.
1. NON-NEGOTIABLE TECH STACK
Use:

* Frontend: HTML + CSS + Vanilla JavaScript
* Backend: Flask
* ORM: SQLAlchemy
* Database: PostgreSQL
* Hosting: dedicated Linux server
* Production stack: Nginx + Gunicorn + Flask + PostgreSQL
* File storage: server-side secure object/file storage abstraction suitable for future expansion
* HTTPS in production
* Environment variables for secrets and deployment configuration

Do not introduce React, Vue, Angular, or another frontend framework.
Libraries are allowed when genuinely useful.
Prefer small, well-maintained libraries over large unnecessary dependencies.
2. DEVELOPMENT APPROACH
This is a large multi-agent project.
Use multiple agents/subagents where appropriate and parallelize independent work.
Do NOT artificially split the implementation into a sequential "Phase 1 / Phase 2 / Phase 3" process.
Instead:

* maintain one shared architecture/task specification
* divide work by independent domains
* let agents work in parallel when their file ownership does not conflict
* coordinate before modifying shared/core files
* integrate continuously
* test after integration
* never leave known broken code behind

Possible agent/workstream areas:

* core backend architecture
* authentication/authorization
* multi-tenancy/security
* patient/medical model
* appointments
* billing
* inventory
* file storage
* Dentistry/AeroDent
* Dermatology/Laser
* Ophthalmology
* Laboratory
* Radiology
* Pharmacy
* frontend/core design
* reporting/export
* offline synchronization
* testing/security/deployment

Use the available Claude Code skills/tools whenever they materially help.
At the beginning:

1. Inspect the available project structure and existing implementation.
2. Inspect the available Claude Code skills.
3. Use the smallest relevant skill/tool instead of manually reproducing information.
4. Avoid repeatedly reading large files when targeted inspection is enough.
5. Keep agent context compact and reuse established architecture decisions.
6. Prefer targeted edits over rewriting unrelated files.
7. Do not repeatedly explain requirements that are already in this document.


KNOWLEDGE / PROJECT CONTEXT FILES — REQUIRED
Because this project is being developed by multiple Claude Code agents, maintain a persistent set of concise project knowledge files inside the project.
These files are part of the project's development infrastructure and must be kept accurate.
Before making meaningful architectural or cross-module changes, agents MUST read the relevant knowledge files.
Agents must NOT rely only on conversation context.
Create and maintain at minimum:

```text
docs/
├── ARCHITECTURE.md
├── DATABASE.md
├── PERMISSIONS.md
├── API.md
├── MODULES.md
├── AGENT_GUIDE.md
├── DECISIONS.md
├── TASK_STATUS.md
└── CHANGELOG.md

```

ARCHITECTURE.md
Document:

* application architecture
* frontend/backend separation
* Flask structure
* major backend modules
* frontend module structure
* authentication architecture
* multi-tenant architecture
* file-storage architecture
* offline synchronization architecture
* production deployment architecture

Keep this concise and update it whenever architecture changes.
DATABASE.md
Document:

* important tables/models
* relationships
* tenant ownership
* department/clinic relationships
* patient model
* medical-record model
* specialty-specific models
* important constraints
* indexes
* deletion/undo behavior

Do not paste the entire generated schema into this file unless necessary.
PERMISSIONS.md
Document the authorization model:

```text
Superadmin
Health Center Manager
Department Manager
Doctor
Receptionist

```

Document:

* role capabilities
* scope rules
* department isolation
* clinic isolation
* patient visibility
* medical-record visibility
* file-sharing rules
* financial permissions

This file is the authoritative reference for access-control behavior.
API.md
Document:

* API version
* endpoint groups
* authentication requirements
* authorization rules
* request/response conventions
* common error format
* important endpoint behavior

Keep examples concise.
MODULES.md
Document every department/module.
For each module record:

* module name
* module type
* specialized/generic
* current implementation status
* major features
* important data models
* dependencies on shared platform functionality

Example:

```text
Dentistry
Type: Specialized
Environment: AeroDent
Status: Integrated

Dermatology
Type: Specialized
Status: Implemented

General Medicine
Type: Generic
Status: Implemented

```

AGENT_GUIDE.md
This is the most important file for multi-agent development.
Document:

* project-wide coding conventions
* directory ownership
* shared/core files
* rules for editing shared files
* how agents should communicate changes
* how to avoid conflicting modifications
* required tests before completion
* security rules
* what must never be changed without checking dependencies

Every new agent should read this file first.
DECISIONS.md
Record important architectural decisions and their reasoning.
Use concise entries such as:

```text
2026-10-03
Decision:
Use Health Center → Department → Clinic → Doctor hierarchy.

Reason:
Clinics are operational units inside the same health center, not branches.

Impact:
No branch entity is required.

```

Do not repeatedly revisit already-decided architecture unless new evidence requires it.
TASK_STATUS.md
Track current implementation status.
Use simple sections:

```text
Completed
In Progress
Blocked
Needs Verification
Known Issues

```

Keep it current so a new agent can quickly understand the current state.
CHANGELOG.md
Record meaningful implementation changes.
Do not log every tiny CSS edit.
Record things such as:

* new modules
* schema changes
* security changes
* authorization changes
* major UI changes
* migrations
* bug fixes affecting important behavior

KNOWLEDGE FILE RULES
Knowledge files must remain concise and useful.
Do NOT dump source code into them.
Do NOT duplicate large amounts of implementation documentation unnecessarily.
Do NOT allow different knowledge files to contradict each other.
When a major decision changes:

1. update the authoritative knowledge file
2. update DECISIONS.md
3. update any affected documentation
4. update TASK_STATUS.md if implementation status changed

When an agent finishes a meaningful task:

1. update TASK_STATUS.md
2. update relevant knowledge files
3. add an appropriate CHANGELOG entry if the change is significant

Before modifying a shared architectural component, an agent should check:

* ARCHITECTURE.md
* DATABASE.md
* PERMISSIONS.md
* AGENT_GUIDE.md

as applicable.
SOURCE OF TRUTH
When documentation and implementation disagree:

1. inspect the actual implementation
2. determine the intended current behavior
3. fix the documentation or code as appropriate
4. never blindly trust stale documentation

Do not create documentation merely for appearance.
The knowledge files must genuinely help future Claude Code agents understand the project with minimal context consumption.
TOKEN EFFICIENCY
Knowledge files should be optimized for agent consumption:

* concise
* structured
* factual
* no repeated explanations
* no unnecessary prose
* prefer tables and compact sections where useful

Agents should read only the relevant files instead of loading the entire documentation set for every task.


3. CORE PRODUCT CONCEPT
The platform is a general health-center management system.
A single health center can have multiple departments/specialties.
A department can contain multiple clinics.
A doctor belongs to exactly one clinic.
Example:

```text
Al-Shifa Health Center

Dentistry
├── Dental Clinic 1
├── Dental Clinic 2
└── Dental Clinic 3

Dermatology
├── Dermatology Clinic 1
└── Dermatology Clinic 2

Neurology
└── Neurology Clinic 1

Laboratory
└── Laboratory 1

```

All clinics exist within the same health center/building.
A clinic is an operational working unit, not a separate geographic branch.
Each clinic can have a customizable text-based location, e.g.:

```text
Room 101
Dental Room A
Second Floor - Room 4
Laser Room
Lab 1

```

Do NOT introduce a branch/location hierarchy.
4. DEPARTMENT VS CLINIC
These concepts must remain separate.
Department
A specialty/module:

* Dentistry
* General Medicine
* Dermatology
* Pediatrics
* Cardiology
* Ophthalmology
* Neurology
* Nutrition
* Laboratory
* Pharmacy
* Radiology

Future departments must be expandable.
Laser Hair Removal is part of Dermatology, not a separate top-level department.
Clinic
A separate operational unit inside a department.
Example:

```text
Dentistry
├── Dental Clinic 1
├── Dental Clinic 2
└── Dental Clinic 3

```

Each clinic may have:

* name
* customizable location text
* phone
* email
* logo
* working hours
* staff assignments
* departments/module configuration as appropriate
* appointment settings
* services
* prices
* inventory relationships

5. PLATFORM HIERARCHY
Superadmin
This is the platform owner.
There must be a separate Superadmin portal/dashboard, but it must use the same main application URL.
Do NOT create a separate domain.
After login, the system determines the user's portal based on role.
Health Center Manager
The main administrator for one health center.
Has complete access to that health center.
Department Manager / Head Doctor
Optional.
Exactly one possible head doctor/manager per department.
A head doctor manages the entire department and all clinics inside it.
Example:

```text
Dentistry
Head Dentist: Dr. Hassan

├── Dental Clinic 1
├── Dental Clinic 2
└── Dental Clinic 3

```

A head doctor can manage everything in that department, but nothing in other departments.
If a department does not have a head doctor, the Health Center Manager already has the same management capabilities.
Doctor
Each doctor belongs to exactly one clinic.
A doctor can access:

* patients belonging to their clinic
* all medical records belonging to that clinic
* all previous visits/records within that clinic regardless of which doctor created them
* clinic appointments within their scope

A doctor cannot access another clinic's records.
Receptionist / Secretary
No nurses for now.
Receptionists may be assigned:

* to the whole health center
* to one or more departments
* to specific clinics

If assigned to a whole department, they can access all clinics within that department.
If assigned only to selected clinics, they can access those clinics only.
A receptionist can work across multiple departments.
6. USER ACCOUNTS
One account per person.
Fields should include at minimum:

* immutable internal user ID
* username
* name
* email
* password
* role
* active/archived state
* relevant scope assignments

Rules:
Username

* English only
* no spaces
* unique only as needed for account generation; different health centers may use the same username
* username may be changed later

Name

* Arabic or English
* spaces allowed

Email
Default format:

```text
{username}_{id}@aerodent.com

```

The ID must never change.
The generated email must never conflict globally.
The email can be customized.
If the username changes and the account is still using the generated email, regenerate the generated email using the same immutable ID.
The email is an internal unique login identifier.
The system must NOT send emails.
No email infrastructure is required.
7. AUTHENTICATION
Login:

```text
Email + Password

```

Everyone logs into the same application URL.
After successful authentication, redirect based on role/scope.
There must be only one active session per user.
When the same account logs in from another device/browser, invalidate the previous session.
Do not automatically log users out because of inactivity.
Use secure production authentication:

* strong password hashing
* secure cookies
* HttpOnly
* Secure in production
* SameSite protection
* CSRF protection where applicable
* login rate limiting
* secure session invalidation
* no sensitive tokens in localStorage
* server-side authorization on every protected endpoint

Prefer a server-verifiable session architecture that makes single-session enforcement reliable.
Password reset:

* Health Center Manager
* Superadmin

No email-based password reset is required.
8. ROLE/PERMISSION SYSTEM
Permissions must be customizable.
Do not hard-code all authorization into UI visibility.
Frontend hiding is NOT security.
Every protected backend endpoint must independently verify:

```text
authenticated user
→ health center
→ role
→ department scope
→ clinic scope
→ permission

```

Use server-side policy checks.
Recommended permission categories include:

* patients.view
* patients.create
* patients.edit
* patients.delete
* appointments.view
* appointments.create
* appointments.edit
* appointments.delete
* medical_records.view
* medical_records.create
* medical_records.edit
* medical_records.delete
* billing.view
* billing.create
* billing.edit
* billing.delete
* inventory.view
* inventory.edit
* inventory.delete
* staff.view
* staff.create
* staff.edit
* staff.delete
* settings.view
* settings.edit
* reports.view
* reports.export

Make the permission system extensible.
9. STAFF CREATION
Health Center Manager can create/manage staff across the entire health center.
Department Manager can create/manage staff within their own department according to permissions and scope.
A Department Manager can create normal doctors restricted to the correct clinic/department.
Doctors must always belong to exactly one clinic.
Receptionists can have multiple scope assignments.
Nurses are not part of this version.
10. DOCTOR REASSIGNMENT MODEL
Medical history is fundamentally associated with the clinic, not permanently with the current doctor.
Example:

```text
Dental Clinic 1
→ Doctor Ahmad
→ historical records

```

If Ahmad moves to Dental Clinic 2:

```text
Doctor Ahmad
→ Dental Clinic 2

```

He immediately gets Clinic 2 access and loses Clinic 1 access.
Historical Clinic 1 records remain in Clinic 1.
New records created after the move are associated with Clinic 2.
11. DOCTOR ACCOUNT REUSE / NAME CHANGE
A doctor account may later be reused/renamed.
Example:

```text
Old account:
Dr. Ahmad

same user ID
↓
New name:
Dr. Omar

```

Existing historical records must NOT have their historical author display changed.
Therefore, medical records should preserve immutable historical author information/snapshots at record creation time.
New records use the current account identity.
The system must never rewrite historical creator information simply because a user's current name changes.
12. MULTI-TENANCY — CRITICAL
This is one of the highest-priority architectural requirements.
There may be many health centers:

```text
Health Center A
Health Center B
Health Center C
...

```

Data from one health center must NEVER leak into another.
Tenant isolation must be enforced server-side.
Every tenant-scoped query must be scoped to the current health center.
Do not trust:

* URL parameters
* frontend filters
* hidden fields
* client-provided health_center_id

Use the authenticated user's tenant context.
Implement defense in depth:

1. application-level authorization
2. tenant-scoped data-access/repository layer
3. strict foreign keys
4. database constraints
5. PostgreSQL Row Level Security or an equivalently strong database-enforced tenant boundary where practical
6. fail closed if tenant context is missing

Never allow a normal user to request arbitrary tenant IDs to bypass authorization.
Do not use a database role with unrestricted bypass capabilities for ordinary application requests.
Test cross-tenant access explicitly.
A security test must attempt to access data belonging to another health center and verify that the request is rejected.
13. HEALTH CENTER MODULE ACTIVATION
The Superadmin controls which modules/departments each health center has.
Example:

```text
Al-Shifa Health Center

✓ Dentistry
✓ Dermatology
✓ Laboratory
✓ Pharmacy
✗ Cardiology
✗ Neurology

```

A health-center manager cannot access inactive modules.
A Health Center Manager cannot create a new specialty/module type.
Only the Superadmin can create platform-level department/module definitions.
A Superadmin can later add new predefined specialties.
There must also be:

```text
Custom Department

```

as a Superadmin-created department type.
Custom departments use the generic medical environment.
14. SUBSCRIPTION PLANS
No automated online payment/subscription system.
The Superadmin manually controls plans and limits.
Basic

* 1 kind of clinic/department
* 1 head doctor maximum
* up to 3 doctors
* up to 1 receptionist/secretary
* up to 3 clinics

Professional

* up to 3 kinds of clinics/departments
* up to 3 head doctors, one for each department
* up to 6 doctors
* up to 3 receptionists/secretaries
* up to 6 clinics

Enterprise
Unlimited:

* clinic/department types
* head doctors
* doctors
* receptionists/secretaries
* clinics

The Superadmin can manually override all limits and create a custom configuration that does not match a standard plan.
The limits must be configurable in the database, not hard-coded throughout the application.
15. TRIAL
Every new health center receives a default:

```text
Status: Trial
Duration: 14 days

```

The trial uses the manually configured plan limits/default configuration.
After expiry:

```text
Trial/Active → Expired

```

Normal staff access should be blocked until the Superadmin activates, extends, or changes the center status.
16. SUPERADMIN POWERS
Superadmin has platform-wide management capabilities.
Can:

* create health centers
* activate/deactivate modules
* create department/module definitions
* create/manage health-center managers
* manage health centers
* manually configure plans
* configure plan limits
* manage subscriptions/statuses
* manage users
* manage platform settings
* manage branding
* manage storage quotas
* increase storage quotas
* inspect permitted audit logs
* reset accounts
* recover/access accounts where appropriate
* permanently delete data when explicitly necessary
* view all health-center data

Superadmin can enter/view a health center through the Superadmin portal for support/troubleshooting.
This access must still respect the platform's logging rules.
Superadmin must NOT edit medical history.
17. AUDIT LOGGING
Implement an audit system.
Audit entries must be immutable.
Nobody can edit an audit entry.
Only log these categories:
Login

* successful login
* failed login

Department management

* create
* edit
* delete

Clinic management

* create
* edit
* delete

User management

* create
* edit
* delete

Do NOT create audit logs for:

* medical-record activity
* financial/income activity
* medical record content
* financial transaction content

Visibility:
Superadmin
Can see platform-wide audit logs.
Health Center Manager
Can see logs for their health center.
Department Manager
Can see logs relevant to their department.
No other role needs audit-log access by default.
18. PATIENT MODEL
There is exactly one patient identity per health center.
Patient ID is health-center-wide and sequential.
Example:

```text
PAT-000001
PAT-000002
PAT-000003

```

The sequence must remain safe under concurrency.
Patient fields:

* patient ID
* full name
* date of birth
* gender
* phone
* address
* blood type
* allergies
* chronic conditions
* medications
* other useful general medical information

Do NOT include:

* emergency contact
* national ID
* insurance

19. PATIENT SEARCH
Global patient search must support:

* name
* phone

Do not require ID search as a core search field.
Search results must be permission-aware.
Patient search must remain fast with large amounts of data.
Use appropriate PostgreSQL indexing and query design.
Target scalability should comfortably support tens of thousands or hundreds of thousands of patients.
20. PATIENT ACCESS MODEL
A patient can visit multiple departments.
Example:

```text
Ali
├── Dentistry
└── Dermatology

```

There is still only one patient profile.
A doctor sees:

* patients linked to their clinic
* records from their clinic

They do not see other clinic data.
A department manager sees:

* all patients/records in their department

A Health Center Manager sees:

* everything in the health center

A receptionist sees:

* patients within assigned department/clinic scope

The existence of a patient's record in another department may be visible as a high-level indicator, but its actual medical details must remain restricted.
Example:

```text
Ali Ahmed

Departments with records:
✓ Dentistry
✓ Dermatology

Accessible records:
✓ Dermatology

Restricted:
🔒 Dentistry

```

21. GENERAL PATIENT PROFILE
Shared general patient information should be available to authorized staff.
Examples:

* name
* DOB
* gender
* phone
* address
* blood type
* allergies
* chronic conditions
* medications

Receptionists and higher roles can edit basic patient information according to permissions.
Changing the patient's name/phone/etc. must never modify the patient's historical medical record identity.
22. COMPLETE PATIENT SUMMARY
The system must have a Complete Patient Summary.
For the Health Center Manager, it can contain the full accessible patient history across the health center.
For other roles, generate an access-scoped summary containing only data they are authorized to see.
Do not expose restricted department information through the summary.
23. MEDICAL VISITS / ENCOUNTERS
Every patient interaction creates a separate Visit/Encounter.
Example:

```text
Ali
├── Oct 01 — Consultation
├── Oct 08 — Follow-up
├── Oct 15 — Treatment
└── Oct 22 — Follow-up

```

Do NOT build one giant mutable medical record.
Each visit should have:

* patient
* department
* clinic
* doctor/staff author
* date/time
* clinical information
* related files
* related prescriptions
* relevant specialty data

24. MEDICAL RECORD ACCESS
Doctors can see all medical records belonging to their current clinic, regardless of which doctor originally created them.
Doctors cannot access records belonging to another clinic.
Department Managers can see/edit/manage the medical information within their department according to permissions.
Health Center Managers can see everything.
Receptionists can see medical records within their scope.
Receptionists can edit medical records only if a relevant manager explicitly grants them the edit permission.
Permissions must be revocable.
25. MEDICAL RECORD DELETION
Deletion follows hierarchy/permissions.
A user with appropriate create/edit/delete permissions may delete applicable data.
Use a short server-side deletion/undo buffer:

```text
Delete
↓
30-second Undo window
↓
Permanent database deletion

```

The Undo action must not rely on the browser alone.
After the 30-second window, the data is permanently removed.
Do not silently leave deleted medical data behind indefinitely.
Medical history is not special-cased as permanently immutable anymore.
Audit logs are separate and always immutable.
26. PATIENT DELETION
Support deletion of accidentally created patient profiles.
Patient deletion must respect the hierarchy and permissions.
If a patient already has substantial medical history, use higher-level permission requirements rather than allowing a low-level user to destroy significant patient history accidentally.
Keep the exact behavior configurable through permissions where appropriate.
27. PATIENT MERGING
Do NOT implement patient-profile merging at this time.
28. NEW DEPARTMENT RECORD CREATION
When a patient first visits a new department:
Do NOT create a second patient.
Instead create the appropriate patient-department/clinic relationship and new visits under the existing patient.
Example:

```text
PAT-000123
Ali Ahmad

General Profile
│
├── Dentistry
│   └── Dental History
│
├── Dermatology
│   └── Dermatology History
│
└── Neurology
    └── No records

```

29. DEPARTMENT INTERFACE ISOLATION
This is critical for UX and privacy.
Each department must have an isolated working environment.
A normal department user should not even see that other departments exist.
Example:
A Dentistry doctor sees:

```text
Dentistry
Dashboard
Patients
Appointments
Dental Records
Prescriptions
X-Rays
...

```

They should NOT see a Dermatology menu item.
A receptionist assigned to Dentistry + Dermatology can switch between them.
A receptionist assigned only to Dentistry has no indication that Dermatology exists.
30. HEALTH CENTER MANAGER UI
The Health Center Manager gets a centralized overview.
Department navigation should NOT be a dropdown menu.
Use large visual buttons/cards similar to product cards in an e-commerce interface.
Example:

```text
[ Dentistry ]
[ Dermatology ]
[ Laboratory ]
[ Pharmacy ]
[ Radiology ]
[ Neurology ]

```

Clicking a department enters that department's isolated environment.
The manager also gets center-wide areas such as:

* Overview
* Patients
* Appointments
* Financial
* Inventory
* Staff
* Reports
* Settings

31. SUPERADMIN UI
Separate Superadmin dashboard/portal inside the same URL.
Example:

```text
Superadmin Dashboard

Health Centers
Modules
Plans
Users
Storage
Audit Logs
Platform Settings

```

The visual language can differ from normal health-center UI while still belonging to the same application.
32. DEPARTMENT TYPES
Initial top-level departments:

* Dentistry
* General Medicine
* Dermatology
* Pediatrics
* Cardiology
* Ophthalmology
* Neurology
* Nutrition
* Laboratory
* Pharmacy
* Radiology

Laser Hair Removal belongs inside Dermatology.
The platform must be expandable.
Only Superadmin can define new department/module types.
Custom module types use the generic medical environment.
33. DENTISTRY / AERODENT
Keep the existing Dentistry functionality and integrate it into the new platform.
Dentistry becomes a department:

```text
Health Center
→ Dentistry
→ Dental Clinics

```

Preserve the existing important dental functionality, including:

* permanent odontogram
* primary odontogram
* treatments
* appointments
* prescriptions
* X-rays/images
* patient management
* existing dental workflows

Refactor as needed so it follows:

* the new authentication system
* the new tenant architecture
* the new permissions
* the new file storage
* the new patient model
* the new appointment model

Do not unnecessarily remove working dental functionality.
34. DERMATOLOGY
Initial Dermatology environment:

* Dashboard
* Patients
* Appointments
* Visits
* Diagnoses
* Treatments
* Prescriptions
* Medical images/photos
* Notes
* Dermatology-specific structured fields

Build it as a dedicated environment, not merely the generic medical environment.
35. DERMATOLOGY-SPECIFIC FIELDS
Implement structured dermatology information.
Use sensible structured fields such as:

* affected area
* condition
* symptoms
* severity
* diagnosis
* examination findings
* treatment
* notes

Keep the model extensible for additional dermatology fields later.
36. LASER HAIR REMOVAL
Laser Hair Removal is a Dermatology module/submodule.
Keep the initial workflow simple.
Each session should contain:

* treatment area
* session number
* date
* notes
* optional photos
* next appointment

Allow multiple treatment areas per session.
Preferred area-selection experience:

1. interactive 3D human body
2. usable fallback 2D body illustration if 3D is unavailable/unsupported

Support front/back body selection and multiple regions.
Do not add unnecessary technical laser parameters in the first version.
37. LASER HISTORY
Patient laser history should show previous sessions clearly.
Example:

```text
Session 1
✓ Legs
✓ Underarms

Session 2
✓ Legs
✓ Underarms
✓ Face

```

Photos are optional.
Notes are supported.
38. OPHTHALMOLOGY
Build a proper structured ophthalmology examination environment.
Include appropriate structured fields such as:

* visual acuity
* refraction
* IOP
* pupil examination
* eye movement
* slit-lamp examination
* fundus examination
* diagnosis
* treatment
* prescription
* notes

Keep the module extensible.
39. RADIOLOGY
Radiology gets a dedicated environment.
Support study types such as:

* X-Ray
* CT
* MRI
* Ultrasound
* Other

Each study should support:

* patient
* requested by
* exam type
* body/region
* date
* images
* report
* radiologist
* status

Workflow:

```text
Doctor
→ Radiology Request
→ Radiology
→ Study
→ Images
→ Report
→ Final Result

```

Other authorized departments can access the final radiology report according to the platform's sharing/access rules.
Radiology staff cannot browse unrelated specialty records.
40. LABORATORY
Build a dedicated Laboratory environment.
Support:

* test categories
* tests
* units
* reference ranges
* results
* abnormal flags
* lab reports

Lab tests must be managed by:

* Health Center Manager
* Laboratory/Department Manager

Superadmin must NOT manage individual laboratory tests/reference ranges.
Workflow:

```text
Doctor
→ Lab Request
→ Laboratory
→ Perform Test
→ Enter Results
→ Final Lab Report

```

Any authorized doctor can request lab tests.
Lab reports/results must be accessible to authorized staff across the health center.
Laboratory staff should not gain access to unrelated specialty medical histories simply because they work in Laboratory.
41. PHARMACY
Pharmacy is more than prescription viewing, but not a full standalone commercial pharmacy platform yet.
Support:

* prescription queue
* medication catalog
* inventory
* stock adjustments
* dispensing
* basic sales
* expiry tracking

Prescriptions should support:

* doctor
* patient
* date
* medications
* dose
* frequency
* duration
* instructions

42. SHARED PRESCRIPTION SYSTEM
Prescriptions are a shared general module across specialties.
Doctors from any supported medical department can create prescriptions.
Pharmacy can process them through:

```text
Pending
→ Dispensed

```

Record what was actually dispensed.
43. GENERIC MEDICAL DEPARTMENTS
Departments without a dedicated module use a generic medical environment.
Initial generic visit fields:

* chief complaint
* symptoms
* vitals
* examination
* diagnosis
* assessment
* treatment plan
* medications
* attachments
* notes

Keep the generic system extensible.
Custom departments use this same generic medical environment.
44. APPOINTMENTS — GLOBAL MODEL
Appointments are part of the shared platform but are scope-restricted by permissions.
The Health Center Manager can see all appointments.
Department Manager sees appointments in their department.
Doctor sees appointments related to their clinic.
Receptionist sees appointments within their assigned department/clinic scope.
Every listed role has the same general appointment actions:

* create
* edit
* cancel
* delete

subject to scope.
45. APPOINTMENT CREATION
Each appointment has its own explicit time.
Do not force a single global appointment duration.
Support start/end time or equivalent explicit time representation.
If an appointment is created by a doctor:

* doctor is automatically assigned
* clinic is automatically assigned

Do not require redundant manual selection.
46. APPOINTMENT FIELDS
Support:

* patient
* department
* clinic
* doctor
* location
* date
* start time
* end time/duration
* appointment type
* reason
* notes
* status
* created by
* recurring-series relationship where applicable

Clinic location is customizable text.
47. APPOINTMENT STATUSES
Use exactly:

* Scheduled
* Arrived
* In Progress
* Cancelled
* No Show
* Completed

48. DOUBLE-BOOKING PREVENTION
Prevent:

* doctor double-booking
* clinic double-booking

Do not depend only on frontend checks.
Enforce conflict detection on the backend/database.
Handle race conditions safely so simultaneous requests cannot create conflicting appointments.
49. RECURRING APPOINTMENTS
Support recurring appointments.
Support editing:

```text
Only this appointment

```

or:

```text
This appointment and all future appointments

```

Make recurring-series data structured so each generated appointment remains individually manageable.
50. WALK-INS
Receptionists and authorized staff must be able to register walk-in patients without a previous appointment.
Workflow:

```text
Patient arrives
→ Find/create patient
→ Select department/clinic
→ Assign doctor
→ Mark Arrived

```

51. BILLING ARCHITECTURE
Billing must support both:

1. health-center-wide overview
2. department/clinic-specific financial views

Every transaction should remain traceable to:

```text
Health Center
→ Department
→ Clinic
→ Doctor where applicable

```

This allows reports by:

* health center
* department
* clinic
* doctor

52. SERVICES AND PRICING
Services should support:

* name
* category
* cost
* selling price
* duration where relevant
* active/inactive
* customizable pricing

Support:

* regular pricing
* discounted pricing
* custom pricing

Use inherited defaults where appropriate.
53. DISCOUNTS
Anyone with billing permission can apply discounts.
Do not create a separate "manager only" discount restriction.
Permissions remain customizable.
54. PAYMENTS
Only track:

```text
Cash

```

Do not implement:

* Sham Cash
* card
* bank transfer
* payment gateways

The data model can remain extensible for future payment methods, but the UI for this version should use Cash only.
Support partial payments.
Example:

```text
Total: 500,000 SYP
Paid: 300,000 SYP
Remaining: 200,000 SYP

```

55. INVOICES / RECEIPTS
Generate printable invoices/receipts for appropriate:

* consultations
* treatments
* procedures
* lab tests
* radiology
* medicines
* products
* services

Each department may have its own document style while inheriting center branding.
56. PATIENT FINANCIAL HISTORY
Patient profiles should include financial history.
Do NOT automatically hide financial information from users merely because they are doctors or receptionists.
Use the normal permission system to control financial access.
Health Center Manager and Department Manager have full financial visibility within their scope.
57. INVENTORY
Every department can have inventory.
Examples:

* Dentistry
* Dermatology
* Laser
* Laboratory
* Pharmacy
* General center supplies

Inventory may be:

* clinic-specific
* department-level shared inventory
* transferable between clinics

Support stock transfers between clinics.
Support shared inventory pools.
58. INVENTORY FIELDS
Use:

* product
* category
* SKU/barcode
* quantity
* cost
* selling price
* low-stock threshold
* expiry date
* supplier
* stock movements

Keep this extensible.
59. BARCODE / QR SUPPORT
Support physical USB barcode/QR scanners on desktop.
Do NOT require phone-camera scanning.
USB scanners should work as standard keyboard-input scanners where possible.
No camera-scanning system is required.
60. INVENTORY REPORTING
Include:

* stock levels
* low stock
* expiry information
* stock movements
* transfers
* department inventory
* clinic inventory
* shared inventory

61. REPORTS
Provide date-range filtering.
Health Center Manager reports:

* patients
* appointments
* doctor activity
* clinic activity
* department activity
* revenue
* outstanding balances
* services/treatments
* inventory
* laboratory
* radiology

Department Managers get department-scoped versions.
Doctors/receptionists receive only reports permitted by their role.
62. EXPORTS
Support:

* Excel
* PDF

Users should select the appropriate data to export.
Do not add CSV unless genuinely needed later.
Exports must respect the same permission and tenant boundaries as the application.
63. PRINTING
Important views must have direct Print actions.
Examples:

* patient summary
* prescriptions
* invoices
* receipts
* laboratory reports
* radiology reports
* appointment schedules

64. PDF GENERATION
Prefer backend-generated PDFs for official documents so that formatting is consistent regardless of browser/device.
65. DOCUMENT TEMPLATES
Support templates for:

* prescriptions
* invoices
* receipts
* lab reports
* radiology reports
* visit summaries
* patient summaries
* appointment slips

Center branding should be inserted automatically.
66. BRANDING
Health Center Manager and Superadmin can control health-center branding.
Support:

* health-center name
* logo
* primary color
* secondary color
* login branding where appropriate
* document branding

Departments may have their own visual identity/environment while still following the parent platform's design system.
67. DESIGN SYSTEM
Create a professional parent-platform design system.
The parent platform should feel modern, reliable, clean, and suitable for a healthcare product.
Departments should have distinct working environments.
Dentistry should retain the AeroDent feel where useful.
Do not use a global light/dark mode switch.
Do not add user-specific dashboard layouts.
Do support:

* Arabic
* English
* RTL/LTR

Language preference is local to the user/device.
Store language preference locally rather than globally changing everyone else's UI.
68. TIME AND CURRENCY
Global timezone:

```text
Asia/Damascus

```

Do not make timezone configurable per health center.
Use month/day order for displayed dates and hour:minute time formatting, while including year when necessary.
Currency:

* health-center default currency
* inherited by departments/clinics
* keep the architecture extensible
* no requirement for multiple active currencies in one center for this version

69. FILE MANAGEMENT
Maximum individual file size:

```text
15 MB

```

Allowed:

* images
* PDF
* necessary/common document file types

Do NOT allow executable/script uploads.
Use MIME/type validation and extension validation.
Support:

* drag and drop
* file picker
* multiple uploads
* preview
* download
* rename
* delete
* share

For images/medical images:

* zoom
* rotate
* fullscreen
* basic annotation

70. FILE STORAGE QUOTA
Default storage quota:

```text
2 GB per health center

```

The Superadmin can expand a center's quota manually.
Track:

* used storage
* total quota
* remaining quota

Prevent uploads that exceed the quota.
71. FILE ACCESS RULES
Patient files must belong to the health center.
Normal files uploaded by a clinic are accessible only to that clinic unless explicitly shared.
Examples:

* X-rays
* Medical images
* Photos
* PDFs
* Documents

Sharing must allow the uploader/authorized manager to choose the destination scope.
Example:

```text
Share with:
☐ Dermatology
☐ Cardiology
☐ Specific clinic
☐ Specific doctor

```

Shares can be revoked.
Laboratory reports/results are the exception and are available to authorized staff across the health center.
72. DENTAL X-RAY FILES
Existing AeroDent X-ray/file behavior should be preserved where practical.
But all files must ultimately use the new platform-wide secure storage and permission architecture.
73. CONCURRENT EDITING
Safely handle two users editing the same record.
Do not silently overwrite changes.
Use appropriate concurrency controls such as:

* row versions
* optimistic locking
* transaction checks
* safe server-side conflict detection

For conflicting sensitive records, never silently discard one user's changes.
74. OFFLINE-FIRST BEHAVIOR
The application is online-first but must tolerate temporary internet loss.
When internet connection is unavailable:

1. user changes are saved locally
2. queued operations are stored locally
3. UI remains usable where possible
4. when connection returns, queued changes are uploaded automatically

Use browser storage such as IndexedDB for offline data/queues.
Use an idempotent synchronization model.
Every queued mutation must have a client-side unique operation ID so retries cannot accidentally duplicate records.
Synchronize safely after reconnect.
Do not lose user changes.
For conflicts, do not silently overwrite newer server data.
Use server-side versions/timestamps/transaction checks.
75. ONLINE/OFFLINE UX
Make connectivity state visible but unobtrusive:

```text
Online
Offline — changes saved locally
Syncing...
Synced
Sync issue — requires attention

```

Do not build an unnecessarily complex offline framework.
The goal is robust practical offline operation.
76. SIMPLE NOTIFICATIONS
Implement simple in-app operational notifications.
Examples:

* appointment created
* appointment cancelled
* patient arrived
* payment recorded
* low stock
* lab result available
* radiology result available
* permission changed

Do NOT build a large enterprise notification platform.
No email delivery.
No SMS.
Use simple UI notifications/toasts and lightweight notification state where useful.
77. WHATSAPP
Do NOT integrate the WhatsApp Business API.
For appointment reminders:
Generate a WhatsApp message/link that opens WhatsApp with a prepared message.
Example:

```text
Your appointment at Al-Shifa Medical Center is scheduled for:
October 5, 2026 at 14:30.

```

The user sends the message manually.
78. MANUAL BACKUPS
Backups are manual, not automatic.
Health Center Manager and Superadmin should have appropriate backup functionality.
Support backup of:

* PostgreSQL data
* uploaded files

Provide a practical restore procedure/documentation for recovering the application on another Linux server.
Do not implement an unnecessary automated cloud backup service.
79. ERROR LOGGING / MONITORING
Implement production logging for:

* Flask/server errors
* API errors
* database errors
* authentication failures
* background/sync errors

Do not place medical-record content or sensitive financial content into normal application logs.
Keep logs useful for debugging without becoming a privacy risk.
80. DATABASE DESIGN
Use a normalized relational model in PostgreSQL.
Suggested core entities include:

```text
users
roles
permissions
role_permissions
user_scopes

health_centers
plans
health_center_subscriptions
plan_limits

department_types
health_center_departments
clinics

patients
patient_department_links
patient_clinic_links

visits
medical_records
prescriptions
prescription_items

appointments
appointment_series

services
service_prices
invoices
invoice_items
payments

inventory_items
inventory_locations
inventory_stock
stock_movements
stock_transfers

files
file_shares

audit_logs
notifications

offline_sync_operations
deletion_buffer

document_templates
storage_usage

```

Add specialty-specific tables/models as necessary.
Do not force everything into one giant generic table.
At the same time, do not over-engineer every specialty before it needs specialized data.
81. TENANT OWNERSHIP IN DATABASE
Every tenant-scoped record must have a reliable relationship back to the Health Center.
Do not rely on indirect inference alone.
For sensitive tables, store the tenant relationship explicitly where useful for security and query performance.
Foreign keys and application policies must prevent cross-tenant relationships.
82. SPECIALTY DATA OWNERSHIP
Medical data must be associated with the relevant:

* health center
* department
* clinic
* patient
* visit

Doctor identity is historical metadata, not the primary ownership boundary.
Clinic controls normal doctor access.
83. GENERIC VS SPECIALIZED DATA
Use specialized models for:

* Dentistry
* Dermatology
* Laser Hair Removal
* Ophthalmology
* Radiology
* Laboratory

Generic medical records for:

* General Medicine
* Pediatrics
* Cardiology
* Neurology
* Nutrition
* future custom departments

Pharmacy has its own prescription/inventory/dispensing workflows.
84. DATABASE PERFORMANCE
Design for speed.
Use:

* correct indexes
* composite indexes for tenant + common filters
* indexed patient name/phone search
* pagination
* efficient joins
* no unnecessary N+1 queries
* server-side filtering
* bounded API responses

Do not load entire patient databases into the browser.
Do not perform expensive filtering only in frontend JavaScript.
85. API ARCHITECTURE
Use Flask as a backend API.
Prefer:

```text
/api/v1/...

```

Use:

* JSON request/response
* consistent status codes
* consistent error format
* Flask Blueprints/modules
* service/business layer
* data-access layer where helpful

Keep concerns separated:

```text
API
→ Authorization
→ Services
→ ORM/Data Layer
→ PostgreSQL

```

Do not put complicated business logic directly inside route handlers.
86. AUTHORIZATION ARCHITECTURE
Every protected endpoint must independently enforce authorization.
Example:

```text
GET /api/v1/patients/123

```

must verify:

* current user is authenticated
* patient belongs to the current health center
* patient is within the user's department/clinic scope
* the user has patient-view permission

Do NOT trust that the frontend hid the patient.
Repeat the same principle for:

* records
* files
* billing
* inventory
* appointments
* staff
* reports
* settings

87. FILE SECURITY
Uploaded files must never be exposed using unrestricted predictable file URLs.
Use authenticated download/view endpoints.
Check permissions before serving any file.
Do not rely on filename secrecy.
Generate safe storage names.
Prevent path traversal.
Prevent executable uploads.
Do not trust client MIME types.
88. DATA VALIDATION
Validate on backend.
Examples:

* usernames
* emails
* IDs
* dates
* financial values
* appointment times
* stock quantities
* uploaded files
* plan limits

Handle malformed input cleanly.
Use PostgreSQL constraints where appropriate.
89. SECURITY TESTING
Create tests for:
Tenant isolation
User from Center A attempts to access Center B data → rejected.
Clinic isolation
Doctor from Clinic A attempts to access Clinic B → rejected.
Department isolation
Dermatology user attempts to access Dentistry data → rejected.
Receptionist scope
Receptionist assigned only to Clinic A cannot access Clinic B.
Department-level receptionist can access all clinics in that department.
Superadmin
Superadmin can access platform-wide management.
Manager scope
Department Manager cannot access another department.
Sessions
New login invalidates old session.
Files
Unauthorized file access rejected.
Appointments
Concurrent booking cannot create a doctor/clinic conflict.
Offline sync
Retrying the same operation does not duplicate data.
90. FRONTEND ARCHITECTURE
Use clean modular Vanilla JavaScript.
Example:

```text
/js
  /core
  /auth
  /api
  /permissions
  /patients
  /appointments
  /billing
  /inventory
  /files
  /reports
  /departments
  /dentistry
  /dermatology
  /ophthalmology
  /radiology
  /laboratory
  /pharmacy
  /offline

```

Use reusable UI primitives/components in Vanilla JS rather than duplicating large chunks of HTML.
91. RESPONSIVENESS
The application must be responsive on:

* desktop
* laptop
* tablet
* phone

Major workflows must remain usable on mobile.
92. HEALTH CENTER SETTINGS
Health Center Manager can manage:

* center name
* logo
* branding
* default currency
* departments
* clinics
* staff
* services
* appointment settings
* storage information
* permissions as permitted
* document templates
* other center-wide settings

93. CLINIC SETTINGS
Each clinic can manage:

* name
* location text
* phone
* email
* logo if applicable
* working hours
* staff assignments
* services
* prices
* appointment settings
* inventory scope

94. DEPARTMENT SETTINGS
Each department can have:

* name
* branding identity
* clinics
* head doctor
* services
* appointment behavior
* department inventory
* department-specific configuration

Clinic-level settings may override department defaults where appropriate.
95. DEPARTMENT MANAGEMENT
The Health Center Manager cannot invent a new specialty type.
The manager can manage departments that were activated by Superadmin, including their operational settings and clinics.
Superadmin controls the available module types.
96. USER PREFERENCES
Local user/device preferences:

* Arabic/English
* RTL/LTR
* other practical personal UI preferences

Do NOT implement:

* light/dark mode
* customizable dashboard layouts

97. NO PATIENT PORTAL
There is no patient account or patient-facing portal in this version.
The system is staff-only.
98. NO AUTO-PAYMENT SUBSCRIPTIONS
Do not build:

* Stripe
* online subscription checkout
* automatic plan billing
* payment gateways

Plans are controlled manually by Superadmin.
99. NO EMAIL SYSTEM
Do not build email sending.
Internal account email is only a unique login identifier.
100. ACCOUNT STATES
Staff accounts should support:

```text
Active
Archived

```

When a staff member leaves:

* archive the account
* preserve historical references
* do not destroy historical record authorship
* do not allow archived users to log in

101. DATA HISTORY
Historical records must remain internally coherent.
Changing:

* doctor name
* username
* email
* clinic assignment

must not rewrite past medical events.
Past records must preserve the historical creator information at time of creation.
New events use the current user/account identity.
102. DELETION / UNDO IMPLEMENTATION
For entities supporting delete:

```text
User clicks Delete
↓
Server securely stages deletion
↓
30-second Undo window
↓
Permanent deletion

```

The deletion/undo mechanism must be server-controlled.
Do not trust a JavaScript timer alone.
If the browser closes during the 30-second window, the server remains authoritative.
103. PATIENT FILE / IMAGE VIEWER
Medical image viewers should support:

* zoom
* rotate
* fullscreen
* basic annotation

Do not add unnecessary advanced DICOM functionality unless required.
Radiology should remain practical and expandable.
104. LAB REPORT ACCESS
Lab report/result visibility is broader than normal uploaded files.
A finalized laboratory result/report should be accessible to authorized staff throughout the health center.
The staff member still should not gain access to unrelated Laboratory workflow/admin capabilities merely by opening a result.
105. REPORTING SCOPE
All reports must be scope-aware.
Examples:

```text
Health Center Manager
→ complete center report

Dentistry Manager
→ Dentistry report

Dental Doctor
→ only permitted dental/clinic information

Receptionist
→ only permitted operational/financial information

```

Never let report endpoints bypass the normal permission system.
106. PRODUCTION CONFIGURATION
Prepare for:

```text
Internet
   ↓
Nginx
   ↓
Gunicorn
   ↓
Flask
   ↓
PostgreSQL
   +
Secure File Storage

```

Use:

* environment variables
* production configuration
* HTTPS support
* secure headers
* proper CORS behavior only if needed
* database connection pooling
* sane timeouts
* logging
* graceful error handling

107. DATABASE SCHEMA MANAGEMENT
Do not introduce Flask-Migrate/Alembic as a mandatory requirement for this project.
Build the initial schema cleanly and keep the schema organized so future migrations can be introduced later if the project grows.
Do not destroy the existing development database during normal application startup.
108. INITIAL SUPERADMIN
Provide a secure bootstrap mechanism for the first Superadmin rather than hard-coding credentials.
Use environment configuration or a controlled CLI/bootstrap command.
Never commit passwords into source code.
109. TESTING REQUIREMENTS
Before considering the project complete, verify:

* login works
* single-session enforcement works
* all roles work
* permissions work
* department isolation works
* clinic isolation works
* tenant isolation works
* patient creation/search works
* patient cross-department model works
* visits work
* appointments work
* recurring appointments work
* conflict prevention works
* billing works
* partial payments work
* inventory works
* transfers/shared inventory work
* barcode/QR USB input works
* file uploads work
* file sharing works
* file quotas work
* reports work
* Excel export works
* PDF generation works
* printing works
* WhatsApp link generation works
* offline save works
* synchronization works
* conflict handling works
* delete + 30-second undo works
* Superadmin portal works
* branding works
* Arabic/English works
* RTL/LTR works
* responsive layout works

110. CODE QUALITY RULES
Do not create fake/demo functionality that looks finished but is not connected to the backend.
Every visible feature should have a real implementation or be clearly marked as intentionally unavailable.
Do not use hard-coded mock medical/business data as the actual source of truth.
Do not duplicate business rules between frontend and backend unnecessarily.
Do not trust client-provided IDs for authorization.
Do not use giant monolithic route files.
Do not place secrets in frontend code.
Do not expose PostgreSQL directly to the browser.
Do not use localStorage as the authoritative medical database.
Use IndexedDB only for offline caching/queued changes.
Do not silently swallow exceptions.
Return useful user-facing errors while keeping detailed sensitive stack traces out of production responses.
111. UX RULES
Keep the interface simple enough for doctors and receptionists.
Avoid unnecessary complexity.
Prefer:

* clear buttons
* readable tables
* obvious patient actions
* fast search
* minimal clicks
* consistent forms
* clear statuses
* visual department cards
* scope-aware navigation

Do not make users understand the database architecture.
112. TOKEN / AGENT EFFICIENCY
Because this project is being developed with multiple Claude Code agents:

* do not dump entire files into context unnecessarily
* inspect only relevant files before editing
* use targeted searches
* keep shared architectural notes concise
* avoid repeating this entire specification in agent-to-agent communication
* use reusable helper modules instead of duplicated logic
* prefer shared utilities for authorization, API responses, validation, files, and errors
* delegate independent tasks in parallel
* do not have multiple agents edit the same foundational file simultaneously
* after each major integration, run focused tests before continuing
* only run full test suites when integration points justify it
* reuse existing working AeroDent code where it reduces risk and implementation time

113. WORKING PRINCIPLE
Do not rebuild everything blindly.
First understand the existing behavior.
Then redesign the architecture around the new platform requirements.
Preserve valuable existing Dentistry functionality.
Refactor where necessary.
Replace architecture where necessary.
Do not preserve technical debt just because the feature already exists.
The final result should feel like one coherent professional platform, not several unrelated applications glued together.
114. FINAL ACCEPTANCE CRITERIA
The implementation is considered successful only when all of the following are true:
Platform

```text
One central URL
→ Login
→ role-based portal

```

Health center

```text
Health Center
→ Departments
→ Clinics
→ Staff

```

Security

```text
Health Center A
≠
Health Center B

```

No cross-tenant data leakage.
Access

```text
Health Center Manager
→ everything in center

Department Manager
→ everything in department

Doctor
→ current clinic only

Receptionist
→ assigned departments/clinics

```

Medical records

```text
One patient identity
+
department/clinic-specific medical history

```

Dentistry
Existing AeroDent dentistry functionality remains usable inside Dentistry.
Specialty modules
Dedicated environments exist for:

* Dentistry
* Dermatology
* Laser Hair Removal
* Ophthalmology
* Radiology
* Laboratory

Generic environment exists for other specialties/custom departments.
Business
Billing, partial cash payments, invoices, inventory, shared inventory, transfers, and reporting work.
Files
15 MB per file.
2 GB default per health center.
Secure access and explicit sharing.
Offline
Temporary offline edits are not lost and synchronize safely after reconnect.
Production
The application runs correctly on Linux with:

```text
Nginx
Gunicorn
Flask
PostgreSQL
Secure file storage

```

Quality
The application must be genuinely functional, not merely visually complete.
115. START NOW
Begin by inspecting the existing codebase and architecture.
Do not ask me to restate the requirements contained in this document.
Do not invent conflicting requirements.
When a small implementation detail is unspecified, choose the safest and simplest architecture consistent with this specification.
Before changing foundational architecture, identify the affected modules and coordinate the appropriate agents.
Use the available Claude Code skills where helpful.
Keep implementation practical.
Prioritize:

1. correctness
2. security
3. data isolation
4. working functionality
5. maintainability
6. performance
7. visual polish

Do not stop at scaffolding.
Continue through implementation, integration, testing, bug fixing, and production-readiness checks until the resulting project is actually working.


this is the original Aerodent-online repository, I don't want you to push anything to it, just pull it if needed
https://github.com/frbhusen/AeroDent-Online