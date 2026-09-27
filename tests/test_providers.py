from __future__ import annotations

import gc

import httpx
import pytest

from rb_wordstat.core.errors import AuthRequired, ProviderError
from rb_wordstat.core.models import FreqType
from rb_wordstat.providers import Health, Provider, XmlRiverProvider, XmlStockProvider, all_providers, provider_class
from rb_wordstat.providers.base import WordstatProvider

from .conftest import fixture_json

CRED = {"user": "u", "token": "t"}


def make(cls: type[WordstatProvider], responses: list, seen: list | None = None) -> WordstatProvider:
    """Провайдер, который по очереди отдаёт `responses`: dict → JSON 200, int → HTTP-статус, Exception → сбой сети."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, int):
            return httpx.Response(item)
        return httpx.Response(200, json=item)

    return cls(CRED, transport=httpx.MockTransport(handler), retry_delay=0)


@pytest.mark.parametrize(
    ("cls", "fixture"),
    [(XmlRiverProvider, "xmlriver_wordstat.json"), (XmlStockProvider, "xmlstock_wordstat.json")],
)
async def test_both_providers_parse_to_the_same_result(cls, fixture) -> None:
    seen: list[httpx.Request] = []
    result = await make(cls, [fixture_json(fixture)], seen).fetch("купить диван", FreqType.exact_ord, 2)

    assert result.total_value == 97993
    assert [e.text for e in result.popular] == ["купить диван", "купить диван в москве", "купить диван недорого"]
    assert result.popular[1].value == 29549
    assert [(e.text, e.value) for e in result.associations] == [("мебельный магазин", 19652), ("диванчик", 10609)]
    assert result.provider == cls.name
    params = seen[0].url.params
    assert params["query"] == '"[!купить !диван]"'
    assert params["regions"] == "2"
    assert params["key"] == "t"


async def test_value_with_spaces_and_broken_rows() -> None:
    data = {"totalValue": "8 615", "table": {"tableData": {"popular": [{"text": "a", "value": "11 067"}, {"x": 1}]}}}
    result = await make(XmlRiverProvider, [data]).fetch("a", FreqType.broad, 213)
    assert result.total_value == 8615
    assert [(e.text, e.value) for e in result.popular] == [("a", 11067)]
    assert result.associations == []


async def test_retries_transient_failures_then_succeeds() -> None:
    ok = fixture_json("xmlriver_wordstat.json")
    responses = [httpx.ConnectError("boom"), 503, {"code": 110, "error": "нет свободных каналов"}, ok]
    provider = make(XmlRiverProvider, responses)
    with pytest.raises(ProviderError, match="после 3 попыток"):
        await provider.fetch("a", FreqType.broad, 213)
    result = await make(XmlRiverProvider, responses[1:]).fetch("a", FreqType.broad, 213)
    assert result.total_value == 97993


@pytest.mark.parametrize(
    ("cls", "body"),
    [
        (XmlRiverProvider, {"code": 42, "error": "ключ содержит ошибку"}),
        (XmlStockProvider, {"query": "a", "error": {"code": -34, "message": "Не корректный ID"}}),
        (XmlRiverProvider, 401),
    ],
)
async def test_auth_errors_are_not_retried(cls, body) -> None:
    with pytest.raises(AuthRequired):
        await make(cls, [body]).fetch("a", FreqType.broad, 213)


async def test_fatal_api_error_and_http_4xx() -> None:
    with pytest.raises(ProviderError, match="ошибка 2"):
        await make(XmlRiverProvider, [{"code": 2, "error": "пустой запрос"}]).fetch("a", FreqType.broad, 213)
    with pytest.raises(ProviderError, match="HTTP 404"):
        await make(XmlStockProvider, [404]).fetch("a", FreqType.broad, 213)


async def test_no_results_is_zero_not_error() -> None:
    result = await make(XmlRiverProvider, [{"code": 15, "error": "нет результатов"}]).fetch("a", FreqType.broad, 213)
    assert (result.total_value, result.popular, result.provider) == (0, [], "xmlriver")


async def test_unknown_xmlstock_error_is_retried_and_non_json_body() -> None:
    other = {"error": {"code": -1, "message": "лимит"}}
    provider = make(XmlStockProvider, [other, {"error": "строкой"}, httpx.ReadTimeout("slow")])
    with pytest.raises(ProviderError):
        await provider.fetch("a", FreqType.broad, 213)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    broken = XmlRiverProvider(CRED, transport=httpx.MockTransport(handler), retry_delay=0)
    with pytest.raises(ProviderError, match="не JSON"):
        await broken.fetch("a", FreqType.broad, 213)
    await broken.aclose()


def test_credentials_own_then_shared_with_serp_then_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    assert XmlRiverProvider.load_credential() is None
    with pytest.raises(AuthRequired):
        XmlRiverProvider()

    monkeypatch.setenv("XMLRIVER_USER", "legacy-u")
    monkeypatch.setenv("XMLRIVER_TOKEN", "legacy-t")
    assert XmlRiverProvider.load_credential() == {"user": "legacy-u", "token": "legacy-t"}

    store = {"serp:xmlriver": '{"user": "serp-u", "token": "serp-t"}'}
    monkeypatch.setattr("rb_wordstat.credentials.manager.keyring.get_password", lambda s, u: store.get(s))
    assert XmlRiverProvider.load_credential() == {"user": "serp-u", "token": "serp-t"}

    monkeypatch.setenv("WORDSTAT_XMLRIVER_TOKEN", "own-t")  # своё поле перекрывает общее
    assert XmlRiverProvider.load_credential() == {"user": "serp-u", "token": "own-t"}

    monkeypatch.setenv("SERP_XMLSTOCK_USER", "su")
    monkeypatch.setenv("SERP_XMLSTOCK_TOKEN", "st")
    assert XmlStockProvider.load_credential() == {"user": "su", "token": "st"}


def test_unknown_provider_name() -> None:
    with pytest.raises(Exception, match="Неизвестный провайдер"):
        provider_class("nope")


def test_required_xmlriver_optional_xmlstock() -> None:
    assert (XmlRiverProvider.required, XmlStockProvider.required) == (True, False)


# --- health_check: баланс счёта, один запрос без повторов ---------------------------


def checked(cls: type[WordstatProvider], respond) -> tuple[Health, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    provider = cls(CRED)
    provider.health_transport = httpx.MockTransport(handler)
    return provider.health_check(), seen


@pytest.mark.parametrize(
    ("cls", "body", "url"),
    [
        (XmlRiverProvider, "1840.5", "https://xmlriver.com/api/get_balance/?user=u&key=t"),
        (XmlStockProvider, '{"balance": 1840.5}', "https://xmlstock.com/api/?do=balance&user=u&key=t"),
    ],
)
def test_health_check_reads_balance(cls, body, url) -> None:
    health, seen = checked(cls, lambda request: httpx.Response(200, text=body))
    assert health.status == "ok"
    assert health.quota is not None
    assert (health.quota.remaining, health.quota.unit) == (1840, "rub")
    assert [str(r.url) for r in seen] == [url]


@pytest.mark.parametrize("cls", [XmlRiverProvider, XmlStockProvider])
def test_health_check_zero_balance_is_quota_exhausted(cls) -> None:
    body = "0" if cls is XmlRiverProvider else '{"balance": 0}'
    health, _ = checked(cls, lambda request: httpx.Response(200, text=body))
    assert health.status == "quota_exhausted"


@pytest.mark.parametrize(
    ("cls", "body"),
    [
        (XmlRiverProvider, '<response><error code="42">ключ содержит ошибку</error></response>'),
        (XmlStockProvider, "ERROR_KEY"),
    ],
)
def test_health_check_bad_credential_is_auth_required(cls, body) -> None:
    with pytest.raises(AuthRequired):
        checked(cls, lambda request: httpx.Response(200, text=body))
    with pytest.raises(AuthRequired):
        checked(cls, lambda request: httpx.Response(401))


@pytest.mark.parametrize("cls", [XmlRiverProvider, XmlStockProvider])
def test_health_check_failures_are_provider_errors_without_retry(cls) -> None:
    with pytest.raises(ProviderError, match="неожиданный ответ"):
        checked(cls, lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(ProviderError, match="HTTP 503"):
        checked(cls, lambda request: httpx.Response(503))

    calls: list[int] = []

    def slow(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError, match="ReadTimeout"):
        checked(cls, slow)
    assert calls == [1]


# --- provider contract: every provider can prove its credential works -------------


@pytest.mark.parametrize("provider_cls", all_providers(), ids=lambda cls: cls.name)
def test_every_provider_implements_health_check(provider_cls: type[Provider]) -> None:
    # Only the override is checked: constructing a provider may need config or
    # env, which is `for_health_check()`'s job, not this test's.
    assert provider_cls.health_check is not Provider.health_check, (
        f"{provider_cls.__name__} must implement health_check() — `auth status --check` calls it"
    )


def test_every_registered_provider_is_discovered() -> None:
    assert {cls.name for cls in all_providers()} == {"xmlriver", "xmlstock"}


def test_all_providers_discovers_package_classes_only() -> None:
    # Subclasses stay registered on Provider while they're referenced, so this
    # test drops them (and collects) at the end — later tests see the real set.
    def make_classes() -> tuple[type, type, type]:
        class Found(Provider):
            __module__ = "rb_wordstat.providers.fake"
            name = "found"

            def health_check(self) -> Health:
                return Health()

        class Base(Provider):
            __module__ = "rb_wordstat.providers.fake"
            abstract = True

        class Elsewhere(Provider):  # defined outside providers/: not discovered
            name = "elsewhere"

        return Found, Base, Elsewhere

    before = set(all_providers())
    found, base, elsewhere = make_classes()
    discovered = all_providers()
    assert found in discovered
    assert base not in discovered
    assert elsewhere not in discovered
    del found, base, elsewhere, discovered
    gc.collect()
    assert set(all_providers()) == before
