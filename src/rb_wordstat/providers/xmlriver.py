from __future__ import annotations

import asyncio
import os

import httpx
from loguru import logger

from .base import WordstatProvider
from ..core.models import FreqType, WordstatEntry, WordstatParams, WordstatResult

_BASE_URL = "https://xmlriver.com/wordstat/new/json"
_MAX_CONCURRENT = 10
_MAX_ATTEMPTS = 3
_RETRY_DELAY = 1.0


class XmlRiverWordstatProvider(WordstatProvider):
    """Провайдер Яндекс.Wordstat через XML River API."""

    name = "xmlriver"

    def __init__(self) -> None:
        user = os.getenv("XMLRIVER_USER")
        token = os.getenv("XMLRIVER_TOKEN")
        if not user or not token:
            raise RuntimeError(
                "Не найдены переменные XMLRIVER_USER и XMLRIVER_TOKEN. "
                "Задайте их через env или файл .env"
            )
        self._user = user
        self._token = token
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    def _parse_response(
        self,
        data: dict,
        query: str,
        freq_type: FreqType,
    ) -> WordstatResult:
        total_value = data.get("totalValue", 0)
        table_data = data.get("table", {}).get("tableData", {})

        popular_raw = table_data.get("popular", [])
        assoc_raw = table_data.get("associations", [])

        def _parse_entries(items: list[dict]) -> list[WordstatEntry]:
            result = []
            for item in items:
                try:
                    result.append(WordstatEntry(
                        text=item["text"],
                        value=int(str(item["value"]).replace("\u00a0", "").replace(" ", "")),
                    ))
                except (KeyError, ValueError):
                    pass
            return result

        return WordstatResult(
            query=query,
            freq_type=freq_type,
            total_value=total_value,
            popular=_parse_entries(popular_raw),
            associations=_parse_entries(assoc_raw),
        )

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        query: str,
        freq_type: FreqType,
        lr: int,
    ) -> WordstatResult:
        query_sent = freq_type.apply(query)
        params = {
            "query": query_sent,
            "user": self._user,
            "key": self._token,
            "regions": lr,
        }
        async with self._semaphore:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = await client.get(_BASE_URL, params=params, timeout=30.0)
                    response.raise_for_status()
                    data = response.json()

                    if "error" in data:
                        logger.warning(
                            f"[wordstat] '{query_sent}' API error: {data['error']} "
                            f"(попытка {attempt}/{_MAX_ATTEMPTS})"
                        )
                    else:
                        result = self._parse_response(data, query, freq_type)
                        logger.info(
                            f"[wordstat] '{query_sent}' lr={lr} → "
                            f"total={result.total_value}, "
                            f"popular={len(result.popular)}, "
                            f"assoc={len(result.associations)}"
                        )
                        return result

                except httpx.HTTPStatusError as e:
                    logger.error(
                        f"[wordstat] '{query_sent}' HTTP {e.response.status_code} "
                        f"(попытка {attempt}/{_MAX_ATTEMPTS})"
                    )
                except Exception as e:
                    logger.error(
                        f"[wordstat] '{query_sent}' {type(e).__name__}: {e} "
                        f"(попытка {attempt}/{_MAX_ATTEMPTS})"
                    )

                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(_RETRY_DELAY)

        logger.error(f"[wordstat] '{query_sent}' — все {_MAX_ATTEMPTS} попытки исчерпаны")
        return WordstatResult(
            query=query,
            freq_type=freq_type,
            total_value=0,
            popular=[],
            associations=[],
        )

    async def search(self, params: WordstatParams) -> list[WordstatResult]:
        """Выполняет все запросы параллельно (до 10 потоков)."""
        queries = params.get_queries()

        async with httpx.AsyncClient() as client:
            tasks = [
                self._fetch_one(client, query, freq_type, params.lr)
                for query in queries
                for freq_type in params.freq
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[WordstatResult] = []
        for item in results:
            if isinstance(item, WordstatResult):
                all_results.append(item)
            else:
                logger.error(f"[wordstat] ошибка в задаче: {item}")

        return all_results
