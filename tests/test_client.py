"""Тесты клиента и провайдера (с mock HTTP)."""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from rb_wordstat.core.models import FreqType, WordstatParams, WordstatResult, WordstatEntry
from rb_wordstat.providers.xmlriver import XmlRiverWordstatProvider


# Пример ответа от API (broad)
MOCK_RESPONSE_BROAD = {
    "totalValue": 8615,
    "table": {
        "tableData": {
            "popular": [
                {"isAssociations": False, "value": "5716", "text": "растаможка авто"},
                {"isAssociations": False, "value": "3145", "text": "калькулятор растаможки авто"},
            ],
            "associations": [
                {"isAssociations": True, "value": "74067", "text": "таможня"},
                {"isAssociations": True, "value": "16749", "text": "таможенная пошлина"},
            ],
        },
        "isQueryInvalid": False,
        "noData": {"popular": False, "associations": False},
    },
    "graph": {"isQueryInvalid": False, "noData": False},
    "map": {"isQueryInvalid": False, "noData": True},
}

# Пример ответа от API (exact_ord)
MOCK_RESPONSE_EXACT_ORD = {
    "totalValue": 167,
    "table": {
        "tableData": {
            "popular": [
                {"isAssociations": False, "value": "5716", "text": "купить угловой диван"},
            ],
            "associations": [
                {"isAssociations": True, "value": "2056", "text": "книжный шкаф купить"},
            ],
        },
        "isQueryInvalid": False,
        "noData": {"popular": False, "associations": False},
    },
    "graph": {"isQueryInvalid": False, "noData": False},
}


class TestXmlRiverProviderParsing:
    """Тесты парсинга ответа от API (без HTTP)."""

    def _make_provider(self):
        with patch.dict("os.environ", {"XMLRIVER_USER": "test_user", "XMLRIVER_TOKEN": "test_token"}):
            return XmlRiverWordstatProvider()

    def test_parse_broad_response(self):
        provider = self._make_provider()
        result = provider._parse_response(MOCK_RESPONSE_BROAD, "растаможка авто", FreqType.broad)

        assert result.query == "растаможка авто"
        assert result.freq_type == FreqType.broad
        assert result.total_value == 8615
        assert len(result.popular) == 2
        assert result.popular[0].text == "растаможка авто"
        assert result.popular[0].value == 5716
        assert len(result.associations) == 2
        assert result.associations[0].text == "таможня"
        assert result.associations[0].value == 74067

    def test_parse_exact_ord_response(self):
        provider = self._make_provider()
        result = provider._parse_response(MOCK_RESPONSE_EXACT_ORD, "купить угловой диван", FreqType.exact_ord)

        assert result.total_value == 167
        assert result.freq_type == FreqType.exact_ord
        assert len(result.popular) == 1

    def test_parse_empty_table_data(self):
        provider = self._make_provider()
        result = provider._parse_response(
            {"totalValue": 0, "table": {"tableData": {}}},
            "несуществующий запрос",
            FreqType.broad,
        )
        assert result.total_value == 0
        assert result.popular == []
        assert result.associations == []

    def test_parse_missing_total_value(self):
        provider = self._make_provider()
        result = provider._parse_response(
            {"table": {"tableData": {"popular": [], "associations": []}}},
            "запрос",
            FreqType.broad,
        )
        assert result.total_value == 0

    def test_parse_value_with_spaces(self):
        """Проверяет парсинг значений с пробелами (11 067 → 11067)."""
        provider = self._make_provider()
        data = {
            "totalValue": 11067,
            "table": {
                "tableData": {
                    "popular": [{"isAssociations": False, "value": "11 067", "text": "тест"}],
                    "associations": [],
                }
            },
        }
        result = provider._parse_response(data, "тест", FreqType.broad)
        assert result.popular[0].value == 11067


@pytest.mark.asyncio
class TestXmlRiverProviderSearch:
    """Тесты метода search с мок HTTP-клиентом."""

    def _make_provider(self):
        with patch.dict("os.environ", {"XMLRIVER_USER": "test_user", "XMLRIVER_TOKEN": "test_token"}):
            return XmlRiverWordstatProvider()

    async def test_search_single_query_broad(self):
        provider = self._make_provider()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=MOCK_RESPONSE_BROAD)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rb_wordstat.providers.xmlriver.httpx.AsyncClient", return_value=mock_client):
            params = WordstatParams(query="растаможка авто", freq=[FreqType.broad])
            results = await provider.search(params)

        assert len(results) == 1
        assert results[0].query == "растаможка авто"
        assert results[0].total_value == 8615

    async def test_search_multiple_freq_types(self):
        provider = self._make_provider()

        responses = [MOCK_RESPONSE_BROAD, MOCK_RESPONSE_EXACT_ORD]
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=responses[call_count % 2])
            call_count += 1
            return mock_resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rb_wordstat.providers.xmlriver.httpx.AsyncClient", return_value=mock_client):
            params = WordstatParams(
                query="купить диван",
                freq=[FreqType.broad, FreqType.exact_ord],
            )
            results = await provider.search(params)

        assert len(results) == 2
        freq_types = {r.freq_type for r in results}
        assert FreqType.broad in freq_types
        assert FreqType.exact_ord in freq_types

    async def test_search_multiple_queries(self):
        provider = self._make_provider()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=MOCK_RESPONSE_BROAD)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rb_wordstat.providers.xmlriver.httpx.AsyncClient", return_value=mock_client):
            params = WordstatParams(
                query=["диван", "кресло", "стол"],
                freq=[FreqType.broad],
            )
            results = await provider.search(params)

        assert len(results) == 3
        queries = [r.query for r in results]
        assert "диван" in queries
        assert "кресло" in queries
        assert "стол" in queries

    async def test_search_handles_http_error_gracefully(self):
        provider = self._make_provider()

        import httpx
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Connection error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rb_wordstat.providers.xmlriver.httpx.AsyncClient", return_value=mock_client):
            params = WordstatParams(query="тест", freq=[FreqType.broad])
            results = await provider.search(params)

        # При ошибке возвращает WordstatResult с total_value=0
        assert len(results) == 1
        assert results[0].total_value == 0
        assert results[0].popular == []


@pytest.mark.asyncio
class TestXmlRiverRetry:
    """Тесты retry-логики (3 попытки с задержкой)."""

    def _make_provider(self):
        with patch.dict("os.environ", {"XMLRIVER_USER": "test_user", "XMLRIVER_TOKEN": "test_token"}):
            return XmlRiverWordstatProvider()

    async def test_retry_succeeds_on_third_attempt(self):
        """На 3-й попытке получает данные после двух ошибок."""
        import httpx
        provider = self._make_provider()
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.HTTPError("Временная ошибка")
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value=MOCK_RESPONSE_BROAD)
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rb_wordstat.providers.xmlriver.httpx.AsyncClient", return_value=mock_client):
            with patch("rb_wordstat.providers.xmlriver.asyncio.sleep", new_callable=AsyncMock):
                params = WordstatParams(query="тест", freq=[FreqType.broad])
                results = await provider.search(params)

        assert call_count == 3
        assert results[0].total_value == 8615

    async def test_retry_exhausted_returns_zero(self):
        """После 3 неудачных попыток возвращает total_value=0."""
        import httpx
        provider = self._make_provider()
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise httpx.HTTPError("Постоянная ошибка")

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rb_wordstat.providers.xmlriver.httpx.AsyncClient", return_value=mock_client):
            with patch("rb_wordstat.providers.xmlriver.asyncio.sleep", new_callable=AsyncMock):
                params = WordstatParams(query="тест", freq=[FreqType.broad])
                results = await provider.search(params)

        assert call_count == 3
        assert results[0].total_value == 0
        assert results[0].popular == []

    async def test_api_error_field_triggers_retry(self):
        """API-ответ с полем 'error' вызывает повтор."""
        provider = self._make_provider()
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if call_count < 2:
                resp.json = MagicMock(return_value={"error": "quota exceeded"})
            else:
                resp.json = MagicMock(return_value=MOCK_RESPONSE_BROAD)
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("rb_wordstat.providers.xmlriver.httpx.AsyncClient", return_value=mock_client):
            with patch("rb_wordstat.providers.xmlriver.asyncio.sleep", new_callable=AsyncMock):
                params = WordstatParams(query="тест", freq=[FreqType.broad])
                results = await provider.search(params)

        assert call_count == 2
        assert results[0].total_value == 8615


class TestProviderCredentials:
    def test_raises_without_env_vars(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("XMLRIVER_USER", None)
            os.environ.pop("XMLRIVER_TOKEN", None)
            with pytest.raises(RuntimeError, match="XMLRIVER_USER"):
                XmlRiverWordstatProvider()
