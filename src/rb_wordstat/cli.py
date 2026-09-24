from __future__ import annotations

import csv
import json
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from .core.client import WordstatClient
from .core.models import ALL_FREQ_TYPES, FreqType, WordstatParams, WordstatResult

console = Console()

_FREQ_CHOICES = ["broad", "phrase", "exact", "exact-ord", "all"]
_FREQ_MAP = {
    "broad": FreqType.broad,
    "phrase": FreqType.phrase,
    "exact": FreqType.exact,
    "exact-ord": FreqType.exact_ord,
}


def _resolve_freq(values: tuple[str, ...]) -> list[FreqType]:
    # Поддержка --freq broad,phrase и --freq broad --freq phrase
    expanded: list[str] = []
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                expanded.append(part)

    invalid = [v for v in expanded if v not in _FREQ_CHOICES]
    if invalid:
        raise click.BadParameter(
            f"Недопустимые значения: {', '.join(invalid)}. "
            f"Допустимые: {', '.join(_FREQ_CHOICES)}"
        )

    if "all" in expanded:
        return ALL_FREQ_TYPES

    seen: list[FreqType] = []
    for v in expanded:
        ft = _FREQ_MAP[v]
        if ft not in seen:
            seen.append(ft)
    return seen or [FreqType.broad]


# ─── Console output ───────────────────────────────────────────────────────────

def _print_freq_table(query_results: list[WordstatResult]) -> None:
    """Таблица частот для одного запроса (несколько freq_type)."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Тип", width=18)
    table.add_column("Оператор", width=40, overflow="fold")
    table.add_column("Частота", justify="right", width=12)

    for r in query_results:
        table.add_row(
            r.freq_type.label,
            r.freq_type.apply(r.query),
            f"{r.total_value:,}".replace(",", "\u00a0"),
        )
    console.print(table)


def _print_keywords_table(title: str, entries: list) -> None:
    if not entries:
        return
    table = Table(show_header=True, header_style="bold green", title=title)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Запрос", overflow="fold")
    table.add_column("Частота", justify="right", width=10)

    for i, entry in enumerate(entries, 1):
        table.add_row(str(i), entry.text, f"{entry.value:,}".replace(",", "\u00a0"))
    console.print(table)


def _output_table(results: list[WordstatResult], show_keywords: bool = True) -> None:
    by_query: dict[str, list[WordstatResult]] = {}
    for r in results:
        by_query.setdefault(r.query, []).append(r)

    for query, qresults in by_query.items():
        console.rule(f"[bold]{query}[/bold]")

        if len(qresults) == 1:
            r = qresults[0]
            console.print(
                f"[bold]Частота ({r.freq_type.label}):[/bold] "
                f"[yellow]{r.total_value:,}[/yellow]".replace(",", "\u00a0")
            )
        else:
            _print_freq_table(qresults)

        if show_keywords:
            broad = next((r for r in qresults if r.freq_type == FreqType.broad), None)
            if broad:
                _print_keywords_table("Похожие запросы", broad.popular)
                _print_keywords_table("Ассоциации", broad.associations)


# ─── File output ──────────────────────────────────────────────────────────────

def _save_json(results: list[WordstatResult], path: Path) -> None:
    data = [r.model_dump() for r in results]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[green]Сохранено в {path}[/green]")


def _save_csv_freq(results: list[WordstatResult], path: Path) -> None:
    """Сводная таблица частот: одна строка на запрос × freq_type."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "freq_type", "freq_label", "operator", "total_value"])
        for r in results:
            writer.writerow([
                r.query,
                r.freq_type.value,
                r.freq_type.label,
                r.freq_type.apply(r.query),
                r.total_value,
            ])
    console.print(f"[green]Сохранено в {path}[/green]")


def _save_csv_keywords(results: list[WordstatResult], path: Path) -> None:
    """Таблица ключевых слов из popular + associations (только broad)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source_query", "type", "keyword", "value"])
        for r in results:
            if r.freq_type != FreqType.broad:
                continue
            for entry in r.popular:
                writer.writerow([r.query, "popular", entry.text, entry.value])
            for entry in r.associations:
                writer.writerow([r.query, "assoc", entry.text, entry.value])
    console.print(f"[green]Сохранено в {path}[/green]")


# ─── CLI ──────────────────────────────────────────────────────────────────────

@click.group()
def main() -> None:
    """rb-wordstat — снятие частот и парсинг Яндекс.Wordstat."""
    load_dotenv()


@main.command()
@click.argument("queries", nargs=-1, required=True)
@click.option(
    "--freq", "-f",
    multiple=True,
    type=str,
    default=("broad",),
    show_default=True,
    help=(
        "Тип(ы) частоты. Можно повторять или через запятую: "
        "broad, phrase, exact, exact-ord, all. "
        "Пример: --freq broad,phrase или --freq broad --freq phrase."
    ),
)
@click.option(
    "--lr",
    default=213,
    show_default=True,
    type=int,
    help="Код региона Яндекса. 213=Москва, 2=СПб, 35=Краснодар, 65=Новосибирск.",
)
@click.option(
    "--format", "-F", "fmt",
    default="table",
    show_default=True,
    type=click.Choice(["table", "json"]),
    help="Формат вывода в консоль.",
)
@click.option(
    "--output", "-o",
    default=None,
    type=click.Path(),
    help=(
        "Сохранить результаты в файл. "
        ".json — полные данные, "
        ".csv — частоты (freq) или ключевые слова (keywords)."
    ),
)
@click.option(
    "--csv-mode",
    default="auto",
    type=click.Choice(["auto", "freq", "keywords"]),
    show_default=True,
    help=(
        "Режим CSV. auto: freq при >1 типах, keywords при только broad. "
        "freq: query|freq_type|total_value. "
        "keywords: source_query|type|keyword|value из popular/assoc."
    ),
)
@click.option(
    "--no-keywords",
    is_flag=True,
    default=False,
    help="Не показывать в консоли похожие запросы и ассоциации. Только частоты.",
)
def search(
    queries: tuple[str, ...],
    freq: tuple[str, ...],
    lr: int,
    fmt: str,
    output: str | None,
    csv_mode: str,
    no_keywords: bool,
) -> None:
    """Снять частоты и/или собрать похожие запросы.

    Примеры:

    \b
      wordstat search "купить диван"
      wordstat search "купить диван" --freq all
      wordstat search "купить диван" --freq broad,phrase,exact
      wordstat search "диван" "кресло" "стол" --freq broad,phrase --lr 2
      wordstat search "купить диван" --freq all --no-keywords
      wordstat search "купить диван" --output results.json
      wordstat search "купить диван" --freq all --output freq.csv
      wordstat search "купить диван" --output keywords.csv --csv-mode keywords
    """
    try:
        freq_types = _resolve_freq(freq)
    except click.BadParameter as e:
        raise click.ClickException(str(e))

    # Предупреждение: keywords CSV без broad
    if output and Path(output).suffix.lower() == ".csv":
        effective_mode = csv_mode
        if effective_mode == "auto" and len(freq_types) == 1:
            effective_mode = "keywords"
        if effective_mode == "keywords" and FreqType.broad not in freq_types:
            console.print(
                "[yellow]Предупреждение: --csv-mode keywords требует freq=broad. "
                "CSV будет пустым. Добавьте broad или используйте --csv-mode freq.[/yellow]"
            )

    try:
        params = WordstatParams(
            query=list(queries),
            lr=lr,
            freq=freq_types,
        )
    except Exception as e:
        raise click.ClickException(str(e))

    client = WordstatClient()

    try:
        results = client.search_sync(params)
    except RuntimeError as e:
        raise click.ClickException(str(e))

    # Консольный вывод
    if fmt == "table":
        _output_table(results, show_keywords=not no_keywords)
    elif fmt == "json":
        data = [r.model_dump() for r in results]
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))

    # Файловый вывод
    if output:
        out_path = Path(output)
        suffix = out_path.suffix.lower()
        if suffix == ".json":
            _save_json(results, out_path)
        elif suffix == ".csv":
            has_multiple_freq = len(freq_types) > 1
            if csv_mode == "freq" or (csv_mode == "auto" and has_multiple_freq):
                _save_csv_freq(results, out_path)
            else:
                _save_csv_keywords(results, out_path)
        else:
            _save_json(results, out_path)


@main.command()
def mcp() -> None:
    """Запустить MCP-сервер."""
    from .mcp_server import serve
    serve()
