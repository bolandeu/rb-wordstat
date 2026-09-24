from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class FreqType(str, Enum):
    broad = "broad"            # базовая — запрос без операторов
    phrase = "phrase"          # фразовая — "запрос"
    exact = "exact"            # точная — "!слово !слово"
    exact_ord = "exact_ord"    # точная с порядком — "[!слово !слово]"

    def apply(self, query: str) -> str:
        """Применяет оператор Яндекс.Wordstat к запросу."""
        if self == FreqType.broad:
            return query
        elif self == FreqType.phrase:
            return f'"{query}"'
        elif self == FreqType.exact:
            inner = " ".join(f"!{w}" for w in query.split())
            return f'"{inner}"'
        elif self == FreqType.exact_ord:
            inner = " ".join(f"!{w}" for w in query.split())
            return f'"[{inner}]"'
        return query

    @property
    def label(self) -> str:
        labels = {
            FreqType.broad: "базовая",
            FreqType.phrase: "фразовая",
            FreqType.exact: "точная",
            FreqType.exact_ord: "точная+порядок",
        }
        return labels[self]


class WordstatEntry(BaseModel):
    text: str
    value: int


class WordstatResult(BaseModel):
    query: str                         # оригинальный запрос (без операторов)
    freq_type: FreqType                # тип частоты
    total_value: int                   # totalValue из ответа API
    popular: list[WordstatEntry]       # похожие запросы
    associations: list[WordstatEntry]  # ассоциированные запросы


ALL_FREQ_TYPES: list[FreqType] = [
    FreqType.broad,
    FreqType.phrase,
    FreqType.exact,
    FreqType.exact_ord,
]


class WordstatParams(BaseModel):
    query: str | list[str]
    lr: int = 213                          # 213 = Москва
    freq: list[FreqType] = [FreqType.broad]

    def get_queries(self) -> list[str]:
        if isinstance(self.query, str):
            return [self.query]
        return self.query
