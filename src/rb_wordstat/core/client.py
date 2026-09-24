from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from ..providers import WordstatProvider, provider_class
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
    """

    def __init__(
        self,
        provider: WordstatProvider | None = None,
        *,
        providers: Sequence[str | WordstatProvider] | None = None,
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

    async def search(self, params: WordstatParams) -> list[WordstatResult]:
        """Все запросы × типы частоты; результаты в порядке запросов, затем типов."""
        # Семафор и экземпляры провайдеров — на один вызов: они привязаны к
        # event loop, а search_sync каждый раз запускает новый.
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        instances: dict[int, WordstatProvider | AuthRequired] = {}
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(self._fetch_one(query, freq_type, params.lr, instances, semaphore))
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

    def search_sync(self, params: WordstatParams) -> list[WordstatResult]:
        """Синхронная обёртка над async search."""
        return asyncio.run(self.search(params))

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
    ) -> WordstatResult:
        errors: list[ProviderError | AuthRequired] = []
        names = self._names()
        for index, name in enumerate(names):
            try:
                provider = self._provider(index, instances)
                async with semaphore:
                    return await provider.fetch(query, freq_type, lr)
            except (ProviderError, AuthRequired) as exc:
                errors.append(exc)
                has_next = index + 1 < len(names)
                log.warning("Провайдер %s: %s%s", name, exc.message, " — пробую следующий" if has_next else "")
        if len(errors) == 1:
            raise errors[0]
        raise ProviderError("+".join(names), "все провайдеры отказали: " + "; ".join(e.message for e in errors))

    def _names(self) -> list[str]:
        return [item if isinstance(item, str) else item.name for item in self._chain]
