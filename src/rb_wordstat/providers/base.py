from abc import ABC, abstractmethod

from ..core.models import WordstatParams, WordstatResult


class WordstatProvider(ABC):
    """Абстрактный интерфейс провайдера Wordstat."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Имя провайдера."""
        ...

    @abstractmethod
    async def search(self, params: WordstatParams) -> list[WordstatResult]:
        """Выполняет запросы и возвращает результаты."""
        ...
