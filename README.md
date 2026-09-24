# wordstat

Частоты Яндекс.Wordstat (базовая, фразовая, точная, точная с порядком) и похожие
запросы / ассоциации через провайдеров [XML River](https://xmlriver.com) и
[XMLStock](https://xmlstock.com) с фолбэком. Работает как CLI (`wordstat search ...`) и как
Python-библиотека (`from rb_wordstat import WordstatClient`). Python-пакет — `rb-wordstat`
(импорт `rb_wordstat`), команда в терминале — `wordstat`.

## Установка

```bash
uv tool install "git+https://github.com/bolandeu/wordstat.git"
```

Одинаково на macOS, Linux и Windows; обновление — `uv tool upgrade rb-wordstat`, конкретная
версия — `...wordstat.git@v0.2.0`.

**Репозиторий приватный.** `uv` ходит в git так же, как `git clone`. Если установка
падает с ошибкой авторизации — один раз `gh auth login` (или `gh auth setup-git`, если
`gh` залогинен через `--with-token`), либо SSH-вариант:

```bash
uv tool install "git+ssh://git@github.com/bolandeu/wordstat.git"
```

Как зависимость другого проекта: `uv add "rb-wordstat @ git+https://github.com/bolandeu/wordstat.git"`.

## Доступы

Доступы XML River и XMLStock **общие с CLI [serp](https://github.com/bolandeu/serp)**: если
`serp auth login` уже был, wordstat их видит и ничего настраивать не нужно. Порядок поиска
для каждого поля (`user`, `token`):

1. свои: env `WORDSTAT_<PROVIDER>_<FIELD>` → keychain `wordstat:<provider>`;
2. общие с serp: env `SERP_<PROVIDER>_<FIELD>` → keychain `serp:<provider>`;
3. только XML River: старые `XMLRIVER_USER` / `XMLRIVER_TOKEN`.

```bash
wordstat auth status --provider xmlstock   # найдены ли доступы
wordstat auth login --provider xmlriver    # свои, если нужны отдельно от serp
wordstat doctor                            # общая диагностика
```

`token` у XMLStock — это `key` из кабинета. `.env`-файлы больше не читаются.

## CLI

```bash
wordstat                      # версия + список команд
wordstat search --help        # все опции
wordstat --ai                 # памятка для AI-агентов
```

| Опция | Коротко | По умолчанию | Описание |
| --- | --- | --- | --- |
| `--freq` | `-f` | `broad` | `broad`, `phrase`, `exact`, `exact-ord`, `all`; через запятую или повтором флага |
| `--lr` | | `213` (Москва) | код региона Яндекса |
| `--provider` | `-p` | `xmlriver` | очередь провайдеров через запятую, см. ниже |
| `--json` | | | конверт `{"ok": true, "count": N, "results": [...]}` в stdout |
| `--output` | `-o` | | дополнительно сохранить: `.csv` → CSV (см. `--csv-mode`), иначе JSON |
| `--csv-mode` | | `auto` | `freq` / `keywords` / `auto` (freq при нескольких типах, иначе keywords) |
| `--no-keywords` | | | в консоли только частоты |

| Тип | Оператор | Пример |
| --- | --- | --- |
| `broad` | без операторов | `купить диван` |
| `phrase` | кавычки | `"купить диван"` |
| `exact` | `!` на каждое слово | `"!купить !диван"` |
| `exact-ord` | `!` + порядок | `"[!купить !диван]"` |

```bash
wordstat search "купить диван"
wordstat search "купить диван" --freq all --no-keywords
wordstat search "диван" "кресло" "стол" --freq broad,phrase --lr 2
wordstat search "купить диван" -p xmlstock,xmlriver
wordstat search "купить диван" --freq all --output freq.csv
wordstat search "купить диван" --output keywords.csv --csv-mode keywords
wordstat search "купить диван" --json | jq '.results[].total_value'
```

CSV `freq`: `query,freq_type,freq_label,operator,total_value`. CSV `keywords`:
`source_query,type,keyword,value` — похожие (`popular`) и ассоциации (`assoc`), только
из результатов `broad`.

**Куда что пишется.** stdout — только данные (таблицы или JSON-конверт); ошибки, логи и
`--verbose` — в stderr. Под `--json` ошибка тоже приходит JSON-ом:
`{"ok": false, "error": {"code", "message", "action"}}`.

**Коды выхода:** `0` ок · `1` прочее · `2` неверные аргументы · `3` нужна авторизация ·
`4` проект не инициализирован · `5` сбой провайдера (сеть, деньги, лимиты — уже с
повторами) · `6` CLI старее, чем требует проект.

Частота 0 — это «запрос не ищут», а не сбой: сбой всегда даёт код 3 или 5.

### Провайдеры и фолбэк

`--provider a,b` — очередь: для каждой пары (запрос, тип частоты) первый провайдер
основной, следующий пробуется, только если предыдущий упал (`AUTH_REQUIRED` /
`PROVIDER_ERROR`). Отказали все → ошибка. В `--json` у каждого результата есть
`provider` — кто ответил.

| Провайдер | Эндпоинт | Похожих запросов |
| --- | --- | --- |
| `xmlriver` | `xmlriver.com/wordstat/new/json` | до 200 |
| `xmlstock` | `xmlstock.com/wordstat/json/` | до 200 (`groupby=200`, без него 2000) |

Частоты у обоих совпадают (проверено 2026-09-24 на «купить диван», Москва).

Очередь можно закрепить за проектом (папкой):

```bash
wordstat init                                   # создаёт .wordstat/config.toml
wordstat config set providers "xmlstock,xmlriver"
```

## Python-библиотека

```python
from rb_wordstat import FreqType, WordstatClient, WordstatParams

client = WordstatClient()  # очередь по умолчанию: ["xmlriver"]
# client = WordstatClient(providers=["xmlstock", "xmlriver"])
params = WordstatParams(query=["купить диван", "кресло"], lr=213, freq=[FreqType.broad, FreqType.exact])
results = client.search_sync(params)
# async: results = await client.search(params)

for r in results:
    print(r.query, r.freq_type.label, r.total_value, r.provider)
    for entry in r.popular[:5]:
        print("  ", entry.text, entry.value)
```

`WordstatResult`: `query`, `freq_type`, `total_value`, `popular` и `associations`
(списки `WordstatEntry(text, value)`), `provider`.

Ошибки — исключения `rb_wordstat.AuthRequired` и `rb_wordstat.ProviderError` (у обоих
`.message` и `.action`). Логи — стандартный `logging`, логгер `rb_wordstat`:
`logging.getLogger("rb_wordstat").setLevel(logging.ERROR)` чтобы заглушить.

## Новый провайдер

1. `src/rb_wordstat/providers/<name>.py` — подкласс `WordstatProvider` с `name`,
   `summary`, `url` и тремя методами: `_params` (GET-параметры), `_api_error` (ошибка в
   теле → `ApiError` с видом `auth` / `retry` / `fatal` / `empty`) и `_parse` (частота,
   похожие, ассоциации как `{"text", "value"}`). HTTP, повторы и перевод ошибок в
   `AuthRequired` / `ProviderError` — в базовом классе.
2. Добавить класс в `PROVIDERS` в `src/rb_wordstat/providers/__init__.py`.

После этого он доступен в `--provider`, `wordstat auth login --provider <name>` и `doctor`.

## Разработка

```bash
uv sync
uv run wordstat --help
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
scripts/install_hooks.sh      # pre-commit: предупреждает об устаревших docstring команд
uv tool install --editable .  # глобальная команда из рабочей копии
```

Релиз: `uv run scripts/release.py patch|minor|major` — поднимает версию, датирует
`CHANGELOG.md`, коммитит, ставит тег и пушит. Версию руками не править.
