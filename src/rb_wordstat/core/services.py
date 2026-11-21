"""Project services: find the project folder, read and write its config file, and the check that the installed CLI is
new enough for it.
"""

from __future__ import annotations

import csv
import json
import logging
import tomllib
from datetime import timedelta
from pathlib import Path

import tomli_w
from packaging.version import Version
from pydantic import ValidationError

from . import pricing
from .client import WordstatClient
from .errors import CliTooOld, InvalidArguments, ProjectNotInitialized
from .models import ALL_FREQ_TYPES, DEFAULT_PROVIDERS, FreqType, ProjectConfig, WordstatParams, WordstatResult
from .version import CLI_NAME, installed_version

log = logging.getLogger(__name__)

PROJECT_DIR_NAME = f".{CLI_NAME}"
CONFIG_FILE_NAME = "config.toml"


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / PROJECT_DIR_NAME).is_dir():
            return candidate
    return None


def require_project_root(start: Path) -> Path:
    root = find_project_root(start)
    if root is None:
        raise ProjectNotInitialized(str(start))
    return root


def config_path(project_root: Path) -> Path:
    return project_root / PROJECT_DIR_NAME / CONFIG_FILE_NAME


def check_cli_compat(config: ProjectConfig) -> None:
    """Raise CliTooOld if this installed CLI is older than the project's `cli.min_version`.

    A project outlives any single CLI release; this is how it refuses to be
    driven by a CLI that predates a config field or command it relies on.
    Skipped for an uninstalled (bare source) run, which has no version, and
    for a build without a `v*` tag in reach (uv-dynamic-versioning's
    `0.0.0` fallback) — a dev checkout, not a release older than anything.
    """
    installed = installed_version()
    if installed is None or Version(installed).release == (0, 0, 0):
        return
    if Version(installed) < Version(config.cli.min_version):
        raise CliTooOld(installed, config.cli.min_version)


def load_config(project_root: Path, *, check_compat: bool = True) -> ProjectConfig:
    """Load and validate the project config, enforcing `cli.min_version` by default.

    Only `doctor` passes `check_compat=False` — it reports the mismatch as
    one of its checks instead of failing on it.
    """
    data = tomllib.loads(config_path(project_root).read_text(encoding="utf-8"))
    config = ProjectConfig.model_validate(data)
    if check_compat:
        check_cli_compat(config)
    return config


def save_config(project_root: Path, config: ProjectConfig) -> None:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(config.model_dump()), encoding="utf-8")


def init_project(project_root: Path, name: str) -> ProjectConfig:
    config = ProjectConfig(name=name)
    save_config(project_root, config)
    return config


def resolve_providers(explicit: str | None, start: Path) -> list[str]:
    """Очередь провайдеров: --provider "a,b" → `providers` проекта → по умолчанию."""
    if explicit:
        return [name.strip() for name in explicit.split(",") if name.strip()]
    root = find_project_root(start)
    if root is not None:
        return load_config(root).providers
    return list(DEFAULT_PROVIDERS)


def resolve_prices(providers: list[str], start: Path) -> dict[str, float | None]:
    """Цена запроса по провайдерам: WORDSTAT_<PROVIDER>_PRICE → [prices] проекта → None (неизвестна)."""
    root = find_project_root(start)
    configured = load_config(root).prices if root is not None else {}
    return pricing.resolve(providers, configured)


def price_results(results: list[WordstatResult], prices: dict[str, float | None]) -> tuple[list[dict], float | None]:
    """Результаты для --json с cost (руб.; из журнала — 0), cost_source и cost_currency, плюс cost_total."""
    return pricing.price(results, prices)


FREQ_CHOICES = ["broad", "phrase", "exact", "exact-ord", "all"]


def resolve_freq(values: list[str]) -> list[FreqType]:
    """--freq broad,phrase и/или --freq broad --freq phrase → типы без дублей; all — все; пусто — broad."""
    expanded = [part.strip() for value in values for part in value.split(",") if part.strip()]
    invalid = [v for v in expanded if v not in FREQ_CHOICES]
    if invalid:
        raise InvalidArguments(
            f"Недопустимые значения --freq: {', '.join(invalid)}. Допустимые: {', '.join(FREQ_CHOICES)}."
        )
    if "all" in expanded:
        return list(ALL_FREQ_TYPES)
    seen: list[FreqType] = []
    for value in expanded:
        freq_type = FreqType(value.replace("-", "_"))
        if freq_type not in seen:
            seen.append(freq_type)
    return seen or [FreqType.broad]


_AGE_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_age(value: str) -> timedelta:
    """'30m', '12h', '7d', '2w' → timedelta."""
    number, unit = value[:-1], value[-1:].lower()
    if not number.isdigit() or unit not in _AGE_UNITS:
        raise InvalidArguments(f"Не понимаю срок '{value}': нужно число и m/h/d/w, например 30m, 12h, 7d, 2w.")
    return timedelta(**{_AGE_UNITS[unit]: int(number)})


def search(
    queries: list[str],
    *,
    freq: list[FreqType],
    lr: int,
    providers: list[str],
    use_cache: bool = False,
    max_age: timedelta | None = None,
    device: str | None = None,
    limit: int | None = None,
) -> list[WordstatResult]:
    """Частоты по всем запросам × типам частоты через очередь провайдеров; ответы пишутся в журнал."""
    try:
        params = WordstatParams(query=queries, lr=lr, freq=freq, device=device, limit=limit)
    except ValidationError as exc:
        raise InvalidArguments("; ".join(err["msg"] for err in exc.errors())) from exc
    return WordstatClient(providers=providers).search_sync(params, use_cache=use_cache, max_age=max_age)


def csv_mode_for(mode: str, freq: list[FreqType]) -> str:
    """auto → freq при нескольких типах частоты, keywords при одном."""
    if mode == "auto":
        return "freq" if len(freq) > 1 else "keywords"
    return mode


def save_results(results: list[WordstatResult], path: Path, *, csv_mode: str) -> None:
    """Файл по расширению: .csv — частоты (freq) или похожие запросы (keywords), иначе JSON."""
    if path.suffix.lower() != ".csv":
        data = [r.model_dump(mode="json") for r in results]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        if csv_mode == "freq":
            writer.writerow(["query", "freq_type", "freq_label", "operator", "total_value", "fetched_at"])
            for r in results:
                writer.writerow(
                    [r.query, r.freq_type.value, r.freq_type.label, r.freq_type.apply(r.query), r.total_value, _iso(r)]
                )
            return
        if all(r.freq_type != FreqType.broad for r in results):
            log.warning(
                "CSV keywords строится по freq=broad, а его нет — файл будет пустым. Добавьте broad или --csv-mode freq."
            )
        writer.writerow(["source_query", "type", "keyword", "value", "fetched_at"])
        for r in results:
            if r.freq_type != FreqType.broad:
                continue
            for entry in r.popular:
                writer.writerow([r.query, "popular", entry.text, entry.value, _iso(r)])
            for entry in r.associations:
                writer.writerow([r.query, "assoc", entry.text, entry.value, _iso(r)])


def _iso(result: WordstatResult) -> str:
    """Когда провайдер отдал ответ (UTC, ISO 8601) — от какого числа данные."""
    return result.fetched_at.isoformat() if result.fetched_at else ""
