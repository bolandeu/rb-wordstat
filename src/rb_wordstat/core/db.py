"""The tool's database: the shared PostgreSQL from `<TOOL>_DATABASE_URL`, else a local SQLite file.

- URL set → PostgreSQL only. Unreachable / wrong credentials → `DatabaseUnavailable`
  (exit 5). Never a silent fallback to SQLite: rows written there would be missing
  from the shared base without anyone noticing.
- URL not set → SQLite in the user data dir (tests, offline work).

Schema changes are Alembic migrations (`migrations/`), tracked in this tool's own
`alembic_version_<TOOL>` table. SQLite is brought up to date when opened. PostgreSQL
is never migrated implicitly — it's one database for every machine, and a dev
checkout must not migrate it: `<cli> db upgrade` does that, under an advisory lock;
opening it only checks the revision (behind → `DatabaseNotMigrated`, unknown → the
database is newer than this CLI, `DatabaseTooNew`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import platformdirs
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util import CommandError
from sqlalchemy import event
from sqlalchemy import exc as sa_exc

from .._distribution import TOOL
from .errors import DatabaseNotMigrated, DatabaseTooNew, DatabaseUnavailable, InvalidArguments
from .tables import PREFIX, metadata

_PACKAGE_NAME = __name__.split(".")[0]

ENV_VAR = f"{TOOL.upper()}_DATABASE_URL"
PROD_ENV_VAR = f"{TOOL.upper()}_PROD_DATABASE_URL"  # `db push` target: production, from a dev machine
PATH_ENV_VAR = f"{TOOL.upper()}_DB_PATH"  # the local SQLite file elsewhere (a second database, an existing file)
# What each one is for — `describe --json` lists them (x-rb-env).
ENV_VARS = {
    ENV_VAR: "Shared PostgreSQL URL; unset → the local SQLite file",
    PROD_ENV_VAR: "Production PostgreSQL URL, the target of `db push` from a dev machine",
    PATH_ENV_VAR: "The local SQLite file, instead of the one in the user data dir",
}
VERSION_TABLE = f"alembic_version_{TOOL}"
CONNECT_TIMEOUT_S = 5


def database_url() -> str | None:
    return os.environ.get(ENV_VAR) or None


def sqlite_path() -> Path:
    """The local database: `<TOOL>_DB_PATH`, else the app data dir (not Caches — cleaners wipe caches)."""
    if path := os.environ.get(PATH_ENV_VAR):
        return Path(path).expanduser()
    return platformdirs.user_data_path(TOOL) / f"{TOOL}.db"


def is_postgres(engine: sa.Engine | sa.Connection) -> bool:
    return engine.dialect.name == "postgresql"


def describe(engine: sa.Engine) -> str:
    """Where the engine points, password hidden — for doctor and `db status`."""
    return engine.url.render_as_string(hide_password=True)


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block a writer
    cursor.close()


def sqlite_engine(path: Path) -> sa.Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def postgres_engine(url: str, *, env_var: str = ENV_VAR) -> sa.Engine:
    """An engine for `url` (any `postgres://` / `postgresql://` spelling → the psycopg driver), connection checked."""
    try:
        parsed = sa.make_url(url)
    except sa_exc.ArgumentError as exc:
        raise DatabaseUnavailable(f"{env_var} is not a database URL.") from exc
    if parsed.drivername.split("+")[0] not in ("postgres", "postgresql"):
        raise DatabaseUnavailable(f"{env_var}: only PostgreSQL is supported, not '{parsed.drivername}'.")
    engine = sa.create_engine(
        parsed.set(drivername="postgresql+psycopg"),
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_S},
    )
    try:
        with engine.connect():
            pass
    except sa_exc.OperationalError as exc:
        engine.dispose()
        where = parsed.render_as_string(hide_password=True)
        reason = str(exc.orig).strip().splitlines()[0]  # psycopg repeats it per address tried
        raise DatabaseUnavailable(f"Can't connect to {where}: {reason}") from exc
    return engine


def alembic_config(connection: sa.Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", f"{_PACKAGE_NAME}:migrations")
    config.attributes.update(connection=connection, metadata=metadata, prefix=PREFIX, version_table=VERSION_TABLE)
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("migrations/versions/ has no revisions")
    return head


def current_revision(connection: sa.Connection) -> str | None:
    return MigrationContext.configure(connection, opts={"version_table": VERSION_TABLE}).get_current_revision()


@dataclass(frozen=True)
class SchemaState:
    current: str | None
    head: str

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head

    @property
    def too_new(self) -> bool:
        """The database is at a revision this CLI's migrations don't contain: a newer release migrated it."""
        if self.current is None:
            return False
        try:
            return ScriptDirectory.from_config(alembic_config()).get_revision(self.current) is None
        except (RevisionError, CommandError):  # alembic raises (not returns None) for an unknown id
            return True


def schema_state(engine: sa.Engine) -> SchemaState:
    with engine.connect() as connection:
        return SchemaState(current_revision(connection), head_revision())


def check_schema(engine: sa.Engine) -> None:
    """Raise unless the database is exactly at this CLI's head revision."""
    state = schema_state(engine)
    if state.up_to_date:
        return
    if state.too_new:
        raise DatabaseTooNew(state.current or "")
    raise DatabaseNotMigrated(state.current, state.head)


def upgrade(engine: sa.Engine) -> SchemaState:
    """Apply pending migrations, in one transaction. On PostgreSQL two runs at once queue on an advisory lock."""
    state = schema_state(engine)
    if state.up_to_date:
        return state
    if state.too_new:  # never "upgrade" a database to an older head
        raise DatabaseTooNew(state.current or "")
    with engine.begin() as connection:
        if is_postgres(connection):
            connection.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": VERSION_TABLE})
        command.upgrade(alembic_config(connection), "head")
    return schema_state(engine)


def open_db(*, check: bool = True) -> sa.Engine:
    """The database this CLI works with: `<TOOL>_DATABASE_URL`, else local SQLite.

    SQLite is migrated on open. PostgreSQL is only checked (`check=False` skips even
    that — for `db upgrade`/`db status` and doctor, which report the revision).
    """
    url = database_url()
    if url is None:
        engine = sqlite_engine(sqlite_path())
        upgrade(engine)
        return engine
    engine = postgres_engine(url)
    if check:
        check_schema(engine)
    return engine


@contextmanager
def connect() -> Iterator[sa.Connection]:
    """A transaction on the tool's database: committed on success, rolled back on error."""
    engine = open_db()
    try:
        with engine.begin() as connection:
            yield connection
    finally:
        engine.dispose()


def import_sqlite(source: Path, target: sa.Engine, *, dry_run: bool = False) -> dict[str, int]:
    """Copy this tool's tables from a local SQLite file into `target` (the shared database), in one transaction.

    The source is brought to the head revision first (its own migrations, like any
    open — even under `dry_run`), so both sides have the same tables. Every target table must be empty —
    an import is a one-off move, not a merge. Returns rows per table.
    """
    if not source.is_file():
        raise InvalidArguments(f"No SQLite database at '{source}'.")
    if target.url.database and Path(target.url.database).resolve() == source.resolve():
        raise InvalidArguments("Source and target are the same database.")
    source_engine = sqlite_engine(source)
    try:
        upgrade(source_engine)
        check_schema(target)
        counts: dict[str, int] = {}
        with source_engine.connect() as src, target.begin() as dst:
            for table in metadata.sorted_tables:  # parents before children (foreign keys)
                if dst.execute(sa.select(sa.func.count()).select_from(table)).scalar_one():
                    raise InvalidArguments(f"Table '{table.name}' in the target database is not empty.")
                counts[table.name] = src.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
                if dry_run:
                    continue
                rows = src.execute(sa.select(table)).mappings()
                while batch := rows.fetchmany(1000):
                    dst.execute(sa.insert(table), [dict(row) for row in batch])
                if is_postgres(dst):
                    _reset_sequences(dst, table)
        return counts
    finally:
        source_engine.dispose()


def _reset_sequences(connection: sa.Connection, table: sa.Table) -> None:
    """Rows came in with their ids: move each serial/identity sequence past them, or the next insert collides."""
    for column in table.primary_key.columns:
        if column.autoincrement is True or (column.autoincrement == "auto" and isinstance(column.type, sa.Integer)):
            top = f"SELECT max({column.name}) FROM {table.name}"  # noqa: S608 — names from tables.py, not input
            connection.execute(
                sa.text(f"SELECT setval(pg_get_serial_sequence(:table, :column), coalesce(({top}), 0) + 1, false)"),
                {"table": table.name, "column": column.name},
            )


def push_tables() -> list[sa.Table]:
    """Tables marked `info={"push": ...}` in tables.py — append-only, with a natural key."""
    return [table for table in metadata.sorted_tables if "push" in table.info]


def prod_engine() -> sa.Engine:
    """Production PostgreSQL for `db push` (`<TOOL>_PROD_DATABASE_URL`), at this CLI's revision."""
    url = os.environ.get(PROD_ENV_VAR)
    if not url:
        raise InvalidArguments(f"{PROD_ENV_VAR} is not set: it names the production database `db push` writes to.")
    engine = postgres_engine(url, env_var=PROD_ENV_VAR)
    check_schema(engine)
    return engine


def push(
    source: sa.Engine,
    target: sa.Engine,
    *,
    tables: list[str] | None = None,
    since: datetime | None = None,
    where: str | None = None,
    dry_run: bool = False,
) -> dict[str, dict[str, int]]:
    """Insert the source's rows of the push tables into `target`, skipping those whose natural key is there.

    Ids are not carried over (the target numbers its own rows). `since` keeps rows whose
    `since` column (tables.py) is at or after it; `where` is an SQL condition on the
    source table, ANDed in. One transaction; `dry_run` rolls it back, so the counts are
    exact either way. Returns per table: `selected`, `sent` (inserted), `skipped`.
    """
    known = {table.name: table for table in push_tables()}
    if not known:
        raise InvalidArguments("No table is marked for push (info={'push': ...} in core/tables.py).")
    chosen = [known[name] for name in known if not tables or name in tables]
    if unknown := sorted(set(tables or ()) - set(known)):
        raise InvalidArguments(f"Not a push table: {', '.join(unknown)}. Push tables: {', '.join(known)}.")
    report: dict[str, dict[str, int]] = {}
    with source.connect() as src, target.connect() as dst:
        transaction = dst.begin()
        for table in chosen:
            if table.foreign_keys or not any(isinstance(c, sa.UniqueConstraint) for c in table.constraints):
                raise InvalidArguments(f"Push table '{table.name}' needs a unique natural key and no foreign keys.")
            columns = [c for c in table.columns if not (c.primary_key and c.autoincrement in (True, "auto"))]
            query = sa.select(*columns)
            if since is not None:
                if not (column := table.info["push"].get("since")):
                    raise InvalidArguments(f"Push table '{table.name}' has no `since` column for --since.")
                query = query.where(table.c[column] >= since)
            if where:
                query = query.where(sa.text(where))
            insert = _insert(dst, table).on_conflict_do_nothing().returning(sa.literal(1))
            selected = sent = 0
            rows = src.execute(query).mappings()
            while batch := rows.fetchmany(1000):
                selected += len(batch)
                sent += len(dst.execute(insert, [dict(row) for row in batch]).all())
            report[table.name] = {"selected": selected, "sent": sent, "skipped": selected - sent}
        if dry_run:
            transaction.rollback()
        else:
            transaction.commit()
    return report


def _insert(connection: sa.Connection, table: sa.Table):
    """INSERT with `on_conflict_do_nothing()` in the connection's dialect."""
    if is_postgres(connection):
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert(table)


def doctor_checks() -> list[dict]:
    """doctor's `database` and `database_schema` checks (connection, revision vs this CLI's head)."""
    try:
        engine = open_db(check=False)
    except DatabaseUnavailable as exc:
        return [{"name": "database", "ok": False, "detail": exc.message}]
    try:
        state = schema_state(engine)
        checks = [{"name": "database", "ok": True, "detail": describe(engine)}]
        if state.up_to_date:
            checks.append({"name": "database_schema", "ok": True, "detail": state.head})
        else:
            problem = (
                DatabaseTooNew(state.current or "") if state.too_new else DatabaseNotMigrated(state.current, state.head)
            )
            checks.append({"name": "database_schema", "ok": False, "detail": f"{problem.message} {problem.action}"})
        return checks
    finally:
        engine.dispose()


__all__ = [
    "ENV_VAR",
    "PATH_ENV_VAR",
    "PREFIX",
    "PROD_ENV_VAR",
    "VERSION_TABLE",
    "SchemaState",
    "check_schema",
    "connect",
    "database_url",
    "doctor_checks",
    "import_sqlite",
    "open_db",
    "push",
    "push_tables",
    "schema_state",
    "sqlite_path",
    "upgrade",
]
