"""The credential store: save, read and delete a provider's secrets in the system keyring, or in environment variables
where no keyring exists.
"""

from __future__ import annotations

import json
import logging
import os
import re

import keyring
import keyring.errors
from keyring.backends import fail

from ..core.errors import CredentialStoreUnavailable
from ..core.version import cli_name

log = logging.getLogger(__name__)

# Everything this CLI stores or reads lives under its namespace — the command
# name (`cli_name`), not the Python package: keychain service
# "<namespace>:<provider>", env vars <NAMESPACE>_<PROVIDER>_<FIELD> (`serp` ->
# SERP_XMLRIVER_API_KEY even though the package is rb_serp). Another tool's
# namespace can be read too (`Provider.shared_namespaces`), never written.
NAMESPACE = cli_name()

# A "credential" is a small dict of named fields stored as one JSON blob per
# provider in the OS keychain. `provider` is whatever identifies the
# credential in this CLI's domain: a service name ("openai"), a target
# site/host for a deploy/publish tool ("example.com"), a machine/profile
# name, etc. One field ("api_key") covers the common case; multiple fields
# cover session-based auth (cookies + csrf token) or host credentials
# (username + password) — nothing is special-cased for either shape.


def _service_name(provider: str, namespace: str = NAMESPACE) -> str:
    return f"{namespace}:{provider}"


def _env_var_name(provider: str, field: str, namespace: str = NAMESPACE) -> str:
    # Anything that isn't a letter or digit becomes "_", so per-target names
    # ("deploy:example.com") and dashed commands still give a settable name:
    # SITEMAP_XML_DEPLOY_EXAMPLE_COM_API_KEY.
    return re.sub(r"[^A-Z0-9]", "_", f"{namespace}_{provider}_{field}".upper())


# keyring can't list what it holds, so the names of stored credentials are
# kept in one more keychain entry. `auth status` reads it to find every
# stored target of a per-target provider ("deploy:example.com", ...).
_INDEX_USER = "__stored_credentials__"


def stored_names() -> list[str]:
    """Names of credentials stored in the keychain by this CLI (env-only ones aren't listed)."""
    try:
        raw = keyring.get_password(NAMESPACE, _INDEX_USER)
    except keyring.errors.KeyringError:
        return []
    return sorted(json.loads(raw)) if raw else []


def _update_index(provider: str, *, present: bool) -> None:
    names = set(stored_names())
    names = names | {provider} if present else names - {provider}
    try:
        keyring.set_password(NAMESPACE, _INDEX_USER, json.dumps(sorted(names)))
    except keyring.errors.KeyringError as exc:  # the credential itself is stored; only listing suffers
        log.warning("could not update the stored-credentials index (%s)", exc)


def read_fields_from_env(provider: str, fields: list[str]) -> dict[str, str]:
    """Read whichever of `fields` are set as env vars for this provider.

    Env var name: <NAMESPACE>_<PROVIDER>_<FIELD>, e.g. MYCLI_OPENAI_API_KEY.
    """
    result: dict[str, str] = {}
    for field in fields:
        value = os.environ.get(_env_var_name(provider, field))
        if value is not None:
            result[field] = value
    return result


# Set on the first keychain failure in this process (headless Linux, CI): the
# env-var path must keep working, and a server that supplies every key through
# env shouldn't log about it on each lookup. Logged once at DEBUG; a WARNING
# only when a field then turns out to be missing everywhere (_locate).
_keychain_problem: str | None = None
_warned_missing = False


def _stored(provider: str, namespace: str = NAMESPACE) -> dict[str, str]:
    global _keychain_problem
    try:
        stored_raw = keyring.get_password(_service_name(provider, namespace), provider)
    except keyring.errors.KeyringError as exc:
        if _keychain_problem is None:
            _keychain_problem = str(exc)
            log.debug("OS credential store unavailable (%s); using environment variables only", exc)
        return {}
    return json.loads(stored_raw) if stored_raw else {}


def get_credential(
    provider: str,
    *,
    env_fields: list[str] | None = None,
    legacy_env: dict[str, str] | None = None,
    legacy_env_first: bool = False,
    shared_namespaces: tuple[str, ...] = (),
) -> dict[str, str] | None:
    """Resolve the full credential bag for a provider.

    Env vars win field-by-field over what's stored in the keychain, so CI
    can override a single field (e.g. a rotated token) without touching the
    rest. `env_fields` lets a multi-field provider (session cookies, host
    credentials, ...) declare its field names explicitly, so env vars are
    checked even before anything has ever been stored. The other keyword
    arguments mirror the `Provider` attributes of the same names (see
    `locate_fields` for the order); providers call `Provider.credential()`.
    """
    stored = _stored(provider)
    fields = env_fields or list(stored.keys()) or ["api_key"]
    located = _locate(provider, fields, legacy_env, legacy_env_first, shared_namespaces, stored)
    merged = {**stored, **{field: value for field, (value, _, _) in located.items()}}
    return merged or None


def locate_fields(
    provider: str,
    fields: list[str],
    *,
    legacy_env: dict[str, str] | None = None,
    legacy_env_first: bool = False,
    shared_namespaces: tuple[str, ...] = (),
) -> dict[str, tuple[str, str, str]]:
    """Map each present field to (value, source "env" | "keychain", where: the env var or keychain service).

    Order per field, first hit wins:
    1. env var `<NAMESPACE>_<PROVIDER>_<FIELD>`, then the same for each shared namespace;
    2. keychain `<namespace>:<provider>`, own namespace first, then shared ones;
    3. the field's legacy env var (`legacy_env`) — or right after 1 with
       `legacy_env_first` (for a tool whose users still set only the old name
       while a stale keychain entry exists).
    For `auth status`, which reports the source and must never print the value.
    """
    return _locate(provider, fields, legacy_env, legacy_env_first, shared_namespaces, _stored(provider))


def _locate(
    provider: str,
    fields: list[str],
    legacy_env: dict[str, str] | None,
    legacy_env_first: bool,
    shared_namespaces: tuple[str, ...],
    own_stored: dict[str, str],
) -> dict[str, tuple[str, str, str]]:
    namespaces = (NAMESPACE, *shared_namespaces)
    stored = {NAMESPACE: own_stored, **{ns: _stored(provider, ns) for ns in shared_namespaces}}
    located: dict[str, tuple[str, str, str]] = {}
    for field in fields:
        env_names = [_env_var_name(provider, field, ns) for ns in namespaces]
        legacy = [(legacy_env or {})[field]] if field in (legacy_env or {}) else []
        env_first = env_names + legacy if legacy_env_first else env_names
        for name in env_first:
            if (value := os.environ.get(name)) is not None:
                located[field] = (value, "env", name)
                break
        else:
            for ns in namespaces:
                if field in stored[ns]:
                    located[field] = (stored[ns][field], "keychain", _service_name(provider, ns))
                    break
            else:
                for name in [] if legacy_env_first else legacy:
                    if (value := os.environ.get(name)) is not None:
                        located[field] = (value, "env", name)
    _warn_if_keychain_mattered(provider, [field for field in fields if field not in located])
    return located


def _warn_if_keychain_mattered(provider: str, missing: list[str]) -> None:
    global _warned_missing
    if missing and _keychain_problem is not None and not _warned_missing:
        _warned_missing = True
        log.warning(
            "OS credential store unavailable (%s) and %s not set in the environment for '%s'",
            _keychain_problem,
            ", ".join(missing),
            provider,
        )


def env_var_name(provider: str, field: str, namespace: str = NAMESPACE) -> str:
    return _env_var_name(provider, field, namespace)


def keychain_service(provider: str, namespace: str = NAMESPACE) -> str:
    return _service_name(provider, namespace)


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
# their own commands/auth flow.


def get_secret(provider: str, field: str = "api_key") -> str | None:
    credential = get_credential(provider, env_fields=[field])
    return credential.get(field) if credential else None


def store_secret(provider: str, secret: str, field: str = "api_key") -> None:
    store_credential(provider, {field: secret})


def read_secret_from_env(provider: str, field: str = "api_key") -> str | None:
    return read_fields_from_env(provider, [field]).get(field)


def delete_secret(provider: str) -> None:
    delete_credential(provider)
