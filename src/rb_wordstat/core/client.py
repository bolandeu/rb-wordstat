from __future__ import annotations

import asyncio

from .models import WordstatParams, WordstatResult
from ..providers.xmlriver import XmlRiverWordstatProvider


class WordstatClient:
    """Основной клиент для получения данных Яндекс.Wordstat."""

    def __init__(self, provider=None) -> None:
        self.provider = provider or XmlRiverWordstatProvider()

    async def search(self, params: WordstatParams) -> list[WordstatResult]:
        """Асинхронный запрос."""
        return await self.provider.search(params)

    def search_sync(self, params: WordstatParams) -> list[WordstatResult]:
        """Синхронная обёртка над async search."""
        return asyncio.run(self.search(params))
