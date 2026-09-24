from __future__ import annotations

import typer

from .. import output
from ..core import services
from ..core.cache import ResponseCache, help_line, human_size
from ..core.errors import InvalidArguments

app = output.group(f"Журнал всех ответов провайдеров (он же кэш для --cache).\n\n{help_line()}")


@app.command("info")
@output.guard
def info(
    ctx: typer.Context,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Размер журнала, число записей, самая старая и новая, разбивка по провайдерам."""
    stats = ResponseCache().stats()
    output.emit_success(
        ctx,
        stats.model_dump(mode="json"),
        render_human=lambda d: output.human.key_values(
            "Журнал ответов",
            {
                "файл": d["path"],
                "размер": human_size(d["file_size"]),
                "записей": d["entries"],
                "самая старая": d["oldest"] or "—",
                "самая новая": d["newest"] or "—",
                "по провайдерам": ", ".join(f"{k}: {v}" for k, v in d["by_provider"].items()) or "—",
            },
        ),
    )


@app.command("list")
@output.guard
def list_entries(
    ctx: typer.Context,
    query: str | None = typer.Option(None, "--query", "-q", help="Только записи, где запрос содержит этот текст."),
    limit: int = typer.Option(50, "--limit", "-n", min=1, help="Сколько последних записей показать."),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Последние записи журнала (без самих ответов), свежие первыми.

    --json: {"ok": true, "count": N, "results": [{id, fetched_at, provider,
    freq_type, region, query, total_value, size}, ...]}; size — сжатый размер
    ответа.
    """
    rows = [e.model_dump(mode="json") for e in ResponseCache().entries(query=query, limit=limit)]

    def render(_: dict) -> None:
        for r in rows:
            output.human.echo(
                f"{r['fetched_at'][:19]}  {r['provider']:<9} {r['freq_type']:<9} lr={r['region']:<6} "
                f"{r['total_value']:>9}  {r['query']}"
            )
        if not rows:
            output.human.echo("Журнал пуст.")

    output.emit_success(ctx, {"count": len(rows), "results": rows}, render_human=render)


@app.command("clear")
@output.guard
def clear(
    ctx: typer.Context,
    older_than: str | None = typer.Option(None, "--older-than", help="Удалить записи старше срока: 30m, 12h, 7d, 2w."),
    all_entries: bool = typer.Option(False, "--all", help="Удалить весь журнал."),
    dry_run: bool = output.DryRunOption,
    confirm: bool = output.ConfirmOption,
    non_interactive: bool = output.NonInteractiveOption,
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
) -> None:
    """Удалить записи журнала: старше срока (--older-than) или все (--all).

    Необратимо: сначала --dry-run (покажет, сколько удалится), затем
    --confirm (обязателен вместе с --non-interactive).

    --json: {"ok": true, "deleted": N} (при --dry-run — {"dry_run": true,
    "would_delete": N}).
    """
    if all_entries == (older_than is not None):
        raise InvalidArguments("Укажите ровно одно: --older-than <срок> или --all.")
    age = services.parse_age(older_than) if older_than else None
    journal = ResponseCache()
    count = journal.count_older(age)
    what = "все записи журнала" if age is None else f"записи журнала старше {older_than}"

    if output.is_dry_run(ctx):
        output.emit_success(
            ctx,
            {"dry_run": True, "would_delete": count},
            render_human=lambda d: output.human.echo(f"Будет удалено: {d['would_delete']} ({what})."),
        )
        return

    output.require_confirmation(ctx, f"Удалить {what} ({count} шт.)", confirm)
    deleted = journal.clear(age)
    output.emit_success(
        ctx, {"deleted": deleted}, render_human=lambda d: output.human.echo(f"Удалено записей: {d['deleted']}.")
    )
