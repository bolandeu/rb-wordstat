from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal

import httpx

from ..core.errors import AuthRequired, ProviderError
from ..core.models import FreqType, WordstatEntry, WordstatResult
from ..core.version import module_exists
from ..credentials import manager as credentials

log = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_RETRY_DELAY = 1.0
_RETRY_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
# health_check: один запрос без повторов, жёсткий предел (standard §8).
HEALTH_TIMEOUT = 10.0

# What a provider's own health check can conclude. `missing` and `unchecked`
# are decided by `auth status` before a check ever runs.
HealthStatus = Literal["ok", "invalid", "expired", "quota_exhausted", "unreachable"]


@dataclass(frozen=True)
class Quota:
    remaining: int | None = None
    limit: int | None = None
    unit: str = "requests"


@dataclass(frozen=True)
class Health:
    """Result of `Provider.health_check()`. Never put a credential value in `message`."""

    status: HealthStatus = "ok"
    expires_at: datetime | None = None
    quota: Quota | None = None
    message: str | None = None


class Provider:
    """Base for every external integration, whatever its transport.

    A concrete provider sets `name` and `credential_fields` (the field names
    it reads via `credentials.manager` under `credential_name`; `()` if it
    needs none), `required`, `per_target` and `legacy_env` where they
    differ, and must implement `health_check()` — `tests/test_providers.py`
    fails for any provider that doesn't. `auth status --check` gets an
    instance via `for_health_check()`: `cls()` by default; a provider whose
    constructor needs arguments overrides it (building them from config/env).

    Classes that are only bases for others set `abstract = True` in their own
    body; everything else defined under `providers/` is discovered by
    `all_providers()`, so there is no registry to forget to update.
    """

    abstract: ClassVar[bool] = True
    name: ClassVar[str] = "default"
    credential_fields: ClassVar[tuple[str, ...]] = ("api_key",)
    # False for a provider the CLI works without: its missing credential is
    # reported but doesn't fail `auth status` (a wrong one still does).
    required: ClassVar[bool] = True
    # True when the credential is per target (a site, host, account): one
    # stored credential per target, named "<name>:<target>" — e.g.
    # `auth login --provider deploy:example.com`. `auth status` reports each
    # stored target separately and sets `target` before `health_check()`.
    per_target: ClassVar[bool] = False
    # Older env var names still honoured, field -> name; looked up after the
    # keychain unless `legacy_env_first`. In a subclass keep the annotation
    # (ruff RUF012): legacy_env: ClassVar[dict[str, str]] = {"api_key": "XMLRIVER_TOKEN"}
    legacy_env: ClassVar[dict[str, str]] = {}
    legacy_env_first: ClassVar[bool] = False
    # Other CLIs' credential namespaces (their command names) to read this
    # provider's credential from after our own — e.g. wordstat reading the
    # key `serp auth login` stored: shared_namespaces = ("serp",). Read-only.
    shared_namespaces: ClassVar[tuple[str, ...]] = ()
    target: str | None = None

    def credential(self) -> dict[str, str] | None:
        """This provider's credential, resolved with all of the options above (use it in auth_headers()).

        None in a CLI generated without credentials (include_auth=false): there
        is no key store to read, so a provider there declares
        `credential_fields = ()` and never needs one.
        """
        manager_module = f"{__name__.split('.')[0]}.credentials.manager"
        if not module_exists(manager_module):
            return None
        manager = importlib.import_module(manager_module)
        return manager.get_credential(
            self.credential_name,
            env_fields=list(self.credential_fields),
            legacy_env=self.legacy_env,
            legacy_env_first=self.legacy_env_first,
            shared_namespaces=self.shared_namespaces,
        )

    @classmethod
    def for_health_check(cls, target: str | None = None) -> Provider:
        """An instance for `auth status --check` (for `target`, if per-target)."""
        provider = cls()
        provider.target = target
        return provider

    @property
    def credential_name(self) -> str:
        """The key to read this provider's credential under in `credentials.manager`."""
        return f"{self.name}:{self.target}" if self.per_target and self.target else self.name

    def health_check(self) -> Health:
        """One cheap, read-only, non-billed call proving the credential works.

        Typically `self.get_json("/me")` (or whatever the API's cheapest
        authenticated read is) then `return Health()`; add `expires_at` for
        anything with a lifetime and `quota` if the API reports it. Just let
        `AuthRequired` / `ProviderError` propagate — `auth status` maps them
        to `invalid` / `unreachable`. It must finish within 10 s and not retry,
        and it is the provider's own client timeout that guarantees it —
        `auth status` runs no watchdog thread. `HttpProvider.probe()` makes
        exactly one request with a 10 s httpx timeout; anything else passes
        `credentials.health.CHECK_TIMEOUT` (10 s) to what it calls.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement health_check()")


def all_providers() -> list[type[Provider]]:
    """Every concrete Provider subclass defined in this package, sorted by name."""
    package = __name__.rsplit(".", 1)[0]
    for module in pkgutil.iter_modules(importlib.import_module(package).__path__):
        # base/http hold only abstract bases; importing http.py would pull in
        # httpx for CLIs without HTTP providers (their subclasses import it anyway).
        if module.name not in ("base", "http"):
            importlib.import_module(f"{package}.{module.name}")
    found: set[type[Provider]] = set()
    pending = list(Provider.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__module__.startswith(f"{package}.") and not cls.__dict__.get("abstract", False):
            found.add(cls)
    return sorted(found, key=lambda cls: cls.name)


class ApiError(Exception):
    """Ошибка в теле ответа сервиса; `kind` решает, что с ней делать."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # "auth" | "retry" | "fatal" | "empty"
        self.message = message


class WordstatProvider(Provider, ABC):
    """Провайдер частот Яндекс.Wordstat поверх HTTP JSON API.

    Один вызов `fetch` — один запрос × тип частоты, один платный ответ:
    похожие и ассоциации приходят в нём же, без страниц. Платный — только
    ответ с данными (или «ничего не найдено»); сбой сети, HTTP-ошибка и
    ответ-ошибка — нет, их повторы тоже. Повторы временных сбоев,
    таймаут и перевод ошибок в `AuthRequired` / `ProviderError` — здесь, общие
    для всех. Подкласс задаёт `name` (ключ в `providers.PROVIDERS` и имя
    credential), `summary` (строка для --help), `credential_fields`, адрес и
    параметры (`_params`), разбор ошибки (`_api_error`) и ответа (`_parse`) —
    последние два без доступов и сети, чтобы разбирать и ответы из журнала.
    На `AuthRequired` / `ProviderError` `WordstatClient` переключается на
    следующий провайдер очереди. `health_check()` (для `auth status --check`) —
    бесплатный запрос баланса: `_balance_params` и `_parse_balance` у подкласса.
    """

    abstract = True
    name: ClassVar[str]
    summary: ClassVar[str] = ""
    url: ClassVar[str]
    balance_url: ClassVar[str]
    credential_fields: ClassVar[tuple[str, ...]] = ("user", "token")
    # Доступы XML River / XMLStock общие с CLI serp (`serp auth login`).
    shared_namespaces: ClassVar[tuple[str, ...]] = ("serp",)
    # Тестовый шов для health_check (синхронный httpx.MockTransport).
    health_transport: httpx.BaseTransport | None = None

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
        """Все `credential_fields`: env WORDSTAT_*/SERP_* → keychain wordstat:/serp: → legacy env. None, если не хватает.

        Тот же поиск, что показывает `auth status` (`credentials.manager.locate_fields`).
        """
        fields = list(cls.credential_fields)
        located = credentials.locate_fields(
            cls.name,
            fields,
            legacy_env=cls.legacy_env,
            legacy_env_first=cls.legacy_env_first,
            shared_namespaces=cls.shared_namespaces,
        )
        if all(field in located for field in fields):
            return {field: value for field, (value, _, _) in located.items()}
        return None

    def health_check(self) -> Health:
        """Баланс счёта — бесплатный запрос, заодно проверка логина и ключа. Без повторов, до 10 с."""
        try:
            with httpx.Client(timeout=HEALTH_TIMEOUT, transport=self.health_transport) as client:
                response = client.get(self.balance_url, params=self._balance_params())
        except httpx.TransportError as exc:
            raise ProviderError(self.name, f"баланс: {type(exc).__name__}") from None
        if response.status_code in (401, 403):
            raise AuthRequired(self.name)
        if response.is_error:
            raise ProviderError(self.name, f"баланс: HTTP {response.status_code}", status=response.status_code)
        balance = self._parse_balance(response.text)
        quota = Quota(remaining=int(balance), unit="rub")
        if balance <= 0:
            return Health(status="quota_exhausted", quota=quota, message=f"баланс {balance:g} ₽ — пополнить счёт")
        return Health(quota=quota)

    @abstractmethod
    def _balance_params(self) -> dict:
        """Параметры GET-запроса баланса к `balance_url`."""

    @abstractmethod
    def _parse_balance(self, text: str) -> float:
        """Баланс в рублях; неверный доступ — AuthRequired, прочее — ProviderError."""

    @abstractmethod
    def _params(self, query_sent: str, lr: int) -> dict:
        """Параметры GET-запроса: доступы, запрос с оператором, регион."""

    @classmethod
    @abstractmethod
    def _api_error(cls, data: dict) -> ApiError | None:
        """Ошибка в теле ответа, или None, если ответ с данными."""

    @classmethod
    @abstractmethod
    def _parse(cls, data: dict) -> tuple[int, list[dict], list[dict]]:
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
        return self.to_result(await self.fetch_raw(query, freq_type, lr), query, freq_type)

    async def fetch_raw(self, query: str, freq_type: FreqType, lr: int) -> dict:
        """Сырой JSON-ответ (с данными или «ничего не найдено»); сбои — AuthRequired / ProviderError."""
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
                        if error is None or error.kind == "empty":
                            log.info("%s %s — ответ получен (попытка %d)", self.name, where, attempt)
                            return data
                        if error.kind == "auth":
                            raise AuthRequired(self.name)
                        if error.kind == "fatal":
                            raise ProviderError(self.name, f"{where}: {error.message}")
                        last_error = error.message

            log.warning("%s %s — %s (попытка %d/%d)", self.name, where, last_error, attempt, _MAX_ATTEMPTS)
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(self._retry_delay)

        raise ProviderError(self.name, f"{where}: {last_error} после {_MAX_ATTEMPTS} попыток")

    @classmethod
    def to_result(cls, data: dict, query: str, freq_type: FreqType) -> WordstatResult:
        """Разобрать ответ из `fetch_raw` — живой или из журнала; «ничего не найдено» → частота 0."""
        error = cls._api_error(data)
        total, popular, associations = (0, [], []) if error is not None else cls._parse(data)
        return WordstatResult(
            query=query,
            freq_type=freq_type,
            total_value=total,
            popular=_entries(popular),
            associations=_entries(associations),
            provider=cls.name,
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
