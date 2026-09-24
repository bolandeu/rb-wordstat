from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import ClassVar

import httpx

from ..core.errors import AuthRequired, ProviderError
from ..core.models import FreqType, WordstatEntry, WordstatResult
from ..credentials import manager as credentials

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_RETRY_DELAY = 1.0
_RETRY_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
# Доступы XML River / XMLStock общие с CLI serp: если своих нет, читаются его
# записи (keychain serp:<provider>, env SERP_<PROVIDER>_<FIELD>).
_SHARED_NAMESPACES = ("serp",)


class ApiError(Exception):
    """Ошибка в теле ответа сервиса; `kind` решает, что с ней делать."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # "auth" | "retry" | "fatal" | "empty"
        self.message = message


class WordstatProvider(ABC):
    """Провайдер частот Яндекс.Wordstat поверх HTTP JSON API.

    Один вызов `fetch` — один запрос × тип частоты. Повторы временных сбоев,
    таймаут и перевод ошибок в `AuthRequired` / `ProviderError` — здесь, общие
    для всех. Подкласс задаёт `name` (ключ в `providers.PROVIDERS` и имя
    credential), `summary` (строка для --help), `credential_fields`, адрес и
    параметры (`_params`), разбор ошибки (`_api_error`) и ответа (`_parse`).
    На `AuthRequired` / `ProviderError` `WordstatClient` переключается на
    следующий провайдер очереди.
    """

    name: ClassVar[str]
    summary: ClassVar[str] = ""
    url: ClassVar[str]
    credential_fields: ClassVar[tuple[str, ...]] = ("user", "token")
    # Устаревшие имена env-переменных по полям — последний источник доступов.
    legacy_env: ClassVar[dict[str, str]] = {}

    def __init__(
        self,
        credential: dict[str, str] | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_delay: float = _RETRY_DELAY,
    ) -> None:
        credential = credential or self.load_credential()
        if credential is None:
            raise AuthRequired(self.name)
        self._credential = credential
        self._transport = transport  # тестовый шов для httpx.MockTransport
        self._retry_delay = retry_delay
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def load_credential(cls) -> dict[str, str] | None:
        """Все `credential_fields`: свои env/keychain → общие с serp → legacy env. None, если не хватает."""
        fields = list(cls.credential_fields)
        found = credentials.get_credential(cls.name, env_fields=fields) or {}
        for namespace in _SHARED_NAMESPACES:
            if all(found.get(field) for field in fields):
                break
            shared = credentials.get_credential(cls.name, env_fields=fields, namespace=namespace) or {}
            found = {**shared, **{k: v for k, v in found.items() if v}}
        for field, env_name in cls.legacy_env.items():
            if not found.get(field) and os.environ.get(env_name):
                found[field] = os.environ[env_name]
        if all(found.get(field) for field in fields):
            return found
        return None

    @abstractmethod
    def _params(self, query_sent: str, lr: int) -> dict:
        """Параметры GET-запроса: доступы, запрос с оператором, регион."""

    @abstractmethod
    def _api_error(self, data: dict) -> ApiError | None:
        """Ошибка в теле ответа, или None, если ответ с данными."""

    @abstractmethod
    def _parse(self, data: dict) -> tuple[int, list[dict], list[dict]]:
        """(частота, похожие, ассоциации) — записи как {"text", "value"}."""

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0, transport=self._transport)
        return self._client

    async def aclose(self) -> None:
        # AsyncClient привязан к event loop, а search_sync каждый раз запускает новый.
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch(self, query: str, freq_type: FreqType, lr: int) -> WordstatResult:
        """Частота и похожие запросы для одного запроса и типа частоты."""
        query_sent = freq_type.apply(query)
        where = f"'{query_sent}' lr={lr}"
        last_error = "нет ответа"

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await self._http().get(self.url, params=self._params(query_sent, lr))
            except httpx.TransportError as exc:
                last_error = type(exc).__name__
            else:
                status = response.status_code
                if status in (401, 403):
                    raise AuthRequired(self.name)
                if response.is_error and status not in _RETRY_HTTP_STATUSES:
                    raise ProviderError(self.name, f"{where}: HTTP {status}", status=status)
                if response.is_error:
                    last_error = f"HTTP {status}"
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        last_error = "ответ не JSON"
                    else:
                        error = self._api_error(data)
                        if error is None:
                            result = self._result(data, query, freq_type)
                            log.info("%s %s → %d (попытка %d)", self.name, where, result.total_value, attempt)
                            return result
                        if error.kind == "empty":
                            return WordstatResult(
                                query=query, freq_type=freq_type, total_value=0, popular=[], associations=[],
                                provider=self.name,
                            )  # fmt: skip
                        if error.kind == "auth":
                            raise AuthRequired(self.name)
                        if error.kind == "fatal":
                            raise ProviderError(self.name, f"{where}: {error.message}")
                        last_error = error.message

            log.warning("%s %s — %s (попытка %d/%d)", self.name, where, last_error, attempt, _MAX_ATTEMPTS)
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(self._retry_delay)

        raise ProviderError(self.name, f"{where}: {last_error} после {_MAX_ATTEMPTS} попыток")

    def _result(self, data: dict, query: str, freq_type: FreqType) -> WordstatResult:
        total, popular, associations = self._parse(data)
        return WordstatResult(
            query=query,
            freq_type=freq_type,
            total_value=total,
            popular=_entries(popular),
            associations=_entries(associations),
            provider=self.name,
        )


def to_int(value: object) -> int:
    """'11 067', '11\\xa0067', 11067 → 11067."""
    return int(str(value).replace(" ", "").replace(" ", ""))


def _entries(items: list[dict]) -> list[WordstatEntry]:
    result = []
    for item in items:
        try:
            result.append(WordstatEntry(text=item["text"], value=to_int(item["value"])))
        except (KeyError, ValueError):
            continue  # битая строка не должна ронять весь ответ
    return result
