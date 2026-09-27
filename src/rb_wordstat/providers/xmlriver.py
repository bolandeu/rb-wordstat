from __future__ import annotations

import re
from typing import ClassVar

from ..core.errors import AuthRequired, ProviderError
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
    balance_url = "https://xmlriver.com/api/get_balance/"
    legacy_env: ClassVar[dict[str, str]] = {"user": "XMLRIVER_USER", "token": "XMLRIVER_TOKEN"}

    def _balance_params(self) -> dict:
        return {"user": self._credential["user"], "key": self._credential["token"]}

    def _parse_balance(self, text: str) -> float:
        # Баланс — число в теле ответа; ошибка — как у выдачи, <error code="N">…</error>.
        try:
            return float(text.strip())
        except ValueError:
            pass
        match = re.search(r'code="?(\d+)', text)
        if match and int(match.group(1)) in _AUTH_ERRORS:
            raise AuthRequired(self.name)
        raise ProviderError(self.name, f"баланс: неожиданный ответ ({text.strip()[:100]!r})")

    def _params(self, query_sent: str, lr: int) -> dict:
        return {"user": self._credential["user"], "key": self._credential["token"], "query": query_sent, "regions": lr}

    @classmethod
    def _api_error(cls, data: dict) -> ApiError | None:
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

    @classmethod
    def _parse(cls, data: dict) -> tuple[int, list[dict], list[dict]]:
        table = data.get("table", {}).get("tableData", {})
        return to_int(data.get("totalValue") or 0), table.get("popular", []), table.get("associations", [])
