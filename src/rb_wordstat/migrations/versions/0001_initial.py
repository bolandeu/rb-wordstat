"""wordstat_responses (the response journal), its v1 view; the pre-Alembic `responses` table moves in

Revision ID: 0001
Revises:

Before 0.4 the journal was a bare `responses` table in the local SQLite file
(ISO-8601 text dates, text region, `query_key` = lower + collapsed spaces). Where it
exists its rows are copied over with their original `fetched_at` and the table is
dropped; the key is recomputed with norm_phrase (adds yo → ye).

Names are literal on purpose: a migration is history and must not change when
code it would import does — norm_phrase is copied here for the same reason.
"""

import unicodedata
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _norm_phrase(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    return " ".join(text.split())


def upgrade() -> None:
    responses = op.create_table(
        "wordstat_responses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("freq_type", sa.Text, nullable=False),
        sa.Column("region", sa.Integer, nullable=False),
        sa.Column("phrase", sa.Text, nullable=False),
        sa.Column("phrase_key", sa.Text, nullable=False),
        sa.Column("total_value", sa.BigInteger, nullable=False),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.PrimaryKeyConstraint("id", name="wordstat_responses_pk"),
        sa.UniqueConstraint(
            "provider", "freq_type", "region", "phrase_key", "fetched_at",
            name="wordstat_responses_key_uq",
        ),
    )  # fmt: skip
    op.create_index("wordstat_responses_fetched_at_ix", "wordstat_responses", ["fetched_at"])

    bind = op.get_bind()
    if "responses" in sa.inspect(bind).get_table_names():  # only ever in a local SQLite file
        rows = bind.execute(
            sa.text(
                "SELECT fetched_at, provider, freq_type, region, query, total_value, data FROM responses ORDER BY id"
            )
        ).all()
        op.bulk_insert(
            responses,
            [
                {
                    "fetched_at": datetime.fromisoformat(r.fetched_at).astimezone(UTC),
                    "provider": r.provider,
                    "freq_type": r.freq_type,
                    "region": int(r.region),
                    "phrase": r.query,
                    "phrase_key": _norm_phrase(r.query),
                    "total_value": r.total_value,
                    "data": r.data,
                }
                for r in rows
            ],
        )
        op.drop_table("responses")

    # The contract with other tools: they read this view, never the table. Its
    # columns don't change — a different shape is a new `_v2_` view next to it.
    op.execute(
        """
        CREATE VIEW wordstat_v1_responses AS
        SELECT fetched_at, provider, freq_type, region, phrase, phrase_key, total_value FROM wordstat_responses
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW wordstat_v1_responses")
    op.drop_table("wordstat_responses")
