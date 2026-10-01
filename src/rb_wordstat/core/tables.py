"""This tool's tables, as SQLAlchemy Core — mirrors the latest migration (`migrations/versions/`).

Every name starts with `PREFIX` (`<tool>_`): the shared PostgreSQL holds every
tool's tables (and Directus') in one `public` schema. Change a table here *and* add
a migration by hand (copy the example in `migrations/versions/`) — tests/test_db.py
fails when the migrated schema and this metadata disagree.

`info={"push": {...}}` marks an append-only table for `<cli> db push` (local SQLite →
production PostgreSQL): rows are inserted without their ids and skipped when one
with the same natural key exists, so the table needs a unique constraint on that key
and no foreign keys (link by natural keys). `since` names the timestamp column that
`--since` filters on.
"""

from __future__ import annotations

import sqlalchemy as sa

from .._distribution import TOOL

PREFIX = f"{TOOL}_"

# Deterministic constraint names: a later migration can drop or alter them by name
# on both PostgreSQL and SQLite (batch mode); they start with the (prefixed) table name.
metadata = sa.MetaData(
    naming_convention={
        "ix": "%(table_name)s_%(column_0_N_name)s_ix",
        "uq": "%(table_name)s_%(column_0_N_name)s_uq",
        "ck": "%(table_name)s_%(constraint_name)s_ck",
        "fk": "%(table_name)s_%(column_0_name)s_fk",
        "pk": "%(table_name)s_pk",
    }
)

# The response journal (it is also the cache, `search --cache`): every paid answer, append-only.
# A repeated query adds a row; readers take the newest by `fetched_at`.
responses = sa.Table(
    f"{PREFIX}responses",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),  # when the provider answered, UTC
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("freq_type", sa.Text, nullable=False),
    sa.Column("region", sa.Integer, nullable=False),  # Yandex lr
    sa.Column("phrase", sa.Text, nullable=False),  # the query as the user typed it
    sa.Column("phrase_key", sa.Text, nullable=False),  # core.normalize.norm_phrase(phrase)
    sa.Column("total_value", sa.BigInteger, nullable=False),
    sa.Column("data", sa.LargeBinary, nullable=False),  # the raw answer, zlib-compressed JSON
    # The natural key; also the cache lookup (newest first by fetched_at).
    sa.UniqueConstraint(
        "provider", "freq_type", "region", "phrase_key", "fetched_at", name="wordstat_responses_key_uq"
    ),
    sa.Index(None, "fetched_at"),
    info={"push": {"since": "fetched_at"}},
)
