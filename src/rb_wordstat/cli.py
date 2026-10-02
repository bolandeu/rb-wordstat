from __future__ import annotations

import io
import sys
from importlib import resources

import typer
from typer import rich_utils

from . import output
from .commands import auth, db, describe, doctor, init, search, skill, status
from .commands import cache as cache_cmd
from .commands import config as config_cmd
from .core.cache import help_line as cache_help_line
from .core.version import DEV_VERSION, cli_name, installed_version, package_summary

_PACKAGE_NAME = __name__.split(".")[0]

# A bare `<cli>` is the discovery entry point for humans and agents alike:
# name + version + description, then every command with the first line of
# its docstring. No `no_args_is_help` (that exits 2) — main_options() below
# prints this and exits 0. Shell completion stays enabled.
# Заголовки справки Typer — по-русски. «Usage:» и «Show this message and exit.»
# зашиты во встроенный в Typer Click и остаются как есть.
rich_utils.ARGUMENTS_PANEL_TITLE = "Аргументы"
rich_utils.OPTIONS_PANEL_TITLE = "Параметры"
rich_utils.COMMANDS_PANEL_TITLE = "Команды"
rich_utils.DEFAULT_STRING = "[по умолчанию: {}]"
rich_utils.REQUIRED_LONG_STRING = "[обязательный]"

app = typer.Typer(
    add_completion=False,
    help=f"{cli_name()} {installed_version() or DEV_VERSION} — {package_summary() or 'частоты Яндекс.Wordstat'}"
    f"\n\n{cache_help_line()}",
)

app.add_typer(config_cmd.app, name="config")
app.add_typer(auth.app, name="auth")  # `auth status` in every CLI; login/logout only with credentials
app.add_typer(skill.app, name="skill")
app.add_typer(cache_cmd.app, name="cache")
app.add_typer(db.app, name="db")

app.command(name="init")(init.init)
app.command(name="status")(status.status)
app.command(name="doctor")(doctor.doctor)
app.command(name="search")(search.search)
app.command(name="describe")(describe.describe)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(installed_version() or DEV_VERSION)
    raise typer.Exit()


def _ai_callback(value: bool) -> None:
    """Print the bundled agent skill doc to stdout.

    For agents that can execute this CLI but cannot read files from disk
    (e.g. a sandboxed shell with no access to a SKILL.md on the filesystem),
    this is the fallback way to get full usage guidance.
    """
    if not value:
        return
    content = resources.files(f"{_PACKAGE_NAME}.data").joinpath("SKILL.md").read_text(encoding="utf-8")
    typer.echo(content)
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_options(
    ctx: typer.Context,
    project: str = typer.Option(None, "--project", help="Путь к корню проекта (иначе ищется вверх от текущей папки)."),
    json_output: bool = typer.Option(False, "--json", help="Машиночитаемый вывод: JSON в stdout."),
    quiet: bool = typer.Option(False, "--quiet", help="Не печатать ничего, кроме данных."),
    verbose: bool = typer.Option(False, "--verbose", help="Подробная диагностика в stderr."),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="Никогда не спрашивать; при нехватке данных — ошибка."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Показать, что будет сделано, ничего не меняя."),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Показать версию и выйти."
    ),
    ai: bool = typer.Option(
        False,
        "--ai",
        callback=_ai_callback,
        is_eager=True,
        help="Напечатать памятку для AI-агентов (SKILL.md) и выйти.",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    ctx.obj["json"] = json_output
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose
    ctx.obj["non_interactive"] = non_interactive
    ctx.obj["dry_run"] = dry_run
    output.configure_logging(verbose)
    output.help_if_no_command(ctx)


def use_utf8_stdio() -> None:
    """Вывод всегда в UTF-8: в pipe Windows по умолчанию пишет в cp1252 и падает на кириллице."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8")


def main() -> None:
    use_utf8_stdio()
    app()


if __name__ == "__main__":
    main()
