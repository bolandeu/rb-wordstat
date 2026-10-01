"""Alembic environment: migrations run on the connection core/db.py hands over.

No alembic.ini and no logging setup — the CLI owns both. Only this tool's
objects exist for Alembic: names outside `<tool>_` (other tools' tables,
Directus) are never reflected, compared or touched.
"""

from alembic import context

# Handed over by core/db.py's alembic_config() — Alembic loads this file by path,
# outside the package, so it can't import from it.
attributes = context.config.attributes
prefix = attributes["prefix"]


def _own(name: str | None, type_: str, *_args) -> bool:
    return type_ != "table" or (name or "").startswith(prefix)


context.configure(
    connection=attributes["connection"],
    target_metadata=attributes["metadata"],
    version_table=attributes["version_table"],
    include_name=_own,
    render_as_batch=True,  # SQLite can't ALTER most things; batch mode rebuilds the table
)
with context.begin_transaction():
    context.run_migrations()
