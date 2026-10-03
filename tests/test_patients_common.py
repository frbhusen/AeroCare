"""Shared helpers for the patients / visits / generic / prescriptions / files tests (no tests here)."""
import io

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 200
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def mk_patient(client, clinic_id, name="Ali Ahmad", expect=201, **kw):
    body = {"full_name": name, "clinic_id": clinic_id, **kw}
    r = client.post("/api/v1/patients", json=body)
    assert r.status_code == expect, r.get_json()
    return r.get_json()


def mk_visit(client, patient_id, clinic_id, expect=201, **kw):
    r = client.post("/api/v1/visits", json={"patient_id": patient_id, "clinic_id": clinic_id, **kw})
    assert r.status_code == expect, r.get_json()
    return r.get_json()


def upload(client, patient_id, clinic_id, files=None, expect=201, **form):
    files = files or [(PNG, "scan.png")]
    data = {"patient_id": str(patient_id), "clinic_id": str(clinic_id), **{k: str(v) for k, v in form.items()}}
    data["files"] = [(io.BytesIO(b), n) for b, n in files]
    r = client.post("/api/v1/files", data=data, content_type="multipart/form-data")
    assert r.status_code == expect, r.get_json()
    return r.get_json()


def undo(client, token):
    return client.post("/api/v1/undo", json={"undo_token": token})


def expire_and_purge(app):
    """Force every staged deletion past its window and run the purger (platform mode)."""
    from sqlalchemy import update
    from backend.app.core import tenancy
    from backend.app.core.timeutil import utcnow
    from backend.app.extensions import db
    from backend.app.models import DeletionStage
    from backend.app.services.deletion import purge_expired
    with app.app_context():
        with tenancy.scoped("platform"):
            db.session.execute(update(DeletionStage).values(expires_at=utcnow()))
            db.session.commit()
        n = purge_expired()
        db.session.remove()
    return n


def platform_exec(app, fn):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    with app.app_context():
        with tenancy.scoped("platform"):
            out = fn(db)
            db.session.commit()
        db.session.remove()
    return out
