from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# Deterministic constraint names keep future migrations (Alembic, if ever adopted) sane.
naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# expire_on_commit=False: request code commits in several steps (auth context, then tenant
# context); objects loaded earlier must stay usable without re-reading under another RLS mode.
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention),
                session_options={"expire_on_commit": False})
