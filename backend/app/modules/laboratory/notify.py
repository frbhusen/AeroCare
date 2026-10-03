"""Operational notifications for laboratory and radiology (no clinical content)."""
from backend.app.services.notifications import notify, recipients_for


def service_recipients(center_id, department_id, clinic_id, clinic_ids):
    targets = set()
    for c in ([clinic_id] if clinic_id else clinic_ids):
        targets |= recipients_for(center_id, clinic_id=c, department_id=department_id)
    if not targets:
        targets |= recipients_for(center_id, department_id=department_id)
    return targets


def lab_request(p, r, lab_clinics):
    users = service_recipients(p.center_id, r.lab_department_id, r.lab_clinic_id, lab_clinics)
    title = "Urgent lab request" if r.priority == "urgent" else "New lab request"
    notify(p.center_id, "lab_request", title, f"Lab request #{r.id}", f"#/laboratory/requests/{r.id}",
           user_ids=users, exclude_user_id=p.user.id)


def lab_result(p, r):
    users = recipients_for(p.center_id, clinic_id=r.requesting_clinic_id, department_id=r.requesting_department_id)
    if r.author_user_id:
        users.add(r.author_user_id)
    notify(p.center_id, "lab_result_available", "Lab result available", f"Lab request #{r.id}",
           f"#/laboratory/requests/{r.id}", user_ids=users, exclude_user_id=p.user.id)


def radiology_request(p, s, clinics):
    users = service_recipients(p.center_id, s.radiology_department_id, s.radiology_clinic_id, clinics)
    title = "Urgent radiology request" if s.priority == "urgent" else "New radiology request"
    notify(p.center_id, "radiology_request", title, f"Radiology study #{s.id}", f"#/radiology/studies/{s.id}",
           user_ids=users, exclude_user_id=p.user.id)


def radiology_result(p, s):
    users = recipients_for(p.center_id, clinic_id=s.requesting_clinic_id, department_id=s.requesting_department_id)
    if s.author_user_id:
        users.add(s.author_user_id)
    notify(p.center_id, "radiology_result_available", "Radiology report available", f"Radiology study #{s.id}",
           f"#/radiology/studies/{s.id}", user_ids=users, exclude_user_id=p.user.id)
