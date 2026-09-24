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


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
