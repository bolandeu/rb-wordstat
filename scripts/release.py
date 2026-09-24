#!/usr/bin/env python3
"""Cut a release: bump the version, date the CHANGELOG, commit, tag, push.

    uv run scripts/release.py patch|minor|major

After this, `uv tool install "git+<repo>@v<version>"` pins that exact
release on any machine, and `uv tool upgrade <cli>` picks it up on machines
that installed from the default branch. Refuses to run on a dirty tree or
off `main` — a release is a statement about what's on `main`, nothing else.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
UNRELEASED = "## [Unreleased]"


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def fail(message: str) -> None:
    print(f"release: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    part = sys.argv[1] if len(sys.argv) == 2 else ""
    if part not in ("patch", "minor", "major"):
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    if run("git", "status", "--porcelain", capture=True):
        fail("working tree is not clean — commit or stash first")
    if run("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True) != "main":
        fail("releases are cut from main")

    run("uv", "version", "--bump", part)  # rewrites pyproject.toml and uv.lock
    version = run("uv", "version", "--short", capture=True)
    tag = f"v{version}"

    if CHANGELOG.is_file():
        text = CHANGELOG.read_text()
        if UNRELEASED not in text:
            fail(f"{CHANGELOG.name} has no '{UNRELEASED}' section")
        today = datetime.date.today().isoformat()
        CHANGELOG.write_text(text.replace(UNRELEASED, f"{UNRELEASED}\n\n## [{version}] - {today}", 1))

    run("git", "add", "pyproject.toml", "uv.lock", CHANGELOG.name)
    run("git", "commit", "-m", f"Release {tag}")
    run("git", "tag", "-a", tag, "-m", tag)
    run("git", "push", "--follow-tags")
    print(f'Released {tag}. Pin it anywhere with: uv tool install "git+<repo-url>@{tag}"')


if __name__ == "__main__":
    main()
