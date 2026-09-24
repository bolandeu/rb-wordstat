from __future__ import annotations

import typer

from .. import output
from ..core.errors import InvalidArguments
from ..credentials import manager as credentials
from ..providers import provider_class, providers_help

app = output.group("Доступы к провайдерам (ключи в связке ключей ОС).")

ProviderOption = typer.Option("xmlriver", "--provider", help=f"Провайдер. Доступны: {providers_help()}.")


@app.command("login")
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
    """
    fields = provider_class(provider).credential_fields
    values = credentials.read_fields_from_env(provider, list(fields))
    missing = [field for field in fields if not values.get(field)]
    if missing and (ctx.obj.get("non_interactive") or non_interactive):
        env_names = ", ".join(f"WORDSTAT_{provider.upper()}_{field.upper()}" for field in missing)
        raise InvalidArguments(f"Missing {env_names} in the environment and --non-interactive was set.")
    for field in missing:
        values[field] = typer.prompt(f"{provider} {field}", hide_input=field != "user")
    credentials.store_credential(provider, values)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Stored credential for '{d['provider']}'."),
    )


@app.command("logout")
@output.guard
def logout(
    ctx: typer.Context,
    provider: str = ProviderOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить доступы провайдера из связки ключей ОС."""
    provider_class(provider)
    credentials.delete_credential(provider)
    output.emit_success(
        ctx,
        {"provider": provider},
        render_human=lambda d: output.human.echo(f"Removed credential for '{d['provider']}'."),
    )


@app.command("status")
@output.guard
def auth_status(
    ctx: typer.Context,
    provider: str = ProviderOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Проверить, что все доступы провайдера есть (в env или связке ключей)."""
    authenticated = provider_class(provider).load_credential() is not None
    output.emit_success(
        ctx,
        {"provider": provider, "authenticated": authenticated},
        render_human=lambda d: output.human.echo(
            f"{'Authenticated' if d['authenticated'] else 'Not authenticated'} for '{d['provider']}'."
        ),
    )
