# Changelog

All notable changes to this project are documented here. Versions follow
[SemVer](https://semver.org/) (while at `0.x`, a minor bump may break).

Don't edit this file between releases: each change adds a fragment to
`changelog.d/` (`uv run towncrier create +<slug>.<type>.md -c "..."`, type
one of added/changed/deprecated/removed/fixed/security), and
`scripts/release.py` assembles them into a new section below the marker.

<!-- towncrier release notes start -->

## [0.3.1] - 2026-09-28

### Changed

- Шаблон cli-generator v1.2.8: общие с serp доступы и порядок источников — средствами шаблона (`shared_namespaces`). Порядок по полю теперь: env `WORDSTAT_*` → env `SERP_*` → keychain `wordstat:` → keychain `serp:` → старые `XMLRIVER_*`; пустая env-переменная считается заданной.


## [0.3.0] - 2026-09-27

### Changed

- Шаблон cli-generator v1.2.3 и стандарт релизов: версия берётся из git-тега, changelog собирается из фрагментов changelog.d/, справка команд проверяется снапшотами. **Несовместимо:** `wordstat auth status` теперь отдаёт отчёт по стандарту §8 (`tool`, `version`, `checked_at`, `credentials[]` с `provider`, `required`, `source`, `source_ref`, `status`, `quota`…) по всем провайдерам сразу вместо `{"provider", "authenticated"}`; код выхода 3, если обязательный xmlriver не в порядке (xmlstock — необязательный). Новый флаг `--check` проверяет ключи бесплатным запросом баланса и показывает остаток в рублях. Порядок поиска ключей прежний: `WORDSTAT_*` → keychain `wordstat:` → `SERP_*` → keychain `serp:` → `XMLRIVER_USER`/`XMLRIVER_TOKEN`.


## [0.2.0] - 2026-09-24

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
- Журнал всех ответов провайдеров, как у serp: SQLite `wordstat.db` в папке
  данных приложения (вся история, сжатый JSON без логина и ключа, путь —
  `WORDSTAT_DB_PATH`); `search --cache`, `--max-age`, `--force`; команды
  `wordstat cache info|list|clear` (`clear` — с `--dry-run` / `--confirm`).
  `--cache` берёт ответ только провайдеров из очереди `--provider`, в её
  порядке. У результата — `fetched_at` и `from_cache`.

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
  (кириллица падала в кодировке по умолчанию cp1252); `.wordstat/config.toml`
  тоже всегда в UTF-8.
- Windows: вывод в pipe (агенты, CI, `> файл`) падал с `UnicodeEncodeError`
  на кириллице — stdout/stderr теперь всегда в UTF-8.
- Зависимости в `uv.lock` обновлены до версий без известных уязвимостей
  (anyio, cryptography, idna, pygments, pytest) — аудит OSV-Scanner в CI.
