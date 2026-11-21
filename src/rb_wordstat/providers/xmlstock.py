from __future__ import annotations

import json

from ..core.errors import AuthRequired, ProviderError
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
    balance_url = "https://xmlstock.com/api/"
    # Запасной провайдер: без его доступов wordstat работает через xmlriver.
    required = False

    def _balance_params(self) -> dict:
        return {"do": "balance", "user": self._credential["user"], "key": self._credential["token"]}

    def _parse_balance(self, text: str) -> float:
        # {"balance": 123.4} либо строка ERROR_… (ERROR_USER / ERROR_KEY — неверный доступ).
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("balance"), int | float):
            return float(data["balance"])
        answer = text.strip()
        if answer.startswith("ERROR_") and ("KEY" in answer or "USER" in answer):
            raise AuthRequired(self.name)
        raise ProviderError(self.name, f"баланс: неожиданный ответ ({answer[:100]!r})")

    def _params(self, query_sent: str, lr: int, *, device: str | None = None, limit: int | None = None) -> dict:
        # `device` и `groupby` — из их же параметров: пустое устройство значит все, groupby 1..2000.
        return {
            "user": self._credential["user"],
            "key": self._credential["token"],
            "query": query_sent,
            "regions": lr,
            "groupby": limit or _GROUPBY,
            "device": device or "all",
        }

    @classmethod
    def _api_error(cls, data: dict) -> ApiError | None:
        error = data.get("error")
        if not error:
            return None
        if not isinstance(error, dict):
            return ApiError("retry", str(error))
        message = f"ошибка {error.get('code')}: {error.get('message')}"
        return ApiError("auth" if error.get("code") in _AUTH_ERRORS else "retry", message)

    @classmethod
    def _parse(cls, data: dict) -> tuple[int, list[dict], list[dict]]:
        def rows(items: list[dict]) -> list[dict]:
            return [{"text": item.get("phrase"), "value": item.get("count")} for item in items]

        return (
            to_int(data.get("totalCount") or 0),
            rows(data.get("results", [])),
            rows(data.get("associations", [])),
        )
