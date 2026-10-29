# Changelog

All notable changes to this project are documented here. Versions follow
[SemVer](https://semver.org/) (while at `0.x`, a minor bump may break).

The changelog is written by `antagor publish`; don't edit it by hand.

## v0.7.2 — 2026-10-29

### Outside epics

- Journal read: an unreadable row is a cache miss with one warning (T432) (WORDSTAT-002)

## v0.7.1 — 2026-10-26

### Main

- Merge pull request #1: template v1.27.3 (Renovate)
- chore(template): Update dependency https://homeserver.tailee01ab.ts.net:3000/bolandeu/cli-generator.git to v1.27.3


## v0.7.0 — 2026-10-23

### Outside epics

- Ignore the revoked XML River key in git history by fingerprint (WORDSTAT-001)

## [0.6.2] - 2026-10-03

### Added

- search --json: стоимость — за каждый платный ответ провайдера: у результата billable_requests (сколько платных ответов ушло на пару запрос × тип частоты; ответы-ошибки, повторы и отказавший перед фолбэком провайдер не считаются; из журнала — 0), cost = billable_requests × цена, в конверте billable_requests_total.


## [0.6.1] - 2026-10-03

### Added

- search --json: у каждого результата cost_source — откуда cost: price_table (цена × единицы), cache (из журнала, 0), null (цены нет); provider — фактическая стоимость из ответа провайдера (XML River и XMLStock её не отдают). На сервере и в Windmill цена — только WORDSTAT_<PROVIDER>_PRICE.


## [0.6.0] - 2026-10-03

### Added

- search --json: у каждого результата cost (руб., из журнала — 0) и cost_currency "RUB", в конверте cost_total. Цена запроса — [prices] <провайдер> в конфиге проекта или WORDSTAT_<PROVIDER>_PRICE (перекрывает конфиг); не задана — null и предупреждение в stderr.

### Changed

- Шаблон cli-generator v1.5.6: TDD в правилах, шаг гейта «existing tests», мутационное тестирование (`uv run --group mutation mutmut run`).


## [0.5.2] - 2026-10-02

### Changed

- Шаблон cli-generator v1.5.5: порядок релиза — никто из агентов не пушит, готовность сообщается tools, пушит dev после согласия пользователя.


## [0.5.1] - 2026-10-02

### Changed

- Шаблон cli-generator v1.5.3: `describe --json` берёт имя локальной базы из `db.sqlite_path()`.


## [0.5.0] - 2026-10-02

### Added

- Шаблон cli-generator v1.5.1: `wordstat describe --json` — контракт CLI в формате OpenCLI (команды, опции, коды выхода, переменные окружения, таблицы и представление `wordstat_v1_responses`).


## [0.4.0] - 2026-10-01

### Added

- Дата получения данных видна в обычном выводе `search` («данные от …, из журнала») и в CSV (колонка `fetched_at`).
- Журнал ответов можно держать в общей PostgreSQL: `WORDSTAT_DATABASE_URL` (иначе локальный SQLite, как раньше). Новые команды `db status`, `db upgrade` (единственный способ обновить схему общей базы), `db import-sqlite` (перенос локального журнала) и `db push` (отправка локальных ответов в прод по `WORDSTAT_PROD_DATABASE_URL`, уже имеющиеся пропускаются). Другим инструментам — представление `wordstat_v1_responses`.

### Changed

- Журнал переехал в таблицу `wordstat_responses`: старая `responses` переносится при первом запуске с исходными датами. Ключ запроса теперь не различает ё и е. В `cache list --json` поле `region` — число, а не строка; `cache info` для PostgreSQL показывает адрес базы вместо пути.


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
