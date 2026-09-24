from __future__ import annotations

from .base import ApiError, WordstatProvider, to_int

# Неверный user/key. Других кодов XMLStock не публикует — их повторяем.
_AUTH_ERRORS = frozenset({-34})
# Столько же похожих запросов, сколько отдаёт XML River (без groupby — 2000).
_GROUPBY = 200


class XmlStockProvider(WordstatProvider):
    """Wordstat через XMLStock: https://xmlstock.com/?do=help-wordstat-params.

    Ответ: `totalCount`, `results` / `associations` — записи `{"phrase",
    "count"}`. Ошибка: `{"error": {"code": N, "message": "..."}}`. `token` —
    это `key` из кабинета XMLStock (тот же, что у serp).
    """

    name = "xmlstock"
    summary = "XMLStock"
    url = "https://xmlstock.com/wordstat/json/"

    def _params(self, query_sent: str, lr: int) -> dict:
        return {
            "user": self._credential["user"],
            "key": self._credential["token"],
            "query": query_sent,
            "regions": lr,
            "groupby": _GROUPBY,
        }

    def _api_error(self, data: dict) -> ApiError | None:
        error = data.get("error")
        if not error:
            return None
        if not isinstance(error, dict):
            return ApiError("retry", str(error))
        message = f"ошибка {error.get('code')}: {error.get('message')}"
        return ApiError("auth" if error.get("code") in _AUTH_ERRORS else "retry", message)

    def _parse(self, data: dict) -> tuple[int, list[dict], list[dict]]:
        def rows(items: list[dict]) -> list[dict]:
            return [{"text": item.get("phrase"), "value": item.get("count")} for item in items]

        return (
            to_int(data.get("totalCount") or 0),
            rows(data.get("results", [])),
            rows(data.get("associations", [])),
        )
