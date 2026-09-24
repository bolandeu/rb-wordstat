# Changelog

All notable changes to this project are documented here. The format is
[Keep a Changelog](https://keepachangelog.com/), versions follow
[SemVer](https://semver.org/). `scripts/release.py` moves the Unreleased
section under a new version heading — add entries here as you go, don't
write them at release time.

## [Unreleased]

### Changed

- CLI переведён на архитектуру cli-generator (Typer), как у serp: одна
  команда `wordstat` вместо `rb-wordstat`; `--json` с конвертом
  `{"ok": ..., "results": [...]}` вместо `--format json`; структурные ошибки
  и фиксированные коды выхода. Python-пакет по-прежнему `rb-wordstat` /
  `from rb_wordstat import WordstatClient, WordstatParams, ...`.
- Доступы — в OS keychain (`wordstat auth login`) или env
  `WORDSTAT_<PROVIDER>_<FIELD>`; если своих нет — общие с serp (`SERP_*`,
  keychain `serp:<provider>`), затем старые `XMLRIVER_USER`/`XMLRIVER_TOKEN`.
  `.env`-файлы больше не загружаются.
- Логирование: stdlib `logging` (логгер `rb_wordstat`) вместо loguru.

### Added

- Провайдер `xmlstock` (XMLStock, `xmlstock.com/wordstat/json/`) и очередь
  провайдеров с фолбэком: `search --provider a,b`, `providers` в
  `.wordstat/config.toml`; по умолчанию `xmlriver`. У каждого результата —
  поле `provider`.
- Команды `doctor`, `status`, `init`, `config`, `auth`, `skill`, флаг `--ai`;
  справка на русском.

### Removed

- MCP-сервер (`rb-wordstat mcp`) и зависимости `mcp`, `click`,
  `python-dotenv`, `loguru`: агенты вызывают CLI с `--json` по памятке
  `wordstat --ai`.

### Fixed

- Сбой провайдера (неверный ключ, нет денег, сеть) больше не выглядит как
  частота 0 с exit 0: фолбэк на следующий провайдер, иначе `AUTH_REQUIRED`
  (3) / `PROVIDER_ERROR` (5). Код 15 XML River («нет результатов») — частота
  0 без повторов.
- Неверный ключ XML River больше не повторяется впустую 3 раза.
- Windows: `skill install` и `--ai` читают и пишут SKILL.md в UTF-8
  (кириллица падала в кодировке по умолчанию cp1252).
- Зависимости в `uv.lock` обновлены до версий без известных уязвимостей
  (anyio, cryptography, idna, pygments, pytest) — аудит OSV-Scanner в CI.
