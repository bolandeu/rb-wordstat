"""Alembic environment: migrations run on the connection core/db.py hands over.

No alembic.ini and no logging setup — the CLI owns both. Only this tool's
objects exist for Alembic: names outside `<tool>_` (other tools' tables,
Directus) are never reflected, compared or touched. On PostgreSQL that is public
plus schema `cache` (this tool's cache tables); SQLite has no schemas.
"""

from alembic import context

# Handed over by core/db.py's alembic_config() — Alembic loads this file by path,
# outside the package, so it can't import from it.
attributes = context.config.attributes
prefix = attributes["prefix"]
connection = attributes["connection"]
postgres = connection.dialect.name == "postgresql"


def _own(name: str | None, type_: str, *_args) -> bool:
    if type_ == "schema":
        return name in (None, "public", attributes["cache_schema"])
    return type_ != "table" or (name or "").startswith(prefix)


context.configure(
    connection=connection,
    target_metadata=attributes["metadata"],
    version_table=attributes["version_table"],
    include_name=_own,
    include_schemas=postgres,
    render_as_batch=True,  # SQLite can't ALTER most things; batch mode rebuilds the table
)
with context.begin_transaction():
    context.run_migrations()
