from __future__ import annotations

import json

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .core.client import WordstatClient
from .core.models import ALL_FREQ_TYPES, FreqType, WordstatParams

server = Server("rb-wordstat")
_client: WordstatClient | None = None


def _get_client() -> WordstatClient:
    global _client
    if _client is None:
        _client = WordstatClient()
    return _client


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="search_wordstat",
            description=(
                "Получить данные Яндекс.Wordstat для одного или нескольких запросов. "
                "Возвращает частоту (totalValue), похожие запросы (popular) и ассоциации (associations). "
                "Поддерживает операторы: broad=базовая, phrase=фразовая (\"запрос\"), "
                "exact=точная (\"!слово !слово\"), exact_ord=точная+порядок (\"[!слово !слово]\")."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "oneOf": [
                            {"type": "string", "description": "Поисковый запрос"},
                            {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Список запросов",
                            },
                        ]
                    },
                    "lr": {
                        "type": "integer",
                        "default": 213,
                        "description": (
                            "Код региона Яндекса. "
                            "213=Москва, 2=СПб, 35=Краснодар, 65=Новосибирск, 54=Екатеринбург."
                        ),
                    },
                    "freq": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["broad", "phrase", "exact", "exact_ord"],
                        },
                        "default": ["broad"],
                        "description": (
                            "Типы частоты для сбора. "
                            "broad=базовая, phrase=фразовая, exact=точная, exact_ord=точная+порядок."
                        ),
                    },
                },
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name != "search_wordstat":
        raise ValueError(f"Неизвестный инструмент: {name}")

    raw_freq = arguments.get("freq", ["broad"])
    freq_map = {
        "broad": FreqType.broad,
        "phrase": FreqType.phrase,
        "exact": FreqType.exact,
        "exact_ord": FreqType.exact_ord,
    }
    freq_types = [freq_map[f] for f in raw_freq if f in freq_map] or [FreqType.broad]

    params = WordstatParams(
        query=arguments["query"],
        lr=arguments.get("lr", 213),
        freq=freq_types,
    )

    results = await _get_client().search(params)
    data = [r.model_dump() for r in results]
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


def serve() -> None:
    """Entry-point для MCP-сервера."""
    import asyncio
    from pathlib import Path

    from loguru import logger
    load_dotenv()

    log_dir = Path.home() / ".local/state/logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(log_dir / "mcp-rb-wordstat.log", rotation="10 MB", retention="7 days")

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())
