from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from rb_wordstat.core import db

# `cache --help` shows the journal path and size, computed when the CLI is
# imported — before any fixture runs. A fixed, never-created path keeps the
# help snapshot independent of the developer's real wordstat.db.
os.environ["WORDSTAT_DB_PATH"] = "/nonexistent/wordstat-journal/wordstat.db"


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real keychain and exported credentials out of every test."""
    for name in (
        "XMLRIVER_USER",
        "XMLRIVER_TOKEN",
        *(
            f"{ns}_{provider}_{field}"
            for ns in ("WORDSTAT", "SERP")
            for provider in ("XMLRIVER", "XMLSTOCK")
            for field in ("USER", "TOKEN")
        ),
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("rb_wordstat.credentials.manager.keyring.get_password", lambda service, username: None)


@pytest.fixture(autouse=True)
def _local_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Every test gets its own SQLite file: never the user's database, never the shared PostgreSQL.

    Engines the test opens are disposed after it — Python 3.14 warns about every
    SQLite connection left to the garbage collector.
    """
    path = tmp_path / "db" / "test.db"
    monkeypatch.setattr(db, "sqlite_path", lambda: path)
    monkeypatch.delenv(db.ENV_VAR, raising=False)
    monkeypatch.delenv(db.PROD_ENV_VAR, raising=False)
    engines: list[sa.Engine] = []
    sqlite_engine = db.sqlite_engine

    def tracked(file: Path) -> sa.Engine:
        engines.append(sqlite_engine(file))
        return engines[-1]

    monkeypatch.setattr(db, "sqlite_engine", tracked)
    yield path
    for engine in engines:
        engine.dispose()


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def contract_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Офлайн-данные контрактных кейсов (tests/contracts/fixtures.yaml): журнал и фальшивые ключи.

    В журнале — записанный ответ XML River (tests/fixtures/xmlriver_wordstat.json)
    по «купить диван», точная частота, регион 213: `search --cache` берёт его,
    не вызывая провайдера. Ключи фальшивые — до сети дело не доходит.
    """
    from rb_wordstat.core.cache import ResponseCache

    data = fixture_json("xmlriver_wordstat.json")
    ResponseCache().put(
        provider="xmlriver", freq_type="exact", region=213, query="купить диван", total_value=data["totalValue"],
        data=data,
    )  # fmt: skip
    monkeypatch.setenv("SERP_XMLRIVER_USER", "contract-user")
    monkeypatch.setenv("SERP_XMLRIVER_TOKEN", "contract-token")
