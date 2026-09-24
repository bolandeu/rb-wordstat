from __future__ import annotations

from importlib.metadata import PackageNotFoundError, metadata
from importlib.metadata import version as pkg_version

_PACKAGE_NAME = __name__.split(".")[0]

# Python-пакет называется rb_wordstat (дистрибутив rb-wordstat), а всё, что видит
# пользователь — команда, env WORDSTAT_*, keychain wordstat:*, папка .wordstat, — wordstat.
CLI_NAME = "wordstat"
DIST_NAME = "rb-wordstat"

DEV_VERSION = "0.0.0-dev"


def package_summary() -> str:
    """The one-line `description` from pyproject.toml, as installed."""
    try:
        return metadata(_PACKAGE_NAME)["Summary"] or ""
    except PackageNotFoundError:
        return ""


def installed_version() -> str | None:
    """Version of this package as installed, or None when it isn't installed at all.

    None only happens when the source tree is run without any install (not
    even `uv sync`'s editable one) — callers treat it as "dev build" and skip
    anything that would compare versions.
    """
    try:
        return pkg_version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return None
