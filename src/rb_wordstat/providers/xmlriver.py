from __future__ import annotations

from .base import ApiError, WordstatProvider, to_int

# Коды ошибок: https://xmlriver.com/api/api-errors/ (те же, что у выдачи в serp).
_NO_RESULTS = 15
_AUTH_ERRORS = frozenset({31, 42})
_RETRY_ERRORS = frozenset({20, 21, 22, 23, 24, 101, 110, 111, 202, 203, 500})


class XmlRiverProvider(WordstatProvider):
    """Wordstat через XML River: https://xmlriver.com/apiwordstat/.

    Ответ: `totalValue`, `table.tableData.popular` / `.associations` — записи
    `{"text", "value"}`, до 200 похожих. Ошибка: `{"code": N, "error": "..."}`.
    """

    name = "xmlriver"
    summary = "XML River"
    url = "https://xmlriver.com/wordstat/new/json"
    legacy_env = {"user": "XMLRIVER_USER", "token": "XMLRIVER_TOKEN"}  # noqa: RUF012 — ClassVar в базе

    def _params(self, query_sent: str, lr: int) -> dict:
        return {"user": self._credential["user"], "key": self._credential["token"], "query": query_sent, "regions": lr}

    def _api_error(self, data: dict) -> ApiError | None:
        if "error" not in data:
            return None
        message = f"ошибка {data.get('code')}: {data['error']}"
        try:
            code = int(str(data.get("code")))
        except ValueError:
            return ApiError("retry", message)
        if code == _NO_RESULTS:
            return ApiError("empty", message)
        if code in _AUTH_ERRORS:
            return ApiError("auth", message)
        return ApiError("retry" if code in _RETRY_ERRORS else "fatal", message)

    def _parse(self, data: dict) -> tuple[int, list[dict], list[dict]]:
        table = data.get("table", {}).get("tableData", {})
        return to_int(data.get("totalValue") or 0), table.get("popular", []), table.get("associations", [])
