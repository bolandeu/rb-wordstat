# Rendered by copier from the `dist_name` answer: the [project] name in
# pyproject.toml (standard §10: `rb-<slug>`), which may differ from this
# import package's name. importlib.metadata finds this package's version,
# summary and console script by it; an editable install (`uv sync`) can't be
# mapped from package to distribution at runtime, so it is written down here.
# tests/test_cli.py fails if it drifts from pyproject.toml.
DIST_NAME = "rb-wordstat"
# The previous distribution name during a rename (standard §10): an install made
# under it (not yet reinstalled) still finds its own version. Drop it once
# every machine has the new name.
DIST_NAME_LEGACY: str | None = None
# The command name (`cli_name`) as an identifier: the namespace of this tool's
# shared-database names (core/db.py) — table prefix `<TOOL>_`, env var
# `<TOOL>_DATABASE_URL`, Alembic table `alembic_version_<TOOL>`. Written down,
# not derived at runtime: a bare source run falls back to the package name,
# and a table name must never depend on how the tool was started.
TOOL = "wordstat"
# The cli-generator release this project was generated or last updated from
# (copier's `_commit`), for `describe --json`; None for a project not made by copier.
TEMPLATE_VERSION: str | None = "v1.5.0"
