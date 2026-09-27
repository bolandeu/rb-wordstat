"""Other CLIs this one shells out to, and the minimum version of each it needs.

A tool that calls another tool's CLI (instead of importing it as a package
pinned by tag) can't rely on the lock file, so it checks at runtime:

    exe = deps.require_cli("serp", "0.3.0", install_url="https://github.com/bolandeu/serp")
    subprocess.run([exe, "search", ...])

A missing or too old CLI fails with DEPENDENCY_TOO_OLD (exit 1) naming what is
installed, what is needed and how to fix it — not with a confusing error from
deep inside the other tool. See tools/docs/standard-release.md §5.
"""

from __future__ import annotations

import shutil
import subprocess

from packaging.version import InvalidVersion, Version

from .errors import DependencyTooOld

VERSION_TIMEOUT = 10.0


def installed_cli_version(name: str) -> tuple[str | None, str | None]:
    """(path, version) of CLI `name` on PATH; (None, None) when it isn't installed."""
    exe = shutil.which(name)
    if exe is None:
        return None, None
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, executable resolved via shutil.which
            [exe, "--version"], capture_output=True, text=True, timeout=VERSION_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return exe, None
    lines = result.stdout.strip().splitlines()
    return exe, (lines[-1].strip() if result.returncode == 0 and lines else None)


def require_cli(name: str, min_version: str, *, install_url: str | None = None) -> str:
    """Path of CLI `name` if it's installed at `min_version` or newer; raise DependencyTooOld otherwise.

    `install_url` (the other tool's git repo, e.g. "https://github.com/bolandeu/serp")
    makes the error's `action` a runnable `uv tool install "git+<url>@v<min_version>"`;
    without it the action says what to install but gives no URL (never a placeholder).

    A dev build of the other tool (version `0.0.0…`, no release tag in reach)
    is accepted, the same way this CLI's own `cli.min_version` check treats it.
    """
    exe, reported = installed_cli_version(name)
    if exe is None:
        raise DependencyTooOld(name, None, min_version, install_url=install_url)
    try:
        version = Version(reported or "")
    except InvalidVersion:
        raise DependencyTooOld(name, reported or "unknown", min_version, install_url=install_url) from None
    if version.release != (0, 0, 0) and version < Version(min_version):
        raise DependencyTooOld(name, reported, min_version, install_url=install_url)
    return exe
