"""Guard against the fresh-init Postgres DDL regression.

`bootstrap.py` initialises a fresh database with `Base.metadata.create_all()`.
Boolean columns that carry an *integer* ``server_default`` (``text("0"|"1")``)
render as ``BOOLEAN DEFAULT 0`` — valid on SQLite, rejected by PostgreSQL
(``DatatypeMismatch``). The test suite runs on SQLite, so this slipped through
once already; compiling the DDL with the PostgreSQL dialect catches it without
needing a live Postgres.
"""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.role import Role
from app.models.user import User


def _postgres_ddl(model) -> str:
    return str(CreateTable(model.__table__).compile(dialect=postgresql.dialect())).lower()


def test_role_boolean_defaults_render_for_postgres():
    ddl = _postgres_ddl(Role)
    # The regression: an integer literal default on a BOOLEAN column.
    assert "boolean default 0" not in ddl
    assert "boolean default 1" not in ddl
    # The fix: proper SQL boolean literals.
    assert "default false" in ddl
    assert "default true" in ddl


def test_user_boolean_defaults_render_for_postgres():
    ddl = _postgres_ddl(User)
    assert "boolean default 0" not in ddl
    assert "boolean default 1" not in ddl
    assert "default false" in ddl
    assert "default true" in ddl
