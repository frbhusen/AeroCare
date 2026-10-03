"""Permission catalog and role defaults. Authoritative description: docs/PERMISSIONS.md.

Effective permissions for a user = role defaults (this file)
                                   ± center overrides (role_permissions table)
                                   ± per-user overrides (user_permissions table).
Superadmin is not governed by this table (platform portal); inside a center it gets read-only
access to medical data and never edits medical history.

To add a permission: add it to CATALOG (and role defaults) and document it in PERMISSIONS.md.
"""

CATALOG = {
    # patients
    "patients.view": "View patients in scope",
    "patients.create": "Register patients",
    "patients.edit": "Edit patient general information",
    "patients.delete": "Delete patient profiles without significant history",
    "patients.delete_with_history": "Delete patients that have medical history",
    # appointments
    "appointments.view": "View appointments",
    "appointments.create": "Create appointments / walk-ins",
    "appointments.edit": "Edit, reschedule, change status",
    "appointments.delete": "Delete appointments",
    # medical records (visits + specialty records + prescriptions + files attached to them)
    "medical_records.view": "View medical records in scope",
    "medical_records.create": "Create medical records",
    "medical_records.edit": "Edit medical records",
    "medical_records.delete": "Delete medical records",
    # billing
    "billing.view": "View invoices, payments, financial history",
    "billing.create": "Create invoices / record payments",
    "billing.edit": "Edit invoices, apply discounts",
    "billing.delete": "Delete invoices / payments",
    "services.manage": "Manage services and prices",
    # inventory
    "inventory.view": "View inventory",
    "inventory.edit": "Receive/adjust/transfer stock, manage items",
    "inventory.delete": "Delete inventory items",
    # pharmacy
    "pharmacy.dispense": "Dispense prescriptions and record sales",
    # laboratory / radiology workflows
    "lab.request": "Request lab tests",
    "lab.process": "Perform tests and enter results (laboratory staff)",
    "lab.manage_tests": "Manage lab test catalog and reference ranges",
    "radiology.request": "Request radiology studies",
    "radiology.process": "Perform studies, upload images, write reports",
    # files
    "files.view": "View files in scope",
    "files.upload": "Upload files",
    "files.edit": "Rename / annotate files",
    "files.delete": "Delete files",
    "files.share": "Share files with other departments/clinics/doctors",
    # staff / settings / reports
    "staff.view": "View staff",
    "staff.create": "Create staff accounts",
    "staff.edit": "Edit staff accounts and assignments",
    "staff.delete": "Archive/delete staff accounts",
    "settings.view": "View settings",
    "settings.edit": "Edit settings (center/department/clinic as scoped)",
    "permissions.manage": "Customize role and user permissions",
    "reports.view": "View reports",
    "reports.export": "Export reports (Excel/PDF)",
    "audit.view": "View audit logs in scope",
    "backup.create": "Create center data backups",
}

ALL = set(CATALOG)

_MEDICAL_VIEW = {"medical_records.view", "files.view"}
_MEDICAL_WRITE = {"medical_records.create", "medical_records.edit", "medical_records.delete",
                  "files.upload", "files.edit", "files.delete", "files.share"}
_APPTS = {"appointments.view", "appointments.create", "appointments.edit", "appointments.delete"}

ROLE_DEFAULTS = {
    "center_manager": set(ALL),
    "department_manager": ALL - {"backup.create"},
    "doctor": (
        {"patients.view", "patients.create", "patients.edit", "patients.delete"}
        | _APPTS | _MEDICAL_VIEW | _MEDICAL_WRITE
        | {"billing.view", "billing.create", "billing.edit",
           "inventory.view", "inventory.edit",
           "lab.request", "radiology.request", "lab.process", "radiology.process",
           "pharmacy.dispense", "reports.view", "staff.view", "settings.view"}
    ),
    "receptionist": (
        {"patients.view", "patients.create", "patients.edit", "patients.delete"}
        | _APPTS | {"medical_records.view", "files.view", "files.upload"}
        | {"billing.view", "billing.create", "billing.edit", "inventory.view", "inventory.edit",
           "pharmacy.dispense", "reports.view", "lab.request", "radiology.request"}
    ),
}

# Permissions that never apply to a role regardless of overrides (structural limits).
ROLE_FORBIDDEN = {
    "receptionist": {"permissions.manage", "audit.view", "backup.create", "lab.manage_tests"},
    "doctor": {"permissions.manage", "audit.view", "backup.create"},
    "department_manager": {"backup.create"},
}
