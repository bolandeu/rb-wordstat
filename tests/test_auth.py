from __future__ import annotations

from pathlib import Path

import pytest

from .test_cli import invoke, invoke_json


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch):
    """In-memory stand-in for the OS keychain so auth tests don't touch it."""
    store: dict[tuple[str, str], str] = {}

    def fake_set_password(service: str, username: str, password: str) -> None:
        store[(service, username)] = password

    def fake_get_password(service: str, username: str) -> str | None:
        return store.get((service, username))

    def fake_delete_password(service: str, username: str) -> None:
        store.pop((service, username), None)

    monkeypatch.setattr("rb_wordstat.credentials.manager.keyring.set_password", fake_set_password)
    monkeypatch.setattr("rb_wordstat.credentials.manager.keyring.get_password", fake_get_password)
    monkeypatch.setattr("rb_wordstat.credentials.manager.keyring.delete_password", fake_delete_password)
    return store


def test_auth_login_logout_status_round_trip(fake_keyring) -> None:
    _, payload = invoke_json("auth", "status", "--provider", "xmlriver")
    assert payload["authenticated"] is False

    result = invoke("auth", "login", "--provider", "xmlriver", "--non-interactive")
    assert result.exit_code == 2  # no env var set, non-interactive can't prompt

    result = invoke(
        "auth",
        "login",
        "--provider",
        "xmlriver",
        "--non-interactive",
        env={"WORDSTAT_XMLRIVER_USER": "u", "WORDSTAT_XMLRIVER_TOKEN": "t"},
    )
    assert result.exit_code == 0

    _, payload = invoke_json("auth", "status", "--provider", "xmlriver")
    assert payload["authenticated"] is True

    assert invoke("auth", "logout", "--provider", "xmlriver").exit_code == 0

    _, payload = invoke_json("auth", "status", "--provider", "xmlriver")
    assert payload["authenticated"] is False


def test_env_var_works_when_keyring_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring.errors

    def broken_get_password(service: str, username: str) -> str | None:
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr("rb_wordstat.credentials.manager.keyring.get_password", broken_get_password)
    _, payload = invoke_json(
        "auth", "status", "--provider", "xmlriver", env={"WORDSTAT_XMLRIVER_USER": "u", "WORDSTAT_XMLRIVER_TOKEN": "t"}
    )
    assert payload["authenticated"] is True


def test_doctor_reports_credential_checks(tmp_path: Path, fake_keyring) -> None:
    _, payload = invoke_json("--project", str(tmp_path), "doctor")
    names = [check["name"] for check in payload["checks"]]
    assert "credential_store" in names
    assert "credential:xmlriver" in names
