# rb-wordstat

Снятие частот и парсинг Яндекс.Wordstat через XML River API.
Три режима использования: **библиотека**, **CLI**, **MCP-сервер**.

---

## Установка

```bash
# Из директории проекта
uv sync --all-extras

# Запуск через uv
uv run rb-wordstat search "купить диван"

# Или через алиас (после source ~/.zshrc)
wordstat search "купить диван"
```

---

## Credentials

Файл: `~/Projects/_shared/credentials/.env.shared`

```
XMLRIVER_USER=9358
XMLRIVER_TOKEN=5c8353083fde7a2c1331726b29c3843d6caecfe3
```

Загружается автоматически из `.env` (симлинк на `.env.shared`).

---

## Операторы частоты

| Атрибут | Оператор | Пример | Описание |
|---------|----------|--------|----------|
| `broad` | без оператора | `купить диван` | Базовая (широкое соответствие) |
| `phrase` | `"..."` | `"купить диван"` | Фразовая (фиксирует слова) |
| `exact` | `"!слово !слово"` | `"!купить !диван"` | Точная словоформа, любой порядок |
| `exact-ord` | `"[!слово !слово]"` | `"[!купить !диван]"` | Точная словоформа + порядок слов |

---

## Режим 1: CLI

### Базовый запрос

```bash
wordstat search "купить диван"
```

Вывод: частота (broad) + таблица похожих запросов + таблица ассоциаций.

### Все параметры

| Параметр | Короткий | По умолчанию | Значения | Описание |
|----------|----------|--------------|----------|----------|
| `--freq` | `-f` | `broad` | `broad` / `phrase` / `exact` / `exact-ord` / `all` | Тип(ы) частоты — через запятую или несколько флагов |
| `--lr` | — | `213` | целое число | Код региона Яндекса |
| `--format` | `-F` | `table` | `table` / `json` | Формат вывода в консоль |
| `--output` | `-o` | — | путь к файлу | Сохранить результат |
| `--csv-mode` | — | `auto` | `auto` / `freq` / `keywords` | Режим CSV при сохранении |
| `--no-keywords` | — | выкл | флаг | Только частоты, без похожих/ассоциаций в консоли |

### Синтаксис `--freq`

```bash
# Один тип
wordstat search "запрос" --freq broad

# Несколько через запятую (рекомендуется)
wordstat search "запрос" --freq broad,phrase,exact

# Несколько через повторение флага
wordstat search "запрос" --freq broad --freq phrase --freq exact

# Все 4 типа
wordstat search "запрос" --freq all
```

### Примеры

```bash
# Базовая частота + похожие + ассоциации
wordstat search "купить диван"

# Все 4 вида частоты, только числа (без похожих)
wordstat search "купить диван" --freq all --no-keywords

# Выборочные виды через запятую
wordstat search "купить диван" --freq broad,phrase,exact

# Несколько запросов сразу
wordstat search "диван" "кресло" "стол" --freq broad,phrase

# С регионом (Санкт-Петербург)
wordstat search "доставка еды" --lr 2

# Подавить лог
wordstat search "купить диван" 2>/dev/null

# Сохранить полные данные в JSON
wordstat search "купить диван" --output results.json

# Сохранить таблицу частот в CSV (при --freq all)
wordstat search "купить диван" --freq all --output freq.csv

# Сохранить похожие/ассоциации в CSV
wordstat search "купить диван" --output keywords.csv --csv-mode keywords
```

### Форматы CSV

| `--csv-mode` | Колонки | Когда использовать |
|---|---|---|
| `freq` | `query, freq_type, freq_label, operator, total_value` | Сравнение частот по операторам |
| `keywords` | `source_query, type, keyword, value` | Сбор похожих/ассоциаций для SEO |
| `auto` | автовыбор | `freq` при >1 типах, `keywords` при только broad |

> `--csv-mode keywords` работает только если в `--freq` есть `broad`.

---

## Режим 2: Python-библиотека

### Быстрый старт

```python
from rb_wordstat import WordstatClient, WordstatParams, FreqType

client = WordstatClient()
results = client.search_sync(WordstatParams(query="купить диван"))

for r in results:
    print(r.total_value)
    for kw in r.popular:
        print(kw.text, kw.value)
```

### WordstatParams — все параметры

```python
WordstatParams(
    query="купить диван",     # str или list[str] — один или несколько запросов
    lr=213,                   # код региона Яндекса (213 = Москва)
    freq=[FreqType.broad],    # список типов частоты
)
```

### FreqType — операторы

```python
FreqType.broad      # базовая — без операторов
FreqType.phrase     # фразовая — "запрос"
FreqType.exact      # точная — "!слово !слово"
FreqType.exact_ord  # точная+порядок — "[!слово !слово]"
```

### WordstatResult — поля

```python
r.query          # str — оригинальный запрос (без операторов)
r.freq_type      # FreqType — тип частоты
r.total_value    # int — частота запроса
r.popular        # list[WordstatEntry] — похожие запросы
r.associations   # list[WordstatEntry] — ассоциированные запросы

# WordstatEntry:
entry.text       # str — текст запроса
entry.value      # int — частота
```

### Примеры

```python
from rb_wordstat import WordstatClient, WordstatParams, FreqType

client = WordstatClient()

# Все 4 вида частоты для одного запроса
results = client.search_sync(WordstatParams(
    query="купить угловой диван",
    freq=[FreqType.broad, FreqType.phrase, FreqType.exact, FreqType.exact_ord],
))
for r in results:
    print(f"{r.freq_type.label}: {r.total_value}")

# Несколько запросов
results = client.search_sync(WordstatParams(
    query=["диван", "кресло", "стол"],
    freq=[FreqType.broad, FreqType.phrase],
    lr=213,
))

# Собрать похожие запросы (из broad)
broad = next(r for r in results if r.freq_type == FreqType.broad)
for kw in broad.popular:
    print(kw.text, kw.value)
```

### Асинхронный режим

```python
import asyncio
from rb_wordstat import WordstatClient, WordstatParams, FreqType

async def main():
    client = WordstatClient()
    results = await client.search(WordstatParams(
        query=["купить диван", "угловой диван"],
        freq=[FreqType.broad, FreqType.exact],
    ))
    for r in results:
        print(r.query, r.freq_type.label, r.total_value)

asyncio.run(main())
```

### Отключить лог

```python
from loguru import logger
logger.disable("rb_wordstat")
```

---

## Режим 3: MCP-сервер

Регистрация в `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rb-wordstat": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/Users/bolandau/Projects/_shared/libs/rb-wordstat",
        "rb-wordstat",
        "mcp"
      ]
    }
  }
}
```

### Инструмент: `search_wordstat`

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `query` | `string` или `array` | обязательный | Запрос или список запросов |
| `lr` | `integer` | `213` | Код региона Яндекса |
| `freq` | `array` | `["broad"]` | Типы частоты: `broad`, `phrase`, `exact`, `exact_ord` |

Возвращает JSON-массив объектов `WordstatResult`.

### Как формулировать запросы в чате

```
Сними частоту Wordstat для "купить диван"
Сравни все виды частоты для "угловой диван" — broad, phrase, exact и exact_ord
Собери похожие запросы и ассоциации для "растаможка авто", регион 213
Сними частоту для "диван", "кресло", "стол" — только broad и phrase
Покажи точную частоту "[!купить !угловой !диван]" в Яндексе
```

---

## Коды регионов Яндекса

| Регион | lr |
|--------|-----|
| Москва | 213 |
| Санкт-Петербург | 2 |
| Краснодар | 35 |
| Новосибирск | 65 |
| Екатеринбург | 54 |
| Вся Россия | 225 |

Полный список: https://xmlriver.com/userfiles/files/yandex_geo.csv

---

## Тестирование MCP

```bash
npx @modelcontextprotocol/inspector uv run --project /Users/bolandau/Projects/_shared/libs/rb-wordstat rb-wordstat mcp
```
