from __future__ import annotations

import json
import logging
import os
import re

import keyring
import keyring.errors
from keyring.backends import fail

from ..core.errors import CredentialStoreUnavailable
from ..core.version import CLI_NAME

# Префикс — wordstat, а не имя пакета rb_wordstat: keychain wordstat:*, env WORDSTAT_*.
_PACKAGE_NAME = CLI_NAME
# Доступы XML River / XMLStock общие с CLI serp: поле, которого нет у wordstat,
# берётся из записей serp (env SERP_<PROVIDER>_<FIELD>, keychain serp:<provider>).
# Порядок по каждому полю: WORDSTAT_* → keychain wordstat: → SERP_* → keychain serp: → legacy env.
SHARED_NAMESPACES = ("serp",)
log = logging.getLogger(__name__)

# A "credential" is a small dict of named fields stored as one JSON blob per
# provider in the OS keychain. `provider` is whatever identifies the
# credential in this CLI's domain: a service name ("openai"), a target
# site/host for a deploy/publish tool ("example.com"), a machine/profile
# name, etc. One field ("api_key") covers the common case; multiple fields
# cover session-based auth (cookies + csrf token) or host credentials
# (username + password) — nothing is special-cased for either shape.


def _service_name(provider: str, namespace: str = _PACKAGE_NAME) -> str:
    return f"{namespace}:{provider}"


def _env_var_name(provider: str, field: str, namespace: str = _PACKAGE_NAME) -> str:
    # Anything that isn't a letter or digit becomes "_", so per-target names
    # ("deploy:example.com") still give a settable name: MYCLI_DEPLOY_EXAMPLE_COM_API_KEY.
    return re.sub(r"[^A-Z0-9]", "_", f"{namespace}_{provider}_{field}".upper())


# keyring can't list what it holds, so the names of stored credentials are
# kept in one more keychain entry. `auth status` reads it to find every
# stored target of a per-target provider ("deploy:example.com", ...).
_INDEX_USER = "__stored_credentials__"


def stored_names() -> list[str]:
    """Names of credentials stored in the keychain by this CLI (env-only ones aren't listed)."""
    try:
        raw = keyring.get_password(_PACKAGE_NAME, _INDEX_USER)
    except keyring.errors.KeyringError:
        return []
    return sorted(json.loads(raw)) if raw else []


def _update_index(provider: str, *, present: bool) -> None:
    names = set(stored_names())
    names = names | {provider} if present else names - {provider}
    try:
        keyring.set_password(_PACKAGE_NAME, _INDEX_USER, json.dumps(sorted(names)))
    except keyring.errors.KeyringError as exc:  # the credential itself is stored; only listing suffers
        log.warning("could not update the stored-credentials index (%s)", exc)


def read_fields_from_env(provider: str, fields: list[str]) -> dict[str, str]:
    """Read whichever of `fields` are set as env vars for this provider.

    Env var name: <PACKAGE>_<PROVIDER>_<FIELD>, e.g. MYCLI_OPENAI_API_KEY.
    """
    result: dict[str, str] = {}
    for field in fields:
        value = os.environ.get(_env_var_name(provider, field))
        if value is not None:
            result[field] = value
    return result


def _stored(provider: str, namespace: str = _PACKAGE_NAME) -> dict[str, str]:
    try:
        stored_raw = keyring.get_password(_service_name(provider, namespace), provider)
    except keyring.errors.KeyringError as exc:
        # A missing/locked keychain (headless Linux, CI) must not block the
        # env-var path — that's the whole point of having a fallback.
        log.warning("OS credential store unavailable (%s); using environment variables only", exc)
        return {}
    return json.loads(stored_raw) if stored_raw else {}


def get_credential(
    provider: str, *, env_fields: list[str] | None = None, legacy_env: dict[str, str] | None = None
) -> dict[str, str] | None:
    """Resolve the full credential bag for a provider.

    Env vars win field-by-field over what's stored in the keychain, so CI
    can override a single field (e.g. a rotated token) without touching the
    rest. `env_fields` lets a multi-field provider (session cookies, host
    credentials, ...) declare its field names explicitly, so env vars are
    checked even before anything has ever been stored. `legacy_env` maps a
    field to an older env var name still honoured (`Provider.legacy_env`).
    Fields this CLI doesn't have come from `SHARED_NAMESPACES` (serp).
    """
    stored = _stored(provider)
    fields = env_fields or list(stored.keys()) or ["api_key"]
    located = _locate(provider, fields, legacy_env, stored)
    merged = {**stored, **{field: value for field, (value, _, _) in located.items()}}
    return merged or None


def locate_fields(
    provider: str, fields: list[str], *, legacy_env: dict[str, str] | None = None
) -> dict[str, tuple[str, str, str]]:
    """Map each present field to (value, source "env" | "keychain", where: the env var or keychain service).

    Precedence per field: `WORDSTAT_<PROVIDER>_<FIELD>` env var, the
    `wordstat:<provider>` keychain entry, then the same pair of each shared
    namespace (`SERP_*`, `serp:<provider>`), then the field's legacy env var
    (`legacy_env`). Empty values count as absent. For `auth status`, which
    reports the source and must never print the value — and for providers
    loading their credential, so both always agree.
    """
    return _locate(provider, fields, legacy_env, _stored(provider))


def _locate(
    provider: str, fields: list[str], legacy_env: dict[str, str] | None, stored: dict[str, str]
) -> dict[str, tuple[str, str, str]]:
    located: dict[str, tuple[str, str, str]] = {}
    for namespace in (_PACKAGE_NAME, *SHARED_NAMESPACES):
        if all(field in located for field in fields):
            break
        # Чужую связку ключей читаем, только если своих полей не хватило.
        bag = stored if namespace == _PACKAGE_NAME else _stored(provider, namespace)
        for field in fields:
            if field in located:
                continue
            env_name = _env_var_name(provider, field, namespace)
            if value := os.environ.get(env_name):
                located[field] = (value, "env", env_name)
            elif value := bag.get(field):
                located[field] = (value, "keychain", _service_name(provider, namespace))
    for field, env_name in (legacy_env or {}).items():
        if field in fields and field not in located and (value := os.environ.get(env_name)):
            located[field] = (value, "env", env_name)
    return located


def env_var_name(provider: str, field: str) -> str:
    return _env_var_name(provider, field)


def keychain_service(provider: str) -> str:
    return _service_name(provider)


def shared_env_var_names(provider: str, field: str) -> list[str]:
    """Env vars of the shared namespaces for this field (SERP_*), in lookup order."""
    return [_env_var_name(provider, field, namespace) for namespace in SHARED_NAMESPACES]


def shared_keychain_services(provider: str) -> list[str]:
    return [_service_name(provider, namespace) for namespace in SHARED_NAMESPACES]


def store_backend() -> str | None:
    """Name of the active keyring backend, or None when there's no usable one.

    `keyring` falls back to its `fail` backend on a machine without a
    secret service (headless Linux, some containers) — reads and writes
    then raise, and only env vars can supply credentials. `doctor` reports
    this so it isn't discovered from a confusing `auth login` failure.
    """
    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring):
        return None
    return f"{type(backend).__module__}.{type(backend).__name__}"


def store_credential(provider: str, fields: dict[str, str]) -> None:
    try:
        keyring.set_password(_service_name(provider), provider, json.dumps(fields))
    except keyring.errors.KeyringError as exc:
        raise CredentialStoreUnavailable(provider, str(exc)) from exc
    _update_index(provider, present=True)


def delete_credential(provider: str) -> None:
    try:
        keyring.delete_password(_service_name(provider), provider)
    except keyring.errors.PasswordDeleteError:
        pass  # already absent — deleting a missing credential is not an error
    except keyring.errors.KeyringError as exc:
        raise CredentialStoreUnavailable(provider, str(exc)) from exc
    _update_index(provider, present=False)


# Convenience wrappers for the common single-secret case (most providers
# only ever need one API key). Multi-field providers should use
# get_credential/store_credential/read_fields_from_env directly instead, in
# their own commands/auth flow — see architecture.md.


def get_secret(provider: str, field: str = "api_key") -> str | None:
    credential = get_credential(provider, env_fields=[field])
    return credential.get(field) if credential else None


def store_secret(provider: str, secret: str, field: str = "api_key") -> None:
    store_credential(provider, {field: secret})


def read_secret_from_env(provider: str, field: str = "api_key") -> str | None:
    return read_fields_from_env(provider, [field]).get(field)


def delete_secret(provider: str) -> None:
    delete_credential(provider)
