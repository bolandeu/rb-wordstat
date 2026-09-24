"""rb-wordstat — частоты Яндекс.Wordstat: CLI `wordstat` и библиотека."""

from .core.client import WordstatClient
from .core.errors import AuthRequired, ProviderError
from .core.models import ALL_FREQ_TYPES, FreqType, WordstatEntry, WordstatParams, WordstatResult

__all__ = [
    "ALL_FREQ_TYPES",
    "AuthRequired",
    "FreqType",
    "ProviderError",
    "WordstatClient",
    "WordstatEntry",
    "WordstatParams",
    "WordstatResult",
]
