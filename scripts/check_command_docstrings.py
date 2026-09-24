#!/usr/bin/env python3
"""Warn (never block) when a command function's logic changed in this commit
without its docstring changing too.

Every command function's docstring is what Typer renders as `--help` text —
part of this CLI's AI-facing API contract (see architecture.md, "AI-first
output"). It is easy to edit a command's body without noticing the --help
text it emits is now stale. This is advisory only: it never fails the
commit, it just prints a reminder to stderr.

Installed via scripts/install_hooks.sh (`.git/hooks/` isn't versioned by
git, so re-run that script after cloning or if hooks go missing).
"""

from __future__ import annotations

import ast
import subprocess
import sys


def _staged_command_files() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [path for path in result.stdout.splitlines() if "/commands/" in path and path.endswith(".py")]


def _read(rev: str, path: str) -> str | None:
    result = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def _functions(source: str) -> dict[str, tuple[str | None, str]]:
    """Map function name -> (docstring, normalized body excluding the docstring)."""
    tree = ast.parse(source)
    functions: dict[str, tuple[str | None, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        docstring = ast.get_docstring(node)
        body = node.body[1:] if docstring is not None else node.body
        functions[node.name] = (docstring, "\n".join(ast.dump(stmt) for stmt in body))
    return functions


def main() -> int:
    stale: list[str] = []

    for path in _staged_command_files():
        staged_source = _read("", path)  # "" + ":" + path == ":path" == the staged (index) blob
        if staged_source is None:
            continue
        try:
            new_funcs = _functions(staged_source)
        except SyntaxError:
            continue

        head_source = _read("HEAD", path)
        old_funcs = _functions(head_source) if head_source is not None else {}

        for name, (doc, body) in new_funcs.items():
            old = old_funcs.get(name)
            if old is None:
                if doc is None:
                    stale.append(f"{path}:{name} — new function, no docstring for --help")
                continue
            old_doc, old_body = old
            if body != old_body and doc == old_doc:
                stale.append(f"{path}:{name} — logic changed, --help text did not")

    if stale:
        print("warning: possibly stale command docstrings (--help text agents rely on):", file=sys.stderr)
        for item in stale:
            print(f"  - {item}", file=sys.stderr)
        print("  (warning only — commit is not blocked)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
