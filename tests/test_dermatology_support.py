"""Shared helpers for the dermatology / laser / ophthalmology tests (no tests here)."""
import io
import random

from sqlalchemy import select, update

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82")


def make_patient(app, center, name="Ali Hassan"):
    """Create a patient directly (center-level identity, not yet linked to any clinic)."""
    from backend.app.core import tenancy
    from backend.app.extensions import db
    from backend.app.models import Patient
    with app.app_context(), tenancy.scoped("platform"):
        pt = Patient(health_center_id=center["center_id"], code=random.randint(100000, 2_000_000_000),
                     full_name=name, search_name=name.lower())
        db.session.add(pt)
        db.session.commit()
        return pt.id


def png_upload(name="lesion.png"):
    return {"files": (io.BytesIO(PNG), name)}


def upload(client, url, data):
    return client.c.post(url, data=data, content_type="multipart/form-data", headers=client._h(None))


def expire_and_purge(app, token):
    """Force the undo window of `token` to end and run the purger (as the background thread would)."""
    from backend.app.core import tenancy
    from backend.app.core.timeutil import utcnow
    from backend.app.extensions import db
    from backend.app.models import DeletionStage
    from backend.app.services import deletion
    with app.app_context():
        with tenancy.scoped("platform"):
            db.session.execute(update(DeletionStage).where(DeletionStage.token == token)
                               .values(expires_at=utcnow()))
            db.session.commit()
        deletion.purge_expired()
        db.session.remove()


def platform_rows(app, stmt):
    from backend.app.core import tenancy
    from backend.app.extensions import db
    with app.app_context(), tenancy.scoped("platform"):
        rows = db.session.execute(stmt).all()
        db.session.rollback()
        return rows


def principal_for(app, user_id):
    """Build a principal for direct service checks (must be used inside an app context)."""
    from backend.app.authz.principal import build_principal
    from backend.app.extensions import db
    from backend.app.models import User
    u = db.session.execute(select(User).where(User.id == user_id)).scalar_one()
    return build_principal(u)
