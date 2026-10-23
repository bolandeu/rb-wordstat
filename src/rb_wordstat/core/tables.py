"""This tool's tables, as SQLAlchemy Core — mirrors the latest migration (`migrations/versions/`).

Every name starts with `PREFIX` (`<tool>_`): the shared PostgreSQL holds every
tool's tables (and Directus') in one `public` schema. Change a table here *and* add
a migration by hand (copy the example in `migrations/versions/`) — tests/test_db.py
fails when the migrated schema and this metadata disagree.

Every table has a single-column PRIMARY KEY — Directus can't show or edit a
table without one and doesn't support a composite one: a surrogate `id`, with the
natural key as a UNIQUE constraint (tests/test_db.py checks this metadata and the
migrated database).

Every table says what its rows are, `info={"kind": "data"}` or `"cache"` (tests/test_db.py
fails without it): `data` is the tool's result and lost when deleted; `cache` is a copy
of something it can fetch again. `describe --json` publishes it (x-rb-data).

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
CACHE_SCHEMA = "cache"  # where a cache table would live in PostgreSQL (the Standard, Database); wordstat keeps its journal in public

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
    info={"kind": "cache", "push": {"since": "fetched_at"}},
)

# The `<tool>_v1_*` views other tools, Directus and the platform read instead of the
# tables — the tool's data contract, published by `describe --json` (x-rb-data.views).
# Declared here for that, created by a migration (`CREATE VIEW`); tests/test_db.py
# fails when a view below is missing from the migrated database or its columns differ.
# Columns never change: a different shape is a new `_v2_` view next to the old one.
# Kept out of `metadata`, which mirrors the tables only.
views = sa.MetaData()

v1_responses = sa.Table(
    f"{PREFIX}v1_responses",
    views,
    sa.Column("fetched_at", sa.DateTime(timezone=True), comment="When the provider answered, UTC"),
    sa.Column("provider", sa.Text, comment="The provider that answered (xmlriver, xmlstock)"),
    sa.Column("freq_type", sa.Text, comment="Frequency type: broad, phrase, exact or exact_ord"),
    sa.Column("region", sa.Integer, comment="Yandex region id (lr)"),
    sa.Column("phrase", sa.Text, comment="The query as the user typed it"),
    sa.Column("phrase_key", sa.Text, comment="The normalized phrase: the key to join on"),
    sa.Column("total_value", sa.BigInteger, comment="Wordstat frequency for the phrase"),
    comment="Every Wordstat answer, append-only: a repeated query adds a row, take the newest by fetched_at",
)
