"""The credential store of this CLI: `rb-credentials` bound to the command's namespace.

The resolution itself — the keychain, the `<NAMESPACE>_<PROVIDER>_<FIELD>` variables, the stored-names index —
lives in the shared package; this module only fixes the namespace and maps the library's errors onto this CLI's.
"""

from __future__ import annotations

from collections.abc import Mapping

try:  # the tests patch this module's functions; the resolution itself lives in rb-credentials
    import keyring
except ModuleNotFoundError:  # the keyring extra is absent: environment variables only
    keyring = None  # type: ignore[assignment]

from rb_credentials import Store, StoreUnavailable

from ..core.errors import CredentialStoreUnavailable
from ..core.version import cli_name

# Everything this CLI stores or reads lives under its namespace — the command
# name (`cli_name`), not the Python package: keychain service
# "<namespace>:<provider>", env vars <NAMESPACE>_<PROVIDER>_<FIELD>.
NAMESPACE = cli_name()

_STORE = Store(NAMESPACE)
# One Store per set of shared namespaces: its state (the "warn once about the keychain" flag) must survive
# between calls, exactly as the module-level equivalent did.
_SHARED: dict[tuple[str, ...], Store] = {}


def _store(shared_namespaces: tuple[str, ...] = ()) -> Store:
    if not shared_namespaces:
        return _STORE
    if shared_namespaces not in _SHARED:
        _SHARED[shared_namespaces] = Store(NAMESPACE, shared_namespaces=shared_namespaces)
    return _SHARED[shared_namespaces]


def stored_names() -> list[str]:
    """Names of the credentials stored in the keychain by this CLI (env-only ones are not listed)."""
    return _STORE.stored_names()


def read_fields_from_env(provider: str, fields: list[str]) -> dict[str, str]:
    """Whichever of `fields` are set as env vars for this provider."""
    return _STORE.read_from_env(provider, fields)


def get_credential(
    provider: str,
    *,
    env_fields: list[str] | None = None,
    legacy_env: Mapping[str, str] | None = None,
    legacy_env_first: bool = False,
    shared_namespaces: tuple[str, ...] = (),
) -> dict[str, str] | None:
    """The full credential bag of a provider: environment first, then the keychain, field by field."""
    return _store(shared_namespaces).get(
        provider, env_fields=env_fields, legacy_env=legacy_env, legacy_env_first=legacy_env_first
    )


def locate_fields(
    provider: str,
    fields: list[str],
    *,
    legacy_env: Mapping[str, str] | None = None,
    legacy_env_first: bool = False,
    shared_namespaces: tuple[str, ...] = (),
) -> dict[str, tuple[str, str, str]]:
    """Per present field: (value, source "env"|"keychain", where). For `auth status`, never the value."""
    return _store(shared_namespaces).locate(provider, fields, legacy_env=legacy_env, legacy_env_first=legacy_env_first)


def env_var_name(provider: str, field: str, namespace: str = NAMESPACE) -> str:
    return Store(namespace).env_var_name(provider, field)


def keychain_service(provider: str, namespace: str = NAMESPACE) -> str:
    return Store(namespace).service_name(provider)


def store_backend() -> str | None:
    """Name of the active keyring backend, or None when only the environment can supply secrets."""
    return _STORE.backend()


def store_credential(provider: str, fields: dict[str, str]) -> None:
    try:
        _STORE.store(provider, fields)
    except StoreUnavailable as exc:
        raise CredentialStoreUnavailable(provider, str(exc)) from exc


def delete_credential(provider: str) -> None:
    try:
        _STORE.delete(provider)
    except StoreUnavailable as exc:
        raise CredentialStoreUnavailable(provider, str(exc)) from exc


def get_secret(provider: str, field: str = "api_key") -> str | None:
    return _STORE.get_secret(provider, field)


def store_secret(provider: str, secret: str, field: str = "api_key") -> None:
    try:
        _STORE.store_secret(provider, secret, field)
    except StoreUnavailable as exc:
        raise CredentialStoreUnavailable(provider, str(exc)) from exc


def read_secret_from_env(provider: str, field: str = "api_key") -> str | None:
    return _STORE.read_secret_from_env(provider, field)


def delete_secret(provider: str) -> None:
    delete_credential(provider)
