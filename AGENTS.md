# AGENTS.md

Guidance for coding agents working on the **rb-wordstat** package (import `rb_wordstat`, command `wordstat`)
itself (not its end users — see `src/rb_wordstat/data/SKILL.md` for
that).

## Development

```bash
uv sync                          # also writes uv.lock — commit it
uv run wordstat --help
uv run scripts/release.py --check   # the whole gate — run it before every commit
```

**Before every commit, `uv run scripts/release.py --check` must pass.**
It is the authoritative gate (CI, if the repo keeps it, runs exactly this,
and every release runs it too): `uv lock --check`, ruff check + format,
ty, pytest (coverage floor, help contract + snapshots, `auth status`
shape), the list of existing tests changed since the last tag, a
changelog fragment for any change since the last tag, and a wheel build
installed into a throwaway venv where `wordstat --version` must
match the built version. A failure names the step and shows its output —
fix the cause, never skip the step.

**TDD is required, and checked** (user, 2026-10-02; `~/Work/dev/docs/testing.md`):

1. **Red first.** The test is committed before the code that makes it
   pass — git shows the order. Keep the failing run's output: it goes
   into the readiness report.
2. **A test is not edited to fit the code.** An existing test changes only
   when the requirement did. The gate's `existing tests` step lists every
   test the last release had that is now changed or gone; each one goes
   into the report with its reason — without one dev doesn't let the
   release through.
3. **The bar is set by others.** Acceptance scenarios are written by dev
   with the user, contract tests (`--json`, exit codes, `v1` views) by the
   consumer. You write the unit tests and pass everyone's — a contract
   test from a consumer is an existing test like any other.
4. **Mutation testing**, now and then and before a big release (not in
   the gate): `uv run --group mutation mutmut run`, then `mutmut results`
   / `mutmut browse` — a surviving mutant is a line no test really checks.

Run `scripts/install_hooks.sh` once per clone: it points git at the
versioned hooks in `.githooks/` (Claude Code sessions do this themselves
via `.claude/settings.json`). The pre-commit hook **blocks** a commit where
a command's logic changed but its docstring didn't, and warns when `src/`
changed with no changelog fragment on the branch.

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

## Releasing

- **Version = git tag.** There is no `version =` in `pyproject.toml`;
  uv-dynamic-versioning reads the latest `vX.Y.Z` tag at build time. Don't
  add one back, don't hard-code a version string anywhere.
- **Changelog = fragments.** Don't edit `CHANGELOG.md`. Every user-visible
  change adds one fragment:
  `uv run towncrier create +<slug>.<type>.md -c "One or two sentences."`
  (type: added/changed/deprecated/removed/fixed/security). CI fails a PR
  without one.
- **Release** from a clean, up-to-date `main`:
  `uv run scripts/release.py patch|minor|major` — gate, towncrier build,
  commit `Release vX.Y.Z`, annotated tag. It never pushes, and neither do
  you: report the release to the root agent (below). The report carries
  the red run of the new tests and every `existing tests` entry with its
  reason (Development, TDD).
- **Every user-visible change ships as a release.** Servers, other tools
  and the Mac install only from tags, never from `main`, so a merged change
  without a release is invisible to them. A change that needs a fragment is
  done only after the release: merge to `main`, run `release.py`, hand it
  to the root agent for the push, and name the new tag in the report.
  Maintenance-only commits (no fragment) wait for the next release. Don't
  leave a fragment unreleased on `main` without naming the reason.
- **SemVer is a promise about the CLI surface.** Removing/renaming/changing
  commands, flags, the `--json` shape, exit or error codes is breaking —
  major, or **minor while at `0.x`**. A new feature with old behaviour
  intact is minor (**patch while at `0.x`**); a fix is patch. Deprecate first
  (warning + a `deprecated` fragment), remove in the next breaking release.
- **Depending on another of our tools**: pin by tag in `[tool.uv.sources]`
  (`{ git = "...", tag = "vX.Y.Z" }`) with a compatible range in
  `dependencies` (`>=0.2,<0.3`) — never `branch = "main"`, never a
  committed `path =`. Bump = new tag + `uv lock --upgrade-package <name>`
  + full gate, one commit.

Projects pin the CLI they need via `[cli] min_version` in their config, so
a change a project depends on needs a release before that project can
require it.

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

Enforced: Claude Code hooks (`.claude/settings.json`: PostToolUse after
editing a command file, Stop before ending the turn), the pre-commit hook,
and `tests/test_help.py` in the gate. If a hook fires on a refactor that
truly doesn't change behaviour, say so — don't bypass it silently. `src/rb_wordstat/data/SKILL.md`
deliberately lists no commands, only conventions; touch it only if a
convention changes (a new exit code, a new credential rule).

## Inside the tools system

This tool is one service among many; the root `~/Work/tools/` agent
deploys it, keeps its credentials (Doppler) and backs up its data (S3).
Full rules: `~/Work/tools/docs/standard-release.md` §13.

- **Nobody here pushes; releases and questions go through the root agent**,
  never straight to the user in this window. Release or branch ready →
  `~/Work/tools/scripts/agent_say.sh tools "<repo, branch, tags, what's
  inside, release.py --check result, the red run, changed existing tests
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
