"""Стоимость платных запросов: цена за запрос по провайдеру, в рублях.

Цена — `[prices] <provider> = 0.0` в конфиге проекта или переменная
`WORDSTAT_<PROVIDER>_PRICE` (перекрывает конфиг; на сервере — только она).
Не задана — стоимость неизвестна (`None`) и предупреждение, не ошибка:
уже оплаченный поиск не должен падать из-за цены.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence

from ..providers import PROVIDERS
from .models import WordstatResult
from .version import CLI_NAME

log = logging.getLogger(__name__)

CURRENCY = "RUB"


def env_var(provider: str) -> str:
    return f"{CLI_NAME.upper()}_{provider.upper()}_PRICE"


# Для `describe`: переменные с ценами всех известных провайдеров.
ENV_VARS = {env_var(name): f"Цена одного запроса к {name}, руб.; перекрывает [prices] проекта" for name in PROVIDERS}


def resolve(providers: Sequence[str], configured: Mapping[str, float]) -> dict[str, float | None]:
    """Цена за запрос по каждому провайдеру: env → конфиг → None."""
    prices: dict[str, float | None] = {}
    for name in providers:
        raw = os.environ.get(env_var(name), "").strip()
        if not raw:
            prices[name] = configured.get(name)
            continue
        try:
            prices[name] = float(raw.replace(",", "."))
        except ValueError:
            log.warning("%s=%r — не число, стоимость запросов %s неизвестна.", env_var(name), raw, name)
            prices[name] = None
    return prices


def price(results: Sequence[WordstatResult], prices: Mapping[str, float | None]) -> tuple[list[dict], float | None]:
    """Результаты для --json с `cost` / `cost_currency` и итог; итог None, если хоть одна стоимость неизвестна."""
    rows: list[dict] = []
    unknown: list[str] = []
    for r in results:
        cost: float | None = 0.0 if r.from_cache else prices.get(r.provider)
        if cost is None and r.provider not in unknown:
            unknown.append(r.provider)
        rows.append({**r.model_dump(mode="json"), "cost": cost, "cost_currency": CURRENCY})
    for name in unknown:
        log.warning(
            "Цена запроса к %s не задана — cost null. Задайте её в [prices] конфига проекта или в %s.",
            name, env_var(name),
        )  # fmt: skip
    costs = [row["cost"] for row in rows]
    total = None if any(c is None for c in costs) else round(sum(costs), 6)
    return rows, total
