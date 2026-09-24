# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (editable mode)
uv sync --all-extras

# Run CLI
uv run rb-wordstat search "запрос"

# Run tests
uv run pytest

# Run MCP server (stdio)
uv run rb-wordstat mcp
```

## Architecture

**Three usage modes:** Python library, CLI (`rb-wordstat search`), and MCP server (`rb-wordstat mcp`).

**Source layout:** `src/rb_wordstat/`

- `core/models.py` — `FreqType` (broad/phrase/exact/exact_ord + apply() operator), `WordstatParams` (input), `WordstatResult` (output), `WordstatEntry` (keyword+value)
- `core/client.py` — `WordstatClient`: thin async wrapper; `search()` is async, `search_sync()` wraps with `asyncio.run()`
- `providers/base.py` — Abstract `WordstatProvider` with `async def search(params) -> list[WordstatResult]`
- `providers/xmlriver.py` — `XmlRiverWordstatProvider`: fetches all query×freq_type pairs in parallel (semaphore-limited to 10), up to 3 retries with 1s delay, parses JSON responses
- `cli.py` — Click CLI; `search` command (--freq supports `broad,phrase` comma-syntax or repeated flags, --no-keywords suppresses console keywords output), `mcp` command starts the MCP server
- `mcp_server.py` — MCP server exposing one tool `search_wordstat`; MCP logs go to `~/.local/state/logs/mcp-rb-wordstat.log`

**Endpoint:** `https://xmlriver.com/wordstat/new/json?query=...&user=...&key=...&lr=...`

**Credentials:** Loaded from `~/Projects/_shared/credentials/.env.shared` via `python-dotenv`. Required env vars: `XMLRIVER_USER`, `XMLRIVER_TOKEN`.

**FreqType operators:**
- `broad` — запрос без операторов (базовая)
- `phrase` — `"запрос"` (фразовая)
- `exact` — `"!слово !слово"` (точная словоформа)
- `exact_ord` — `"[!слово !слово]"` (точная словоформа + порядок)

**Response parsing:**
- `totalValue` — частота запроса
- `table.tableData.popular` — похожие запросы (isAssociations=false)
- `table.tableData.associations` — ассоциации (isAssociations=true)

**CSV modes:**
- `freq` — query|freq_type|freq_label|operator|total_value
- `keywords` — source_query|type|keyword|value (from popular+assoc of broad results)
- `auto` (default) — freq при >1 freq types, keywords при только broad

**Logging:** Uses `loguru`. Silence with `logger.disable("rb_wordstat")`.

**Defaults:** lr=213 (Москва), freq=[broad].
