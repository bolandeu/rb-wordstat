from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from ..providers import WordstatProvider, provider_class
from .cache import ResponseCache
from .errors import AuthRequired, ProviderError
from .models import DEFAULT_PROVIDERS, FreqType, WordstatParams, WordstatResult

log = logging.getLogger(__name__)

_MAX_CONCURRENT = 10


class WordstatClient:
    """Основной клиент для получения данных Яндекс.Wordstat.

    `providers` — очередь: имена из `providers.PROVIDERS` или готовые
    экземпляры. Первый — основной, остальные — фолбэки: для каждой пары
    (запрос, тип частоты) следующий пробуется, только если предыдущий упал с
    `ProviderError` / `AuthRequired`. Отказали все — ошибка (одна — как есть,
    несколько — сводный `ProviderError`). Все пары запрашиваются параллельно,
    не больше 10 одновременно.

    `cache` — журнал всех ответов (`ResponseCache`): каждый ответ провайдера
    пишется туда всегда; `False` — не писать. Читать из него — только по
    `use_cache=True` в `search`, и только ответы провайдеров из очереди — в
    её порядке.
    """

    def __init__(
        self,
        provider: WordstatProvider | None = None,
        *,
        providers: Sequence[str | WordstatProvider] | None = None,
        cache: ResponseCache | bool = True,
    ) -> None:
        if provider is not None and providers is not None:
            raise ValueError("Передайте либо provider, либо providers.")
        if provider is not None:
            self._chain: list[str | WordstatProvider] = [provider]
        else:
            self._chain = list(DEFAULT_PROVIDERS if providers is None else providers)
        if not self._chain:
            raise ValueError("Очередь провайдеров пуста.")
        for item in self._chain:
            if isinstance(item, str):
                provider_class(item)  # неизвестное имя — ошибка сразу, а не после сбоя основного
        self.cache: ResponseCache | None = ResponseCache() if cache is True else (cache or None)

    async def search(
        self, params: WordstatParams, *, use_cache: bool = False, max_age: timedelta | None = None
    ) -> list[WordstatResult]:
        """Все запросы × типы частоты; результаты в порядке запросов, затем типов.

        `use_cache` — сначала журнал (не старше `max_age`), живой запрос — только если там нет.
        """
        # Семафор и экземпляры провайдеров — на один вызов: они привязаны к
        # event loop, а search_sync каждый раз запускает новый.
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        instances: dict[int, WordstatProvider | AuthRequired] = {}
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(
                        self._fetch_one(query, freq_type, params.lr, instances, semaphore, use_cache, max_age)
                    )
                    for query in params.get_queries()
                    for freq_type in params.freq
                ]
        except ExceptionGroup as eg:
            raise eg.exceptions[0] from None
        finally:
            for instance in instances.values():
                if isinstance(instance, WordstatProvider):
                    await instance.aclose()
        return [task.result() for task in tasks]

    def search_sync(
        self, params: WordstatParams, *, use_cache: bool = False, max_age: timedelta | None = None
    ) -> list[WordstatResult]:
        """Синхронная обёртка над async search."""
        return asyncio.run(self.search(params, use_cache=use_cache, max_age=max_age))

    def _provider(self, index: int, instances: dict[int, WordstatProvider | AuthRequired]) -> WordstatProvider:
        """Экземпляр провайдера из очереди — создаётся один раз за вызов search."""
        if index not in instances:
            item = self._chain[index]
            try:
                instances[index] = provider_class(item)() if isinstance(item, str) else item
            except AuthRequired as exc:  # нет доступов — помним, чтобы не проверять на каждой паре
                instances[index] = exc
        instance = instances[index]
        if isinstance(instance, AuthRequired):
            raise instance
        return instance

    async def _fetch_one(
        self,
        query: str,
        freq_type: FreqType,
        lr: int,
        instances: dict[int, WordstatProvider | AuthRequired],
        semaphore: asyncio.Semaphore,
        use_cache: bool = False,
        max_age: timedelta | None = None,
    ) -> WordstatResult:
        names = self._names()
        if use_cache and self.cache is not None:
            # Из журнала — только ответ провайдера из очереди и в её порядке:
            # формат ответа у каждого свой, разбирает его свой класс.
            for index, name in enumerate(names):
                hit = self.cache.latest(
                    provider=name, freq_type=freq_type.value, region=str(lr), query=query, max_age=max_age
                )
                if hit is not None:
                    result = self._class(index).to_result(hit.data, query, freq_type)
                    return result.model_copy(
                        update={"provider": name, "fetched_at": hit.fetched_at, "from_cache": True}
                    )

        errors: list[ProviderError | AuthRequired] = []
        for index, name in enumerate(names):
            try:
                provider = self._provider(index, instances)
                async with semaphore:
                    data = await provider.fetch_raw(query, freq_type, lr)
                result = type(provider).to_result(data, query, freq_type)
                fetched_at = self._save(name, freq_type, lr, query, result.total_value, data)
                return result.model_copy(update={"provider": name, "fetched_at": fetched_at})
            except (ProviderError, AuthRequired) as exc:
                errors.append(exc)
                has_next = index + 1 < len(names)
                log.warning("Провайдер %s: %s%s", name, exc.message, " — пробую следующий" if has_next else "")
        if len(errors) == 1:
            raise errors[0]
        raise ProviderError("+".join(names), "все провайдеры отказали: " + "; ".join(e.message for e in errors))

    def _names(self) -> list[str]:
        return [item if isinstance(item, str) else item.name for item in self._chain]

    def _class(self, index: int) -> type[WordstatProvider]:
        item = self._chain[index]
        return provider_class(item) if isinstance(item, str) else type(item)

    def _save(self, provider: str, freq_type: FreqType, lr: int, query: str, total: int, data: dict) -> datetime:
        """Записать ответ в журнал; сбой диска не должен ломать уже оплаченный запрос."""
        if self.cache is not None:
            try:
                return self.cache.put(
                    provider=provider, freq_type=freq_type.value, region=str(lr), query=query, total_value=total,
                    data=data,
                )  # fmt: skip
            except sqlite3.Error as exc:
                log.warning("Не удалось записать ответ в журнал %s: %s", self.cache.path, exc)
        return datetime.now(UTC)
