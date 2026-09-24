# AGENTS.md

Guidance for coding agents working on the **rb-wordstat** package (import `rb_wordstat`, command `wordstat`)
itself (not its end users — see `src/rb_wordstat/data/SKILL.md` for
that).

## Development

```bash
uv sync                          # also writes uv.lock — commit it (CI runs `uv lock --check`)
uv run wordstat --help
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Before calling anything done, that last line must pass — it's exactly
what CI runs on Linux/macOS/Windows, followed by `uv tool install .` to
prove the package still installs as a tool.

Run `scripts/install_hooks.sh` once (`.git/hooks/` isn't versioned by git,
so this is also needed again after a fresh clone). It installs a
pre-commit hook that warns — never blocks — when a command's logic changed
without its docstring changing too, since that docstring is the `--help`
text agents read as this CLI's API contract.

## Architecture (do not violate)

- `commands/` — argument parsing only. No business logic here.
- `core/` — services, models, errors. All real logic lives here.
- `providers/` — Wordstat providers, one module per service, each a
  `providers.WordstatProvider` subclass registered in `providers.PROVIDERS`
  (`name`, `summary`, `url`, `_params`, `_api_error`, `_parse`). The base
  class owns HTTP, retries, the timeout and mapping every vendor failure to
  `AuthRequired` / `ProviderError` — that is what `WordstatClient` switches
  to the next provider in the queue on, per (query, freq type) pair
  (`--provider a,b`, project `providers = [...]`, default `["xmlriver"]`).
  Tests inject `httpx.MockTransport` via the provider's `transport`
  argument. Never call `httpx` from `core/` or `commands/`.
- `credentials/` — secrets via OS keychain + env vars. Never write a secret
  to `.wordstat/config.toml` or any other project-local file.
- `output/` — every command supports both human and `--json` output via
  `output.emit_success` / `output.guard`. Don't `print()` directly in a
  command. stdout is data only; errors, `--verbose` progress and `logging`
  go to stderr.
- Command groups are created with `output.group("...")`, not
  `typer.Typer(...)` — that's what makes `wordstat <group>` with
  no subcommand print help (exit 0) instead of a usage error.
- Errors are `CliError` subclasses with a stable `code` and the fixed
  exit-code table (see `core/errors.py`). Don't raise bare exceptions as the
  intended user-facing failure path.
- Any new command that changes external state irreversibly (deletes,
  overwrites a remote resource, restarts something, ...) must support
  `--dry-run` (`output.is_dry_run`) and gate the actual action behind
  `output.require_confirmation`. Commands that only touch local project
  files (`init`, `config set`) don't need this.

## Names

Python package `rb_wordstat` (distribution `rb-wordstat`), but everything a user
sees is `wordstat`: the command, `WORDSTAT_<PROVIDER>_<FIELD>` env vars, keychain
entries `wordstat:<provider>`, the `.wordstat/` project dir. Credentials are
shared with the sibling `serp` CLI: `WordstatProvider.load_credential` falls
back to its entries (`SERP_*`, keychain `serp:<provider>`) — the same XML
River / XMLStock account serves both tools. That split lives in
`core/version.py` (`CLI_NAME`, `DIST_NAME`) — use those, never
`__name__.split(".")[0]`, for anything user-facing.

## Library API

`rb_wordstat` is also imported as a library (`from rb_wordstat import WordstatClient,
WordstatParams, WordstatResult, WordstatEntry, FreqType`, plus `AuthRequired` /
`ProviderError`): `await WordstatClient(providers=[...]).search(params)` or `.search_sync(...)`.
Keep these names and signatures stable — other projects depend on them.
Logging is stdlib `logging` (logger `rb_wordstat`), never `print`.

## Releasing

Never edit `version =` in `pyproject.toml` by hand. Add a line under
`## [Unreleased]` in `CHANGELOG.md` with each change, and when it should
ship run `uv run scripts/release.py patch|minor|major` from a clean
`main` — it bumps the version, dates the changelog, commits, tags
`v<version>` and pushes. Projects pin the CLI they need via
`[cli] min_version` in their config, so a change a project depends on
needs a release before that project can require it.

## After changing the command surface

Nothing to update by hand: agents discover commands from a bare
`wordstat` / `--help`, which is rendered from the command
docstrings — so the docstring *is* the API doc, keep it accurate (the
pre-commit hook warns when it drifts). `src/rb_wordstat/data/SKILL.md`
deliberately lists no commands, only conventions; touch it only if a
convention changes (a new exit code, a new credential rule).
