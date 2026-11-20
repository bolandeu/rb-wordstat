# AGENTS.md

- Decisions and why: `docs/adr/` (format: `docs/adr/README.md`).
- The package Standard: https://github.com/bolandeu/python-package-gate/blob/main/skills/cli-builder/reference/standard.md (sections by name, for example «Install»).
- The gate before a commit: `gate check`, on this machine (Standard, CI). It is the only gate: no workflow runs it.

## Architect only

A worker does not need this section: Antagor cuts it from the worker's brief.

## Package notes

**A command that may take more than a couple of minutes runs detached —
only through `scripts/run_detached.sh <label> <command...>`, then poll
`scripts/runs_status.sh <label>` (`--json` for the exit code and the
output tails).** Any command: the gate, `scripts/pg_test.sh`, a long
`wordstat` run. Run in the agent's own shell, it dies with the turn
— an interrupt (an incoming herdr message is one) kills it and the work
is redone. The detached run has its own session; its pid, output
(`<label>.log`), errors (`<label>.stderr`) and exit code (`<label>.exit`)
are in the tool's state dir (`runs/`); `python3 scripts/detach.py stop
<label>` ends it.

## Architecture (do not violate)

- `commands/` — argument parsing only. No business logic here.
- `core/` — services, models, errors. All real logic lives here.
- `providers/` — Wordstat providers, one module per service, each a
  `providers.WordstatProvider` subclass registered in `providers.PROVIDERS`
  (`name`, `summary`, `url`, `_params`, `_api_error`, `_parse`). The base
  class owns HTTP, retries, the timeout and mapping every vendor failure to
  `AuthRequired` / `ProviderError` — that is what `WordstatClient` switches
  to the next provider in the queue on, per (query, freq type) pair.
  `_api_error` / `_parse` are classmethods so journal entries parse without
  credentials. The response journal (`core/cache.py`, table `wordstat_responses`
  in the tool's database, append-only, every raw answer, read only with `--cache`) lives in `WordstatClient`
  (`--provider a,b`, project `providers = [...]`, default `["xmlriver"]`).
  Tests inject `httpx.MockTransport` via the provider's `transport`
  argument. Never call `httpx` from `core/` or `commands/`.
  `WordstatProvider` subclasses the template's `providers.base.Provider`
  (`abstract = True`), so `all_providers()` finds every provider and
  `auth status` reports it. Each sets `required` (`xmlriver` yes, `xmlstock`
  no) and implements `health_check()` through `balance_url` /
  `_balance_params` / `_parse_balance`: the free balance request, one try,
  10 s (`tests/test_providers.py` fails without it). `auth status --check
  --json` runs those checks; its JSON shape is a cross-tool contract pinned
  by `tests/test_auth.py` — changing it is a breaking change.
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
- Data goes through `core/db.py` (cli-generator `architecture.md` §12).
  `WORDSTAT_DATABASE_URL` → the shared PostgreSQL, else local SQLite
  (`WORDSTAT_DB_PATH` moves the file). Caches go there too; anything kept local
  instead is listed here, with the reason.
  Tables, views, indexes: `wordstat_*` only, declared in `core/tables.py`
  and created by a hand-written migration in `migrations/versions/`.
  Other tools read only the `wordstat_v1_*` views — a new shape is a `_v2_`
  view plus a Service map entry. Every view is declared in `tables.py`
  `views` (typed columns with `comment=`) — `wordstat describe --json`
  publishes it as the data contract; every table has
  `info={"kind": "data" | "cache"}`. Cross-tool keys: `core/normalize.py`,
  stored next to the original text. Every migration must keep working
  with the previous release (expand/contract); the shared base is
  migrated only by `wordstat db upgrade` from a release. Every table
  has a single-column PRIMARY KEY (a surrogate `id`; Directus supports
  no other kind) and its natural key as UNIQUE. PostgreSQL tests: only via
  `scripts/pg_test.sh` (own container, Docker-assigned port, removed after)
  — never a fixed port or another tool's server. Append-only
  tables with a unique natural key can be marked `info={"push": ...}` for
  `wordstat db push` (local SQLite → `WORDSTAT_PROD_DATABASE_URL`).

## Names

Python package `rb_wordstat` (distribution `rb-wordstat`), but everything a user
sees is `wordstat`: the command, `WORDSTAT_<PROVIDER>_<FIELD>` env vars, keychain
entries `wordstat:<provider>`, the `.wordstat/` project dir (unlike the
template, which prefixes them with the package name — kept so stored
credentials survive). Credentials are shared with the sibling `serp` CLI:
per field, `WORDSTAT_*` → keychain `wordstat:` → `SERP_*` → keychain `serp:` →
legacy `XMLRIVER_*` (`credentials.manager.SHARED_NAMESPACES`, `locate_fields`;
servers pass keys as `SERP_*`). Providers and `auth status` both resolve through
`locate_fields`, so they always agree. Names: `core/version.py` `CLI_NAME`
(prefix) and `cli_name()` (the command), `_distribution.DIST_NAME` — use
those, never `__name__.split(".")[0]`, for anything user-facing.

## Library API

`rb_wordstat` is also imported as a library (`from rb_wordstat import WordstatClient,
WordstatParams, WordstatResult, WordstatEntry, FreqType`, plus `AuthRequired` /
`ProviderError`): `await WordstatClient(providers=[...]).search(params)` or `.search_sync(...)`.
Keep these names and signatures stable — other projects depend on them.
Logging is stdlib `logging` (logger `rb_wordstat`), never `print`.

## After changing the command surface

Agents discover commands from a bare `wordstat` / `--help`,
rendered from the command docstrings and `help=` strings — so the
docstring *is* the API doc. **Changed a command's behaviour → update its
docstring in the same commit**:

- docstring = one-line summary, optional paragraph, and an
  `Example: {cli} <command> ...` line (`output.guard` turns `{cli}` into
  `wordstat`); every `typer.Option`/`Argument` has `help=`;
- then `uv run pytest --snapshot-update` and read the diff in
  `tests/snapshots/help/` and `tests/snapshots/describe.json` — that diff
  is the user-visible change (`describe --json` is the machine-readable
  contract the tools catalog and the platform read).

Enforced by `tests/test_help.py` and the docstring check in the project's `checks`. `src/rb_wordstat/data/SKILL.md`
deliberately lists no commands, only conventions; touch it only if a
convention changes (a new exit code, a new credential rule).

## Inside the tools system

This tool is one service among many; the root `~/Work/tools/` agent
deploys it, keeps its credentials (секрет-менеджер) and backs up its data (S3).
Full rules: `~/Work/tools/docs/standard-release.md` §13.

- **Nobody here pushes; releases and questions go through the root agent**,
  never straight to the user in this window. Release or branch ready →
  `~/Work/tools/scripts/agent_say.sh tools "<repo, branch, tags, what's
  inside, gate result, the red run, changed existing tests
  with reasons>"`, one message per tag. The root
  agent checks it and queues it for dev; dev shows the user and pushes
  after their yes; then the root agent installs it on the Mac and the
  homeserver. Don't push yourself; force-push and `commit --amend` never.
  A question or decision for the user → the same channel, briefly: the
  question, the options, your recommendation; meanwhile do whatever doesn't
  depend on the answer.
- **Only the root agent goes to production.** Run nothing against it:
  no `db push` (not even `--dry-run`), no reads through
  `*_PROD_DATABASE_URL`, no ssh to the server. Need a check on production →
  send the root agent the exact command; it runs it and returns the output.
  A local throwaway database (`scripts/pg_test.sh`) is yours.
- **Nothing around the root agent.** Tasks come from it. Don't give
  instructions to other agents (other tools, sysadmin, dev, windmill, ...)
  and change nothing outside this repository. A bug or a request for
  another tool or the infrastructure → a message to the root agent
  (`~/Work/tools/scripts/agent_say.sh tools "..."`); it decides and passes
  it on.

- **Report to the root agent** (in the report to the user, next to the
  release tag): a new or renamed env var / credential, a new local database
  or changed data path, a new or dropped dependency on another tool, a
  refreshed token written back locally, a breaking release.
- **Consumers**: before a breaking change, check who uses this tool (root
  `AGENTS.md` → Service map) and name them in the report.
- **Headless Linux servers**: env vars first, keychain optional (a missing
  keychain is not an error when the env var is set); reuse existing env var
  names; no prompts without a TTY; no Mac-only paths.
- **Data** lives in the shared PostgreSQL (`WORDSTAT_DATABASE_URL`)
  or the local SQLite in `platformdirs.user_data_dir("<tool>")`, never in
  the repo; it moves between them only through `db import-sqlite` and
  `db push` (cli-generator `architecture.md` §12).
