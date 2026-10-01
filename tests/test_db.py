from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from typer.testing import CliRunner

from rb_wordstat.cli import app
from rb_wordstat.core import db, tables
from rb_wordstat.core.errors import DatabaseNotMigrated, DatabaseTooNew, DatabaseUnavailable, InvalidArguments
from rb_wordstat.core.normalize import norm_phrase

runner = CliRunner()

# The real PostgreSQL contract (advisory lock, sequences, psycopg) runs only when
# a throwaway server is given: TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/postgres
PG_URL = os.environ.get("TEST_DATABASE_URL")


def invoke_json(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.stdout)


def _add_item(engine: sa.Engine, phrase: str = "Купить ёлку") -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.insert(tables.responses).values(
                fetched_at=datetime(2026, 9, 1, tzinfo=UTC), provider="xmlriver", freq_type="broad", region=213,
                phrase=phrase, phrase_key=norm_phrase(phrase), total_value=1, data=b"{}",
            )
        )  # fmt: skip


def test_names_are_namespaced() -> None:
    assert all(table.name.startswith(db.PREFIX) for table in tables.metadata.sorted_tables)
    tool = db.PREFIX.removesuffix("_")
    assert db.VERSION_TABLE.endswith(f"_{tool}")
    assert db.ENV_VAR.startswith(f"{tool.upper()}_")


def test_sqlite_is_created_and_migrated_on_open(_local_database: Path) -> None:
    engine = db.open_db()
    names = sa.inspect(engine).get_table_names()
    assert db.VERSION_TABLE in names and "alembic_version" not in names
    assert f"{db.PREFIX}v1_responses" in sa.inspect(engine).get_view_names()
    assert db.schema_state(engine).up_to_date
    assert _local_database.is_file()


def test_sqlite_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.undo()  # conftest replaced sqlite_path itself
    monkeypatch.setenv(db.PATH_ENV_VAR, str(tmp_path / "x.sqlite"))
    assert db.sqlite_path() == tmp_path / "x.sqlite"
    monkeypatch.delenv(db.PATH_ENV_VAR)
    assert db.sqlite_path().name == f"{db.PREFIX.removesuffix('_')}.db"


def test_tables_match_the_migrations() -> None:
    """tables.py and migrations/versions/ describe the same schema."""
    engine = db.open_db()
    with engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_name": lambda name, type_, *_: type_ != "table" or name.startswith(db.PREFIX)}
        )
        assert compare_metadata(context, tables.metadata) == []


def test_url_never_falls_back_to_sqlite(monkeypatch: pytest.MonkeyPatch, _local_database: Path) -> None:
    monkeypatch.setenv(db.ENV_VAR, "postgresql://user:secret@127.0.0.1:1/nowhere")
    code, payload = invoke_json("db", "status")
    assert code == 5
    assert payload["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "secret" not in payload["error"]["message"]
    assert not _local_database.exists()


@pytest.mark.parametrize("url", ["sqlite:///x.db", "not a url"])
def test_url_must_be_postgres(url: str) -> None:
    with pytest.raises(DatabaseUnavailable):
        db.postgres_engine(url)


def _as_postgres(monkeypatch: pytest.MonkeyPatch, engine: sa.Engine) -> None:
    """Route the URL branch to a SQLite engine: the shared-database rules without a server."""
    monkeypatch.setenv(db.ENV_VAR, "postgresql://stand-in")
    monkeypatch.setattr(db, "postgres_engine", lambda *_args, **_kwargs: engine)


def test_shared_database_is_never_migrated_implicitly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.db")
    _as_postgres(monkeypatch, engine)
    with pytest.raises(DatabaseNotMigrated) as excinfo:
        db.open_db()
    assert "db upgrade" in (excinfo.value.action or "")
    assert db.schema_state(engine).current is None  # untouched
    assert db.open_db(check=False) is engine


def test_db_upgrade_migrates_the_shared_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.db")
    _as_postgres(monkeypatch, engine)
    code, payload = invoke_json("db", "upgrade", "--dry-run")
    assert (code, payload["current"], payload["dry_run"]) == (0, None, True)
    assert db.schema_state(engine).current is None

    code, payload = invoke_json("db", "upgrade")
    assert code == 0
    assert payload["previous"] is None and payload["up_to_date"] is True
    db.open_db()  # checked, fine now

    code, payload = invoke_json("db", "upgrade")
    assert payload["previous"] == payload["head"]


def test_database_newer_than_the_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = db.sqlite_engine(tmp_path / "shared.db")
    db.upgrade(engine)
    with engine.begin() as conn:
        conn.execute(sa.text(f"UPDATE {db.VERSION_TABLE} SET version_num = 'from_the_future'"))  # noqa: S608
    _as_postgres(monkeypatch, engine)
    with pytest.raises(DatabaseTooNew):
        db.open_db()
    with pytest.raises(DatabaseTooNew):
        db.upgrade(engine)  # never "upgrade" to an older head
    _code, payload = invoke_json("doctor")
    schema = next(check for check in payload["checks"] if check["name"] == "database_schema")
    assert schema["ok"] is False and "upgrade" in schema["detail"]


def test_doctor_reports_the_database() -> None:
    _code, payload = invoke_json("doctor")
    checks = {check["name"]: check for check in payload["checks"]}
    assert checks["database"]["ok"] and checks["database_schema"]["ok"]


def test_doctor_reports_an_unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(db.ENV_VAR, "postgresql://user@127.0.0.1:1/nowhere")
    code, payload = invoke_json("doctor")
    assert code == 0
    database = next(check for check in payload["checks"] if check["name"] == "database")
    assert database["ok"] is False


def test_status(_local_database: Path) -> None:
    code, payload = invoke_json("db", "status")
    assert code == 0
    assert payload["up_to_date"] is True
    assert str(_local_database) in payload["database"]


def test_import_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = db.sqlite_engine(tmp_path / "old.db")
    db.upgrade(source)
    _add_item(source)
    _add_item(source, "вторая")
    target = db.sqlite_engine(tmp_path / "shared.db")
    db.upgrade(target)
    _as_postgres(monkeypatch, target)

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.db"), "--dry-run")
    assert code == 0 and payload["rows"] == {tables.responses.name: 2}
    with target.connect() as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(tables.responses)).scalar_one() == 0

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.db"))
    assert code == 0 and payload["rows"] == {tables.responses.name: 2}
    with target.connect() as conn:
        assert {row.phrase for row in conn.execute(sa.select(tables.responses))} == {"Купить ёлку", "вторая"}

    code, payload = invoke_json("db", "import-sqlite", str(tmp_path / "old.db"))
    assert code == 2 and "not empty" in payload["error"]["message"]


def test_import_sqlite_rejects_bad_sources(tmp_path: Path) -> None:
    target = db.sqlite_engine(tmp_path / "shared.db")
    with pytest.raises(InvalidArguments, match="No SQLite"):
        db.import_sqlite(tmp_path / "missing.db", target)
    db.upgrade(target)
    with pytest.raises(InvalidArguments, match="same database"):
        db.import_sqlite(tmp_path / "shared.db", target)


def _prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> sa.Engine:
    """A migrated stand-in for production, behind <TOOL>_PROD_DATABASE_URL."""
    prod = db.sqlite_engine(tmp_path / "prod.db")
    db.upgrade(prod)
    monkeypatch.setenv(db.PROD_ENV_VAR, "postgresql://prod")
    monkeypatch.setattr(db, "postgres_engine", lambda *_args, **_kwargs: prod)
    return prod


def _phrases(engine: sa.Engine) -> list[tuple[int, str]]:
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(sa.select(tables.responses.c.id, tables.responses.c.phrase).order_by("id"))
        ]


def test_push(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local = db.open_db()
    for phrase in ("один", "два", "три"):
        _add_item(local, phrase)
    prod = _prod(monkeypatch, tmp_path)
    _add_item(prod, "два")  # already there: skipped, not duplicated
    _add_item(prod, "четыре")

    code, payload = invoke_json("db", "push", "--dry-run")
    assert code == 0, payload
    assert payload["tables"] == {tables.responses.name: {"selected": 3, "sent": 2, "skipped": 1}}
    assert len(_phrases(prod)) == 2

    code, payload = invoke_json("db", "push")
    assert payload["tables"][tables.responses.name]["sent"] == 2
    assert [phrase for _id, phrase in _phrases(prod)] == ["два", "четыре", "один", "три"]  # prod's own ids

    code, payload = invoke_json("db", "push")
    assert payload["tables"][tables.responses.name] == {"selected": 3, "sent": 0, "skipped": 3}


def test_push_filters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local = db.open_db()
    _add_item(local, "старая")
    with local.begin() as conn:
        conn.execute(sa.update(tables.responses).values(fetched_at=datetime(2020, 1, 1, tzinfo=UTC)))
    _add_item(local, "новая")
    _prod(monkeypatch, tmp_path)
    _code, payload = invoke_json("db", "push", "--since", "2026-01-01", "--dry-run")
    assert payload["tables"][tables.responses.name]["selected"] == 1
    _code, payload = invoke_json("db", "push", "--where", "phrase = 'старая'", "--dry-run")
    assert payload["tables"][tables.responses.name]["selected"] == 1
    code, payload = invoke_json("db", "push", "--table", "nope")
    assert code == 2 and "Not a push table" in payload["error"]["message"]


def test_push_needs_a_migrated_prod(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, payload = invoke_json("db", "push")
    assert code == 2 and db.PROD_ENV_VAR in payload["error"]["message"]
    prod = db.sqlite_engine(tmp_path / "prod.db")  # never migrated
    monkeypatch.setenv(db.PROD_ENV_VAR, "postgresql://prod")
    monkeypatch.setattr(db, "postgres_engine", lambda *_args, **_kwargs: prod)
    code, payload = invoke_json("db", "push")
    assert code == 1 and payload["error"]["code"] == "DATABASE_NOT_MIGRATED"


def test_push_table_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "push_tables", lambda: [])
    with pytest.raises(InvalidArguments, match="No table"):
        db.push(db.open_db(), db.open_db())
    keyless = sa.Table(
        f"{db.PREFIX}keyless", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True), info={"push": {}}
    )
    monkeypatch.setattr(db, "push_tables", lambda: [keyless])
    with pytest.raises(InvalidArguments, match="natural key"):
        db.push(db.open_db(), db.open_db())
    no_since = tables.responses.to_metadata(sa.MetaData())
    no_since.info["push"] = {}
    monkeypatch.setattr(db, "push_tables", lambda: [no_since])
    with pytest.raises(InvalidArguments, match="since"):
        db.push(db.open_db(), db.open_db(), since=datetime(2026, 1, 1))


@pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set")
def test_postgres_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert PG_URL
    monkeypatch.setenv(db.ENV_VAR, PG_URL)
    engine = db.open_db(check=False)
    with engine.begin() as conn:  # a clean slate: only this tool's objects
        conn.execute(sa.text(f"DROP VIEW IF EXISTS {db.PREFIX}v1_responses"))
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {db.PREFIX}responses, {db.VERSION_TABLE}"))
        conn.execute(sa.text("CREATE TABLE IF NOT EXISTS directus_users (id int)"))  # someone else's table
    with pytest.raises(DatabaseNotMigrated):
        db.open_db()
    assert db.upgrade(engine).up_to_date
    db.check_schema(engine)

    source = db.sqlite_engine(tmp_path / "old.db")
    db.upgrade(source)
    _add_item(source)
    assert db.import_sqlite(tmp_path / "old.db", engine) == {tables.responses.name: 1}
    _add_item(engine, "вторая")  # the sequence moved past the imported ids
    with engine.connect() as conn:
        assert conn.execute(sa.text(f"SELECT count(*) FROM {db.PREFIX}v1_responses")).scalar_one() == 2  # noqa: S608
        assert sa.inspect(conn).has_table("directus_users")

    monkeypatch.setenv(db.PROD_ENV_VAR, PG_URL)  # db push into real PostgreSQL: ON CONFLICT, RETURNING
    local = db.sqlite_engine(tmp_path / "local.db")
    db.upgrade(local)
    _add_item(local)  # "Купить ёлку" is already there
    _add_item(local, "третья")
    prod = db.prod_engine()
    assert db.push(local, prod, dry_run=True) == {tables.responses.name: {"selected": 2, "sent": 1, "skipped": 1}}
    assert db.push(local, prod)[tables.responses.name]["sent"] == 1
    assert db.push(local, prod)[tables.responses.name]["sent"] == 0
    prod.dispose()
    engine.dispose()
