from __future__ import annotations

import json
from pathlib import Path

import pytest


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
def isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Every test gets its own empty response journal instead of the real wordstat.db."""
    db_path = tmp_path / "wordstat-journal" / "wordstat.db"
    monkeypatch.setenv("WORDSTAT_DB_PATH", str(db_path))
    return db_path


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
