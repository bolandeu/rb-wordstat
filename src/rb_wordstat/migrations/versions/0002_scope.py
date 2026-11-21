"""wordstat_responses.scope: the journal key learns the device and the depth

Revision ID: 0002
Revises: 0001

An answer depends on the device (`desktop`, `phone`, `tablet` or all of them) and, on XMLStock, on how many similar
phrases were asked (`groupby`). Without those in the key a cache hit would answer a different question, so the natural
key grows by `scope` (`'<device>|<limit>'`, `''` for the provider's own defaults). Existing rows get `''` and stay
valid: they were collected with exactly those defaults.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

KEY = ["provider", "freq_type", "region", "phrase_key", "fetched_at"]
NAME = "wordstat_responses_key_uq"


VIEW = """
        CREATE VIEW wordstat_v1_responses AS
        SELECT fetched_at, provider, freq_type, region, phrase, phrase_key, total_value FROM wordstat_responses
        """


def upgrade() -> None:
    # The view on the table blocks the batch table-rebuild SQLite needs; it is recreated with the same columns.
    op.execute("DROP VIEW IF EXISTS wordstat_v1_responses")
    with op.batch_alter_table("wordstat_responses") as batch:
        batch.add_column(sa.Column("scope", sa.Text, nullable=False, server_default=sa.text("''")))
        batch.drop_constraint(NAME, type_="unique")
        batch.create_unique_constraint(NAME, [*KEY, "scope"])
    op.execute(VIEW)


def downgrade() -> None:
    with op.batch_alter_table("wordstat_responses") as batch:
        batch.drop_constraint(NAME, type_="unique")
        batch.create_unique_constraint(NAME, KEY)
        batch.drop_column("scope")
    op.execute(VIEW)
