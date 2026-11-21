"""The pydantic models of the project's config file."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class FreqType(StrEnum):
    broad = "broad"  # базовая — запрос без операторов
    phrase = "phrase"  # фразовая — "запрос"
    exact = "exact"  # точная — "!слово !слово"
    exact_ord = "exact_ord"  # точная с порядком — "[!слово !слово]"

    def apply(self, query: str) -> str:
        """Применяет оператор Яндекс.Wordstat к запросу."""
        if self == FreqType.phrase:
            return f'"{query}"'
        if self in (FreqType.exact, FreqType.exact_ord):
            inner = " ".join(f"!{w}" for w in query.split())
            return f'"[{inner}]"' if self == FreqType.exact_ord else f'"{inner}"'
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


DEVICES: tuple[str, ...] = ("desktop", "phone", "mobile", "tablet")

ALL_FREQ_TYPES: list[FreqType] = [
    FreqType.broad,
    FreqType.phrase,
    FreqType.exact,
    FreqType.exact_ord,
]


class WordstatEntry(BaseModel):
    text: str
    value: int


class WordstatResult(BaseModel):
    query: str  # оригинальный запрос (без операторов)
    freq_type: FreqType  # тип частоты
    total_value: int  # частота запроса
    popular: list[WordstatEntry]  # похожие запросы
    associations: list[WordstatEntry]  # ассоциированные запросы
    provider: str = ""  # какой провайдер из очереди ответил
    fetched_at: datetime | None = None  # когда провайдер отдал этот ответ
    from_cache: bool = False  # взят из журнала (--cache), а не живым запросом
    billable_requests: int = 1  # платных ответов провайдера на пару; из журнала — 0


class WordstatParams(BaseModel):
    query: str | list[str]
    lr: int = 213  # 213 = Москва
    freq: list[FreqType] = Field(default_factory=lambda: [FreqType.broad])
    # Устройства через запятую: desktop, phone (mobile), tablet; пусто — все устройства.
    device: str | None = None
    # Сколько похожих фраз просить: XMLStock `groupby`, 1..2000; None — умолчание провайдера.
    limit: int | None = Field(default=None, ge=1, le=2000)

    @field_validator("device", mode="before")
    @classmethod
    def clean_device(cls, v: object) -> object:
        """`desktop, phone` → `desktop,phone`; мусор — ошибка, а не молчаливые «все устройства»."""
        if v is None:
            return None
        parts = [part.strip().lower() for part in str(v).split(",") if part.strip()]
        unknown = [part for part in parts if part not in DEVICES]
        if unknown:
            raise ValueError(f"device: {', '.join(unknown)} — допустимо {', '.join(DEVICES)}")
        return ",".join(dict.fromkeys(parts)) or None

    def get_queries(self) -> list[str]:
        if isinstance(self.query, str):
            return [self.query]
        return self.query


DEFAULT_PROVIDERS = ["xmlriver"]


class CliCompat(BaseModel):
    min_version: str = "0.1.0"


class ProjectConfig(BaseModel):
    version: int = 1
    name: str
    # Очередь провайдеров: первый — основной, остальные — фолбэки по порядку.
    providers: list[str] = Field(default_factory=lambda: list(DEFAULT_PROVIDERS))
    # Цена одного запроса по провайдеру, руб.: [prices] xmlriver = 0.0; env WORDSTAT_<PROVIDER>_PRICE перекрывает.
    prices: dict[str, float] = Field(default_factory=dict)
    cli: CliCompat = Field(default_factory=CliCompat)

    @field_validator("providers", mode="before")
    @classmethod
    def split_providers(cls, v: object) -> object:
        # `config set providers "a,b"` приходит строкой.
        if isinstance(v, str):
            return [name.strip() for name in v.split(",") if name.strip()]
        return v
