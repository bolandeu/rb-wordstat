from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import typer
from rich.table import Table

from .. import output
from ..core import services
from ..core.models import FreqType, WordstatEntry, WordstatResult
from ..providers import providers_help


class CsvMode(StrEnum):
    auto = "auto"
    freq = "freq"
    keywords = "keywords"


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _when(result: WordstatResult) -> str:
    """От какого числа данные (местное время) и откуда: живой запрос или журнал."""
    if result.fetched_at is None:
        return ""
    when = result.fetched_at.astimezone().strftime("%d.%m.%Y %H:%M")
    return f"{when}, из журнала" if result.from_cache else when


def _keywords_table(title: str, entries: list[WordstatEntry]) -> None:
    if not entries:
        return
    table = Table(show_header=True, header_style="bold green", title=title)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Запрос", overflow="fold")
    table.add_column("Частота", justify="right", width=10)
    for i, entry in enumerate(entries, 1):
        table.add_row(str(i), entry.text, _num(entry.value))
    output.human.console.print(table)


def _render(results: list[WordstatResult], show_keywords: bool) -> None:
    console = output.human.console
    by_query: dict[str, list[WordstatResult]] = {}
    for r in results:
        by_query.setdefault(r.query, []).append(r)
    for query, rows in by_query.items():
        console.rule(f"[bold]{query}[/bold]")
        if len(rows) == 1:
            when = _when(rows[0])
            console.print(
                f"[bold]Частота ({rows[0].freq_type.label}):[/bold] [yellow]{_num(rows[0].total_value)}[/yellow]"
                + (f" [dim]· данные от {when}[/dim]" if when else "")
            )
        else:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Тип", width=18)
            table.add_column("Оператор", width=40, overflow="fold")
            table.add_column("Частота", justify="right", width=12)
            table.add_column("Данные от", style="dim")
            for r in rows:
                table.add_row(r.freq_type.label, r.freq_type.apply(r.query), _num(r.total_value), _when(r))
            console.print(table)
        broad = next((r for r in rows if r.freq_type == FreqType.broad), None)
        if show_keywords and broad:
            _keywords_table("Похожие запросы", broad.popular)
            _keywords_table("Ассоциации", broad.associations)


@output.guard
def search(
    ctx: typer.Context,
    queries: list[str] = typer.Argument(..., help="Один или несколько запросов."),
    freq: list[str] = typer.Option(
        ["broad"],
        "--freq",
        "-f",
        help="Тип(ы) частоты: broad, phrase, exact, exact-ord, all. Повторять флаг или через запятую.",
    ),
    lr: int = typer.Option(213, "--lr", help="Код региона Яндекса: 213=Москва, 2=СПб, 35=Краснодар, 65=Новосибирск."),
    provider: str | None = typer.Option(
        None,
        "--provider",
        "-p",
        help="Очередь провайдеров через запятую: первый основной, остальные фолбэки. "
        f"Доступны: {providers_help()}. По умолчанию — `providers` из конфига проекта, иначе xmlriver.",
    ),
    output_path: Path | None = typer.Option(
        None, "--output", "-o", help="Дополнительно сохранить в файл: .csv — таблица (см. --csv-mode), иначе JSON."
    ),
    csv_mode: CsvMode = typer.Option(
        CsvMode.auto,
        "--csv-mode",
        help="CSV: freq — query|freq_type|freq_label|operator|total_value; keywords — "
        "source_query|type|keyword|value из похожих и ассоциаций (только broad); auto — freq при нескольких "
        "типах частоты, иначе keywords.",
    ),
    no_keywords: bool = typer.Option(False, "--no-keywords", help="В консоли только частоты, без похожих запросов."),
    cache: bool = typer.Option(
        False,
        "--cache",
        help="Взять ответ из журнала, если такой запрос (провайдер, тип частоты, регион, текст) уже был — "
        "бесплатно. Только ответы провайдеров из --provider, в порядке очереди. Без флага — всегда живой "
        "запрос. Ответы пишутся в журнал всегда.",
    ),
    max_age: str | None = typer.Option(
        None, "--max-age", help="С --cache: брать из журнала, только если запись не старше срока: 30m, 12h, 7d, 2w."
    ),
    force: bool = typer.Option(
        False, "--force", help="Всегда живой запрос, даже с --cache; новый ответ станет актуальным."
    ),
    json_output: bool = output.JsonOption,
    quiet: bool = output.QuietOption,
    verbose: bool = output.VerboseOption,
) -> None:
    """Частоты Яндекс.Wordstat и похожие запросы / ассоциации.

    Каждая пара (запрос, тип частоты) запрашивается параллельно; провайдеры
    пробуются по порядку из --provider, пока один не ответит. Отказали все →
    PROVIDER_ERROR (exit 5) или AUTH_REQUIRED (exit 3) — частота 0 значит
    только «запрос не ищут», не сбой. Похожие запросы и ассоциации приходят с
    типом broad.

    Каждый ответ провайдера пишется в журнал (`wordstat cache`); с --cache
    повторный запрос берётся оттуда бесплатно.

    --json: {"ok": true, "count": N, "results": [{query, freq_type,
    total_value, popular: [{text, value}], associations: [...], provider,
    fetched_at, from_cache}, ...]} (+ "saved_to" при --output).

    \b
    Примеры:
      wordstat search "купить диван"
      wordstat search "купить диван" --freq all --no-keywords
      wordstat search "диван" "кресло" --freq broad,phrase --lr 2
      wordstat search "купить диван" -p xmlstock,xmlriver   # xmlriver — фолбэк
      wordstat search "купить диван" --freq all --output freq.csv
      wordstat search "купить диван" --output keywords.csv --csv-mode keywords
      wordstat search "купить диван" --cache --max-age 7d   # из журнала, если свежее недели
      wordstat search "купить диван" --json

    Example: {cli} search "купить диван" --freq all --json
    """
    freq_types = services.resolve_freq(freq)
    providers = services.resolve_providers(provider, Path(ctx.obj.get("project") or Path.cwd()))
    output.vecho(ctx, f"Провайдеры: {', '.join(providers)}")
    results = services.search(
        queries,
        freq=freq_types,
        lr=lr,
        providers=providers,
        use_cache=cache and not force,
        max_age=services.parse_age(max_age) if max_age else None,
    )

    payload: dict = {"count": len(results), "results": [r.model_dump(mode="json") for r in results]}
    if output_path is not None:
        services.save_results(results, output_path, csv_mode=services.csv_mode_for(csv_mode.value, freq_types))
        payload["saved_to"] = str(output_path)

    def render(_: dict) -> None:
        _render(results, show_keywords=not no_keywords)
        if output_path is not None:
            output.human.console.print(f"[green]Сохранено в {output_path}[/green]")

    output.emit_success(ctx, payload, render_human=render)
