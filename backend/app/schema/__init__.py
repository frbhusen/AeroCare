"""Schema management without Alembic (spec §107).

`flask --app backend.wsgi db init-schema` (run as the schema-owner role) is idempotent:
  1. CREATE EXTENSION pg_trgm / btree_gist (trusted extensions)
  2. metadata.create_all()  -- creates missing tables only; never drops or alters data
  3. applies RLS policies to every table with a health_center_id column (+ special tables)
  4. applies module SQL (exclusion constraints, trigram indexes, triggers)
  5. grants DML to the runtime role (default hc_app) and makes audit_logs append-only

Schema changes to existing tables must be written as additive, idempotent SQL in
`MODULE_SQL`-style blocks (ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...) until a migration tool
is adopted. Never drop the development database on startup.
"""
from sqlalchemy import create_engine, text

from backend.app.extensions import db

EXTRA_SQL = []  # (name, sql) registered by modules via register_sql()

TENANT_EXPR = ("(current_setting('app.mode', true) = 'platform' OR "
               "(current_setting('app.mode', true) = 'tenant' AND {col} = "
               "nullif(current_setting('app.center_id', true), '')::int))")

SPECIAL_TABLES = {"users", "audit_logs", "health_centers"}

CORE_SQL = """
CREATE INDEX IF NOT EXISTS ix_patients_search_name_trgm ON patients USING gin (search_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_patients_phone_trgm ON patients USING gin (phone_digits gin_trgm_ops);

CREATE OR REPLACE FUNCTION hc_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_logs is append-only'; END $$;
DROP TRIGGER IF EXISTS trg_audit_immutable ON audit_logs;
CREATE TRIGGER trg_audit_immutable BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION hc_audit_immutable();
"""


def register_sql(name, sql):
    EXTRA_SQL.append((name, sql))


def _policy_sql(table, col="health_center_id", extra=None, check=None):
    using = TENANT_EXPR.format(col=col)
    if extra:
        using = f"({using} OR {extra})"
    check = check or using
    return (f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;\n'
            f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;\n'
            f'DROP POLICY IF EXISTS hc_tenant ON "{table}";\n'
            f'CREATE POLICY hc_tenant ON "{table}" USING ({using}) WITH CHECK ({check});\n')


def rls_sql(metadata):
    out = []
    for table in metadata.sorted_tables:
        if table.name in SPECIAL_TABLES or "health_center_id" not in table.c:
            continue
        out.append(_policy_sql(table.name))
    auth = "current_setting('app.mode', true) = 'auth'"
    out.append(_policy_sql("users", extra=auth))
    out.append(_policy_sql("health_centers", col="id", extra=auth))
    # audit_logs: readable per tenant; inserts also allowed during login (auth mode, center may be NULL).
    # SELECT must include auth mode too because INSERT ... RETURNING re-reads the new row.
    tenant = TENANT_EXPR.format(col="health_center_id")
    out.append('ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;\nALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;\n'
               'DROP POLICY IF EXISTS hc_tenant ON audit_logs;\nDROP POLICY IF EXISTS hc_audit_insert ON audit_logs;\n'
               f'CREATE POLICY hc_tenant ON audit_logs FOR SELECT USING ({tenant} OR {auth});\n'
               f'CREATE POLICY hc_audit_insert ON audit_logs FOR INSERT WITH CHECK ({tenant} OR {auth});\n')
    return "\n".join(out)


def init_schema(app, schema_url=None, runtime_role=None, echo=print):
    from backend.app.modules import load_all
    load_all()
    url = schema_url or app.config["SCHEMA_DATABASE_URL"]
    if not url:
        raise RuntimeError("SCHEMA_DATABASE_URL is not set")
    runtime_role = runtime_role or _runtime_role(app.config["SQLALCHEMY_DATABASE_URI"])
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    db.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(CORE_SQL))
        for name, sql in EXTRA_SQL:
            echo(f"  module sql: {name}")
            conn.execute(text(sql))
        conn.execute(text(rls_sql(db.metadata)))
        if runtime_role:
            conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{runtime_role}";'
                              f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{runtime_role}";'
                              f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{runtime_role}";'
                              f'REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM "{runtime_role}";'))
    engine.dispose()
    echo("schema ready")


def _runtime_role(url):
    from sqlalchemy.engine import make_url
    try:
        return make_url(url).username
    except Exception:
        return None
