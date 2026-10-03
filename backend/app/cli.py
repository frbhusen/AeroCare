"""CLI commands:  flask --app backend.wsgi <group> <command>

  db init-schema            create/upgrade schema (idempotent), RLS, grants, catalog seed
  admin create-superadmin   bootstrap the first Superadmin (password prompted or $HC_SUPERADMIN_PASSWORD)
  ops purge-deletions       hard-delete expired staged deletions now
  ops storage-gc            remove stored bytes with no files row (after crashes)
  backup create             full PostgreSQL dump + uploaded files archive (see docs/OPERATIONS.md)
  dev seed-demo             demo center with every role (development only)
"""
import os

import click
from flask.cli import AppGroup
from sqlalchemy import select

from .core import tenancy
from .extensions import db

db_cli = AppGroup("db", help="Schema management")
admin_cli = AppGroup("admin", help="Platform administration")
ops_cli = AppGroup("ops", help="Operations")
backup_cli = AppGroup("backup", help="Manual backups")
dev_cli = AppGroup("dev", help="Development helpers")

PLANS = [
    # code, name, departments, head doctors, doctors, receptionists, clinics
    ("basic", "Basic", 1, 1, 3, 1, 3),
    ("professional", "Professional", 3, 3, 6, 3, 6),
    ("enterprise", "Enterprise", None, None, None, None, None),
]

DEPARTMENT_TYPES = [
    # code, en, ar, environment, icon, color
    ("dentistry", "Dentistry", "طب الأسنان", "dentistry", "tooth", "#0e7490"),
    ("general_medicine", "General Medicine", "الطب العام", "generic", "stethoscope", "#2563eb"),
    ("dermatology", "Dermatology", "الجلدية", "dermatology", "sparkles", "#c026d3"),
    ("pediatrics", "Pediatrics", "طب الأطفال", "generic", "baby", "#f59e0b"),
    ("cardiology", "Cardiology", "القلبية", "generic", "heart", "#dc2626"),
    ("ophthalmology", "Ophthalmology", "العينية", "ophthalmology", "eye", "#0891b2"),
    ("neurology", "Neurology", "العصبية", "generic", "brain", "#7c3aed"),
    ("nutrition", "Nutrition", "التغذية", "generic", "apple", "#16a34a"),
    ("laboratory", "Laboratory", "المخبر", "laboratory", "flask", "#ea580c"),
    ("pharmacy", "Pharmacy", "الصيدلية", "pharmacy", "pill", "#059669"),
    ("radiology", "Radiology", "الأشعة", "radiology", "scan", "#475569"),
]


def seed_catalog():
    from .models import DepartmentType, Plan
    with tenancy.scoped("platform"):
        for i, (code, name, d, h, doc, r, c) in enumerate(PLANS):
            if not db.session.execute(select(Plan).where(Plan.code == code)).scalar_one_or_none():
                db.session.add(Plan(code=code, name=name, max_departments=d, max_head_doctors=h, max_doctors=doc,
                                    max_receptionists=r, max_clinics=c, storage_quota_bytes=2 * 1024 ** 3))
        for i, (code, en, ar, env, icon, color) in enumerate(DEPARTMENT_TYPES):
            if not db.session.execute(select(DepartmentType).where(DepartmentType.code == code)).scalar_one_or_none():
                db.session.add(DepartmentType(code=code, name_en=en, name_ar=ar, environment=env, icon=icon,
                                              color=color, sort_order=i * 10))
        db.session.commit()


@db_cli.command("init-schema")
def init_schema_cmd():
    from flask import current_app
    from .schema import init_schema
    init_schema(current_app, echo=click.echo)
    seed_catalog()
    click.echo("catalog seeded")


@admin_cli.command("create-superadmin")
@click.option("--username", required=True)
@click.option("--name", required=True)
@click.option("--email", default=None, help="Defaults to the generated {username}_{id}@aerodent.com")
def create_superadmin(username, name, email):
    from .services.accounts import create_user_record
    password = os.environ.get("HC_SUPERADMIN_PASSWORD") or click.prompt("Password", hide_input=True,
                                                                          confirmation_prompt=True)
    with tenancy.scoped("platform"):
        u = create_user_record(center_id=None, username=username, name=name, role="superadmin", password=password,
                               email=email)
        db.session.commit()
        click.echo(f"superadmin created: id={u.id} email={u.email}")


@ops_cli.command("purge-deletions")
def purge_cmd():
    from .services.deletion import purge_expired
    click.echo(f"purged {purge_expired(limit=10000)}")


@ops_cli.command("storage-gc")
@click.option("--dry-run", is_flag=True)
def storage_gc(dry_run):
    from pathlib import Path
    from flask import current_app
    from .models import StoredFile
    root = Path(current_app.config["STORAGE_ROOT"]).resolve()
    with tenancy.scoped("platform"):
        keys = set(db.session.execute(select(StoredFile.storage_key)).scalars())
    removed = 0
    for p in root.rglob("*"):
        if p.is_file():
            key = p.relative_to(root).as_posix()
            if key not in keys:
                removed += 1
                if not dry_run:
                    p.unlink()
    click.echo(f"{'would remove' if dry_run else 'removed'} {removed} orphaned files")


@backup_cli.command("create")
def backup_create():
    from flask import current_app
    from .services.backup import create_full_backup
    path = create_full_backup(current_app)
    click.echo(f"backup written: {path}")


@dev_cli.command("seed-demo")
@click.option("--password", default=None, help="Password for all demo accounts (prompted if omitted)")
def seed_demo(password):
    from flask import current_app
    if current_app.config["ENV_NAME"] == "production":
        raise click.ClickException("seed-demo is disabled in production")
    from .services.demo import seed_demo_center
    password = password or click.prompt("Demo password", hide_input=True)
    info = seed_demo_center(password)
    for line in info:
        click.echo(line)


def register_cli(app):
    for g in (db_cli, admin_cli, ops_cli, backup_cli, dev_cli):
        app.cli.add_command(g)
