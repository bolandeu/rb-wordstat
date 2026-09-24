"""rb-wordstat — Яндекс.Wordstat клиент: библиотека, CLI и MCP-сервер."""
from .core.client import WordstatClient
from .core.models import FreqType, WordstatEntry, WordstatParams, WordstatResult

__version__ = "0.1.0"
__all__ = ["WordstatClient", "WordstatParams", "WordstatResult", "WordstatEntry", "FreqType"]
