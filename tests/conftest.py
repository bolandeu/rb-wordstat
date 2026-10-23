"""Shared fixtures: rerun a test file under the CI environment, and give each test its own local database."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from rb_wordstat.core import db

# Typer reads these once, at import, and then forces terminal output — what a CI runner sets.
CI_ENV = {"GITHUB_ACTIONS": "true", "FORCE_COLOR": "1", "PY_COLORS": "1"}


@pytest.fixture
def same_in_ci(request: pytest.FixtureRequest) -> Callable[[str], None]:
    """Rerun this file's tests matching `-k` under CI_ENV in a fresh interpreter: the only way to set a value read at import."""
    if request.config.getoption("--snapshot-update"):
        pytest.skip("the snapshots are being written; there is nothing to compare yet")

    def run(selection: str) -> None:
        options = ["-k", selection, "-p", "no:cacheprovider", "--no-cov", "-q"]
        command = [sys.executable, "-m", "pytest", str(request.path), *options]
        env = {**os.environ, **CI_ENV}
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
        assert result.returncode == 0, result.stdout[-3000:]

    return run


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
    по «купить диван», широкая частота, регион 213, с похожими (popular) и
    ассоциациями (associations): `search --cache` берёт его, не вызывая провайдера. Ключи фальшивые — до сети дело не доходит.
    """
    from rb_wordstat.core.cache import ResponseCache

    data = fixture_json("xmlriver_wordstat.json")
    ResponseCache().put(
        provider="xmlriver", freq_type="broad", region=213, query="купить диван", total_value=data["totalValue"],
        data=data,
    )  # fmt: skip
    monkeypatch.setenv("SERP_XMLRIVER_USER", "contract-user")
    monkeypatch.setenv("SERP_XMLRIVER_TOKEN", "contract-token")
