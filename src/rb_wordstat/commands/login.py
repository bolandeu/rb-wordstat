"""`auth login` / `auth logout` — only in CLIs generated with credentials (include_auth).

`commands/auth.py` registers these into the `auth` group when this module
exists; `auth status` is there in every CLI (tools/docs/standard-release.md §8).
"""

from __future__ import annotations

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..credentials import manager as credentials
from ..providers import provider_class, providers_help

ProviderOption = typer.Option("xmlriver", "--provider", help=f"Провайдер. Доступны: {providers_help()}.")


@output.guard
def login(
    ctx: typer.Context,
    provider: str = ProviderOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Сохранить доступы провайдера в связку ключей ОС.

    Каждое поле берётся из переменной WORDSTAT_<PROVIDER>_<FIELD> (например
    WORDSTAT_XMLSTOCK_USER, WORDSTAT_XMLSTOCK_TOKEN), если она задана, иначе
    спрашивается. С --non-interactive недостающее поле — ошибка, а не вопрос.

    Example: {cli} auth login --provider xmlstock
    """
    fields = provider_class(provider).credential_fields
    values = credentials.read_fields_from_env(provider, list(fields))
    missing = [field for field in fields if not values.get(field)]
    if missing and (ctx.obj.get("non_interactive") or non_interactive):
        env_names = ", ".join(credentials.env_var_name(provider, field) for field in missing)
        raise InvalidArguments(f"Missing {env_names} in the environment and --non-interactive was set.")
    for field in missing:
        values[field] = typer.prompt(f"{provider} {field}", hide_input=field != "user")
    credentials.store_credential(provider, values)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Stored credential for '{d['provider']}'."),
    )


@output.guard
def logout(
    ctx: typer.Context,
    provider: str = ProviderOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить доступы провайдера из связки ключей ОС (записи serp не трогаются).

    Example: {cli} auth logout --provider xmlstock
    """
    provider_class(provider)
    credentials.delete_credential(provider)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Removed credential for '{d['provider']}'."),
    )
