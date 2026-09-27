from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest

from rb_wordstat import providers
from rb_wordstat.core.errors import AuthRequired, ProviderError
from rb_wordstat.credentials import health
from rb_wordstat.credentials import manager as credentials
from rb_wordstat.providers import Health, Provider, Quota, XmlRiverProvider

from .test_cli import invoke, invoke_json

PKG = "wordstat"  # keychain service and env prefix: wordstat, not the package name (see core/version.py)
PREFIX = PKG.upper()
GOOD, BAD = "good-secret-123", "bad-secret-456"


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

    monkeypatch.setattr(credentials.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(credentials.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(credentials.keyring, "delete_password", fake_delete_password)
    return store


# --- test providers: a required API key one, an optional two-field one ----------


class Demo(Provider):
    """A provider with no transport at all: health_check() decides from the credential."""

    name = "demo"
    path = "/me"  # "/down" simulates the service being unreachable
    expires_at: datetime | None = None

    def health_check(self) -> Health:
        credential = credentials.get_credential(
            self.credential_name, env_fields=list(self.credential_fields), legacy_env=self.legacy_env
        )
        if self.path == "/down":
            raise ProviderError(self.name, "ConnectError while calling GET /me")
        if (credential or {}).get("api_key") != GOOD:
            raise AuthRequired(self.name)
        return Health(expires_at=self.expires_at, quota=Quota(remaining=42))


class Extra(Demo):
    name = "extra"
    required = False
    credential_fields = ("user", "api_key")


@pytest.fixture
def demo_providers(monkeypatch: pytest.MonkeyPatch, fake_keyring):
    monkeypatch.setattr(providers, "all_providers", lambda: [Demo, Extra])
    monkeypatch.setattr(Demo, "path", "/me")
    monkeypatch.setattr(Demo, "expires_at", None)
    return fake_keyring


def env(demo: str | None = None, extra: str | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    if demo is not None:
        values[f"{PREFIX}_DEMO_API_KEY"] = demo
    if extra is not None:
        values |= {f"{PREFIX}_EXTRA_USER": "me", f"{PREFIX}_EXTRA_API_KEY": extra}
    return values


def status(*args: str, **values: str | None) -> tuple[int, dict, str]:
    result = invoke("auth", "status", *args, "--json", env=env(**values))
    assert GOOD not in result.output and BAD not in result.output, "a credential value leaked into the output"
    return result.exit_code, json.loads(result.stdout), result.output


def by_provider(payload: dict) -> dict[str, dict]:
    return {entry["provider"]: entry for entry in payload["credentials"]}


# --- the §8 shape: changing any of this is a breaking change ---------------------

TOP_KEYS = ["ok", "tool", "version", "checked_at", "credentials"]
ENTRY_KEYS = ["provider", "required", "fields", "source", "source_ref", "status", "expires_at", "quota", "message"]
SOURCES = {"env", "keychain", "file", "missing"}
STATUSES = {"ok", "missing", "invalid", "expired", "quota_exhausted", "unreachable", "unchecked"}


@pytest.mark.parametrize("args", [(), ("--check",)])
def test_report_shape_is_the_cross_tool_contract(demo_providers, args: tuple[str, ...]) -> None:
    _, payload, _ = status(*args, demo=GOOD)
    assert [k for k in payload if k != "error"] == TOP_KEYS
    assert payload["tool"] == "wordstat"
    assert isinstance(payload["version"], str)
    assert datetime.fromisoformat(payload["checked_at"].replace("Z", "+00:00")).tzinfo is not None
    assert payload["checked_at"].endswith("Z")
    for entry in payload["credentials"]:
        assert list(entry) == ENTRY_KEYS
        assert isinstance(entry["required"], bool)
        assert all(isinstance(field, str) for field in entry["fields"])
        assert entry["source"] in SOURCES
        assert entry["status"] in STATUSES
        assert entry["quota"] is None or set(entry["quota"]) == {"remaining", "limit", "unit"}


def test_presence_only_without_check(demo_providers) -> None:
    code, payload, _ = status(demo=GOOD)
    demo = by_provider(payload)["demo"]
    assert (code, payload["ok"], demo["status"], demo["source"]) == (0, True, "unchecked", "env")
    assert demo["source_ref"] == f"{PREFIX}_DEMO_API_KEY"
    assert by_provider(payload)["extra"]["status"] == "missing"  # optional: reported, not a problem


def test_missing_required_is_exit_3(demo_providers) -> None:
    code, payload, _ = status()
    demo = by_provider(payload)["demo"]
    assert (code, demo["status"], demo["source"]) == (3, "missing", "missing")
    assert f"{PREFIX}_DEMO_API_KEY" in demo["source_ref"] and "keychain" in demo["source_ref"]
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CREDENTIALS_UNHEALTHY"
    assert list(by_provider(payload)) == ["demo", "extra"]


def test_check_ok(demo_providers) -> None:
    code, payload, _ = status("--check", demo=GOOD)
    demo = by_provider(payload)["demo"]
    assert (code, demo["status"], demo["message"]) == (0, "ok", None)
    assert demo["quota"] == {"remaining": 42, "limit": None, "unit": "requests"}


def test_check_invalid_is_exit_3(demo_providers) -> None:
    code, payload, _ = status("--check", demo=BAD)
    assert (code, by_provider(payload)["demo"]["status"]) == (3, "invalid")


def test_invalid_optional_is_still_a_problem(demo_providers) -> None:
    code, payload, _ = status("--check", demo=GOOD, extra=BAD)
    assert (code, by_provider(payload)["extra"]["status"]) == (3, "invalid")
    code, payload, _ = status("--check", demo=GOOD, extra=GOOD)
    assert (code, by_provider(payload)["extra"]["status"]) == (0, "ok")


def test_unreachable_counts_only_for_required(demo_providers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Demo, "path", "/down")  # Extra inherits it
    code, payload, _ = status("--check", demo=GOOD, extra=GOOD)
    assert code == 3
    assert {e["status"] for e in payload["credentials"]} == {"unreachable"}
    monkeypatch.setattr(providers, "all_providers", lambda: [Extra])
    code, _, _ = status("--check", extra=GOOD)
    assert code == 0


def test_check_timeout_is_unreachable(demo_providers, monkeypatch: pytest.MonkeyPatch) -> None:
    # The 10 s limit is the provider's client timeout (HttpProvider.probe);
    # hitting it surfaces as ProviderError, which auth status reports as unreachable.
    def timed_out(self) -> Health:
        raise ProviderError(self.name, f"ReadTimeout after {health.CHECK_TIMEOUT:g} s while calling GET /me")

    monkeypatch.setattr(Demo, "health_check", timed_out)
    code, payload, _ = status("--check", demo=GOOD)
    demo = by_provider(payload)["demo"]
    assert (code, demo["status"]) == (3, "unreachable")
    assert "ReadTimeout" in demo["message"]


def test_past_expiry_is_expired(demo_providers, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Demo, "expires_at", datetime.now(UTC) - timedelta(minutes=1))
    code, payload, _ = status("--check", demo=GOOD)
    demo = by_provider(payload)["demo"]
    assert (code, demo["status"]) == (3, "expired")
    assert demo["expires_at"].endswith("Z")


def test_error_messages_are_scrubbed(demo_providers, monkeypatch: pytest.MonkeyPatch) -> None:
    def leaky(self) -> Health:
        raise RuntimeError(f"boom with {credentials.get_secret('demo')}")

    monkeypatch.setattr(Demo, "health_check", leaky)
    _, payload, _ = status("--check", demo=BAD)  # status() itself asserts no leak
    assert "***" in by_provider(payload)["demo"]["message"]


def test_keychain_and_mixed_sources(demo_providers) -> None:
    credentials.store_credential("demo", {"api_key": GOOD})
    credentials.store_credential("extra", {"user": "me", "api_key": GOOD})
    _, payload, _ = status("--check", extra=None)
    entries = by_provider(payload)
    assert (entries["demo"]["source"], entries["demo"]["status"]) == ("keychain", "ok")
    assert entries["demo"]["source_ref"] == f"keychain service {PKG}:demo"

    result = invoke("auth", "status", "--json", env={f"{PREFIX}_EXTRA_API_KEY": GOOD})
    extra = by_provider(json.loads(result.stdout))["extra"]
    assert extra["source"] == "env"
    assert extra["source_ref"] == f"{PREFIX}_EXTRA_API_KEY; rest from keychain service {PKG}:extra"


def test_provider_filter_and_unknown_provider(demo_providers) -> None:
    code, payload, _ = status("--provider", "extra")
    assert (code, list(by_provider(payload))) == (0, ["extra"])
    code, payload, _ = status("--provider", "nope")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"


def test_human_output(demo_providers) -> None:
    result = invoke("auth", "status", env=env(demo=BAD))
    assert result.exit_code == 0
    assert "demo: unchecked (env:" in result.stdout
    assert "extra (optional): missing" in result.stdout
    assert BAD not in result.output


def test_no_providers_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers, "all_providers", lambda: [])
    code, payload = invoke_json("auth", "status")
    assert (code, payload["credentials"]) == (0, [])


# --- legacy env names -------------------------------------------------------------


class Legacy(Demo):
    name = "legacy"
    legacy_env: ClassVar[dict[str, str]] = {"api_key": "OLD_LEGACY_TOKEN"}


def test_legacy_env_name_is_a_source(monkeypatch: pytest.MonkeyPatch, fake_keyring) -> None:
    monkeypatch.setattr(providers, "all_providers", lambda: [Legacy])
    result = invoke("auth", "status", "--check", "--json", env={"OLD_LEGACY_TOKEN": GOOD})
    entry = by_provider(json.loads(result.stdout))["legacy"]
    assert (result.exit_code, entry["source"], entry["status"]) == (0, "env", "ok")
    assert entry["source_ref"] == "OLD_LEGACY_TOKEN"

    # the standard name wins over the legacy one
    both = {"OLD_LEGACY_TOKEN": BAD, f"{PREFIX}_LEGACY_API_KEY": GOOD}
    entry = by_provider(json.loads(invoke("auth", "status", "--check", "--json", env=both).stdout))["legacy"]
    assert (entry["source_ref"], entry["status"]) == (f"{PREFIX}_LEGACY_API_KEY", "ok")

    missing = by_provider(json.loads(invoke("auth", "status", "--json").stdout))["legacy"]
    assert "OLD_LEGACY_TOKEN" in missing["source_ref"]


# --- per-target providers: one entry per stored target --------------------------


class Deploy(Demo):
    name = "deploy"
    per_target = True


@pytest.fixture
def deploy_provider(monkeypatch: pytest.MonkeyPatch, fake_keyring):
    monkeypatch.setattr(providers, "all_providers", lambda: [Deploy])
    monkeypatch.setattr(Demo, "path", "/me")
    monkeypatch.setattr(Demo, "expires_at", None)
    return fake_keyring


def test_per_target_reports_each_stored_target(deploy_provider) -> None:
    credentials.store_credential("deploy:a.example.com", {"api_key": GOOD})
    credentials.store_credential("deploy:b.example.com", {"api_key": BAD})
    code, payload, _ = status("--check")
    entries = by_provider(payload)
    assert list(entries) == ["deploy:a.example.com", "deploy:b.example.com"]
    assert (entries["deploy:a.example.com"]["status"], entries["deploy:b.example.com"]["status"]) == ("ok", "invalid")
    assert entries["deploy:a.example.com"]["source_ref"] == f"keychain service {PKG}:deploy:a.example.com"
    assert code == 3

    code, payload, _ = status("--check", "--provider", "deploy:a.example.com")
    assert (code, list(by_provider(payload))) == (0, ["deploy:a.example.com"])

    credentials.delete_credential("deploy:b.example.com")
    assert list(by_provider(status()[1])) == ["deploy:a.example.com"]


def test_per_target_env_only_target_by_name(deploy_provider) -> None:
    target_env = {f"{PREFIX}_DEPLOY_C_EXAMPLE_COM_API_KEY": GOOD}
    result = invoke("auth", "status", "--check", "--provider", "deploy:c.example.com", "--json", env=target_env)
    entry = by_provider(json.loads(result.stdout))["deploy:c.example.com"]
    assert (result.exit_code, entry["source"], entry["status"]) == (0, "env", "ok")
    assert entry["source_ref"] == f"{PREFIX}_DEPLOY_C_EXAMPLE_COM_API_KEY"


def test_per_target_with_no_targets_is_missing(deploy_provider) -> None:
    code, payload, _ = status()
    entry = by_provider(payload)["deploy"]
    assert (code, entry["status"]) == (3, "missing")
    assert "deploy:<target>" in entry["message"]


# --- login / logout --------------------------------------------------------------


def xmlriver_entry(**env_values: str) -> tuple[int, dict]:
    result = invoke("auth", "status", "--provider", "xmlriver", "--json", env=env_values)
    return result.exit_code, by_provider(json.loads(result.stdout))["xmlriver"]


def test_auth_login_logout_round_trip(fake_keyring) -> None:
    assert xmlriver_entry()[1]["status"] == "missing"

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
    assert fake_keyring[("wordstat:xmlriver", "xmlriver")] == '{"user": "u", "token": "t"}'

    code, entry = xmlriver_entry()
    assert (code, entry["source"], entry["status"]) == (0, "keychain", "unchecked")
    assert entry["source_ref"] == "keychain service wordstat:xmlriver"

    assert invoke("auth", "logout", "--provider", "xmlriver").exit_code == 0
    assert xmlriver_entry()[1]["status"] == "missing"


# --- реальные провайдеры: xmlriver обязателен, xmlstock нет; ключи общие с serp ---


def test_real_providers_required_and_optional(fake_keyring) -> None:
    code, payload = invoke_json("auth", "status")
    entries = by_provider(payload)
    assert code == 3
    assert (entries["xmlriver"]["required"], entries["xmlriver"]["status"]) == (True, "missing")
    assert (entries["xmlstock"]["required"], entries["xmlstock"]["status"]) == (False, "missing")
    assert entries["xmlriver"]["fields"] == ["user", "token"]
    ref = entries["xmlriver"]["source_ref"]
    assert "WORDSTAT_XMLRIVER_USER (or SERP_XMLRIVER_USER, XMLRIVER_USER)" in ref
    assert ref.endswith("keychain service wordstat:xmlriver or serp:xmlriver")

    code, payload = invoke_json("auth", "status", env={"SERP_XMLRIVER_USER": "u", "SERP_XMLRIVER_TOKEN": "t"})
    assert code == 0  # xmlstock missing — optional, not a problem


def test_credential_order_wordstat_then_serp_then_legacy(fake_keyring) -> None:
    legacy = {"XMLRIVER_USER": "lu", "XMLRIVER_TOKEN": "lt"}
    serp_token = {"SERP_XMLRIVER_TOKEN": "st"}
    assert xmlriver_entry(**legacy)[1]["source_ref"] == "XMLRIVER_USER, XMLRIVER_TOKEN"

    fake_keyring[("serp:xmlriver", "xmlriver")] = '{"user": "ku", "token": "kt"}'
    entry = xmlriver_entry(**legacy)[1]
    assert (entry["source"], entry["source_ref"]) == ("keychain", "keychain service serp:xmlriver")

    entry = xmlriver_entry(**legacy, **serp_token)[1]
    assert (entry["source"], entry["source_ref"]) == (
        "env",
        "SERP_XMLRIVER_TOKEN; rest from keychain service serp:xmlriver",
    )

    fake_keyring[("wordstat:xmlriver", "xmlriver")] = '{"user": "wu"}'
    entry = xmlriver_entry(**legacy, **serp_token)[1]
    assert entry["source_ref"] == "SERP_XMLRIVER_TOKEN; rest from keychain service wordstat:xmlriver"

    entry = xmlriver_entry(**legacy, **serp_token, **{"WORDSTAT_XMLRIVER_TOKEN": "wt"})[1]
    assert entry["source_ref"] == "WORDSTAT_XMLRIVER_TOKEN; rest from keychain service wordstat:xmlriver"
    assert XmlRiverProvider.load_credential() is not None


def test_real_provider_check_uses_balance(fake_keyring, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(XmlRiverProvider, "health_check", lambda self: Health(quota=Quota(remaining=5, unit="rub")))
    code, entry = xmlriver_entry(WORDSTAT_XMLRIVER_USER="u", WORDSTAT_XMLRIVER_TOKEN=GOOD)
    assert (code, entry["status"]) == (0, "unchecked")
    result = invoke(
        "auth", "status", "--check", "--json", env={"WORDSTAT_XMLRIVER_USER": "u", "WORDSTAT_XMLRIVER_TOKEN": GOOD}
    )
    entry = by_provider(json.loads(result.stdout))["xmlriver"]
    assert (result.exit_code, entry["status"], entry["quota"]) == (
        0,
        "ok",
        {"remaining": 5, "limit": None, "unit": "rub"},
    )
    assert GOOD not in result.output


def test_env_var_works_when_keyring_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import keyring.errors

    def broken_get_password(service: str, username: str) -> str | None:
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(credentials.keyring, "get_password", broken_get_password)
    monkeypatch.setattr(providers, "all_providers", lambda: [Demo])
    code, payload, _ = status(demo=GOOD)
    assert (code, by_provider(payload)["demo"]["source"]) == (0, "env")


def test_doctor_reports_credential_checks(tmp_path: Path, fake_keyring) -> None:
    _, payload = invoke_json("--project", str(tmp_path), "doctor")
    names = [check["name"] for check in payload["checks"]]
    assert "credential_store" in names
    assert "credential:xmlriver" in names
