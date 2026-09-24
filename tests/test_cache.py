from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from rb_wordstat import WordstatClient, WordstatParams
from rb_wordstat.core import services
from rb_wordstat.core.cache import ResponseCache, default_path, help_line, human_size, query_key
from rb_wordstat.core.errors import InvalidArguments
from rb_wordstat.core.models import FreqType

from .test_cli import invoke, invoke_json
from .test_search import FakeProvider


def put(journal: ResponseCache, query: str = "Купить  Диван", provider: str = "a", total: int = 100) -> None:
    journal.put(provider=provider, freq_type="broad", region="213", query=query, total_value=total,
                data={"total": total, "query": query})  # fmt: skip


def test_journal_put_latest_stats_entries_clear(isolated_cache: Path) -> None:
    journal = ResponseCache()
    assert journal.path == isolated_cache == default_path()
    assert "пока пуст" in help_line()
    assert journal.latest(provider="a", freq_type="broad", region="213", query="купить диван") is None

    put(journal, total=100)
    put(journal, total=200)
    put(journal, query="кресло", provider="b")

    hit = journal.latest(provider="a", freq_type="broad", region="213", query=" купить диван ")
    assert hit is not None and hit.data["total"] == 200  # самая свежая; регистр и пробелы не важны
    assert journal.latest(provider="a", freq_type="phrase", region="213", query="купить диван") is None
    assert journal.latest(provider="a", freq_type="broad", region="2", query="купить диван") is None
    assert (
        journal.latest(provider="a", freq_type="broad", region="213", query="купить диван", max_age=timedelta(0))
        is None
    )

    stats = journal.stats()
    assert (stats.entries, stats.by_provider) == (3, {"a": 2, "b": 1})
    assert stats.oldest is not None and stats.newest is not None
    assert "КБ" in help_line() or "Б" in help_line()

    rows = journal.entries(query="диван", limit=10)
    assert [r.total_value for r in rows] == [200, 100]
    assert rows[0].freq_type == "broad" and rows[0].size > 0
    assert len(journal.entries()) == 3

    assert journal.count_older(timedelta(days=1)) == 0
    assert journal.clear(timedelta(days=1)) == 0
    assert journal.count_older(None) == 3
    assert journal.clear(None) == 3
    assert journal.stats().entries == 0


def test_helpers() -> None:
    assert query_key("  Купить   ДИВАН ") == "купить диван"
    assert human_size(512) == "512 Б"
    assert human_size(2048) == "2 КБ"
    assert human_size(3 * 1024**3) == "3.0 ГБ"
    assert services.parse_age("30m") == timedelta(minutes=30)
    assert services.parse_age("2W") == timedelta(weeks=2)
    with pytest.raises(InvalidArguments):
        services.parse_age("7 дней")


def test_client_writes_every_answer_and_reads_only_with_use_cache() -> None:
    journal = ResponseCache()
    primary = FakeProvider("a")
    client = WordstatClient(providers=[primary], cache=journal)
    params = WordstatParams(query="диван", freq=[FreqType.broad, FreqType.phrase])

    live = client.search_sync(params)
    assert [r.from_cache for r in live] == [False, False]
    assert live[0].fetched_at is not None
    assert journal.stats().entries == 2

    again = client.search_sync(params)  # без use_cache — снова живой запрос
    assert len(primary.calls) == 4
    assert journal.stats().entries == 4

    cached = client.search_sync(params, use_cache=True)
    assert len(primary.calls) == 4  # ни одного платного запроса
    assert [(r.from_cache, r.provider, r.total_value) for r in cached] == [(True, "a", 100), (True, "a", 100)]
    assert cached[0].popular[0].text == "диван купить"
    assert again[0].fetched_at is not None and cached[0].fetched_at == again[0].fetched_at

    stale = client.search_sync(params, use_cache=True, max_age=timedelta(0))
    assert [r.from_cache for r in stale] == [False, False]


def test_cache_only_from_providers_in_queue_in_order() -> None:
    journal = ResponseCache()
    put(journal, query="диван", provider="b", total=7)
    only_a = WordstatClient(providers=[FakeProvider("a")], cache=journal)
    assert only_a.search_sync(WordstatParams(query="диван"), use_cache=True)[0].from_cache is False

    journal.clear(None)  # живой ответ `a` из первой части теста — убрать, оставить только запись `b`
    put(journal, query="диван", provider="b", total=7)
    a, b = FakeProvider("a"), FakeProvider("b")
    result = WordstatClient(providers=[a, b], cache=journal).search_sync(WordstatParams(query="диван"), use_cache=True)
    assert (result[0].provider, result[0].total_value, result[0].from_cache) == ("b", 7, True)
    assert a.calls == b.calls == []


def test_client_without_journal_and_broken_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    no_journal = WordstatClient(providers=[FakeProvider("a")], cache=False)
    assert no_journal.cache is None
    assert no_journal.search_sync(WordstatParams(query="x"), use_cache=True)[0].from_cache is False

    def broken_put(**kwargs):
        raise sqlite3.OperationalError("disk full")

    journal = ResponseCache()
    monkeypatch.setattr(journal, "put", broken_put)
    result = WordstatClient(providers=[FakeProvider("a")], cache=journal).search_sync(WordstatParams(query="x"))
    assert result[0].total_value == 100  # оплаченный ответ не теряется из-за диска


# --- команды -------------------------------------------------------------------


def test_search_cache_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(services, "search", lambda queries, **kw: calls.append(kw) or [])
    invoke_json("search", "x", "--cache", "--max-age", "7d")
    invoke_json("search", "x", "--cache", "--force")
    assert (calls[0]["use_cache"], calls[0]["max_age"]) == (True, timedelta(days=7))
    assert calls[1]["use_cache"] is False


def test_cache_commands() -> None:
    code, info = invoke_json("cache", "info")
    assert code == 0 and info["entries"] == 0
    assert "Журнал пуст" in invoke("cache", "list").stdout

    journal = ResponseCache()
    put(journal, query="диван")
    put(journal, query="кресло")

    human = invoke("cache", "info").stdout
    assert "записей: 2" in human and "a: 2" in human
    code, listed = invoke_json("cache", "list", "-q", "диван")
    assert (code, listed["count"], listed["results"][0]["query"]) == (0, 1, "диван")
    assert "кресло" in invoke("cache", "list").stdout

    code, err = invoke_json("cache", "clear")
    assert code == 2 and err["error"]["code"] == "INVALID_ARGUMENTS"
    code, preview = invoke_json("--dry-run", "cache", "clear", "--all")
    assert preview == {"ok": True, "dry_run": True, "would_delete": 2}
    code, _ = invoke_json("--non-interactive", "cache", "clear", "--all")
    assert code == 2 and journal.stats().entries == 2

    code, done = invoke_json("--non-interactive", "cache", "clear", "--older-than", "1d", "--confirm")
    assert done["deleted"] == 0
    assert "Удалено записей: 2" in invoke("cache", "clear", "--all", "--confirm").stdout
    assert "Будет удалено: 0" in invoke("--dry-run", "cache", "clear", "--all").stdout


def test_doctor_reports_cache(isolated_cache: Path) -> None:
    _, payload = invoke_json("doctor")
    check = next(c for c in payload["checks"] if c["name"] == "cache")
    assert check["ok"] and str(isolated_cache) in check["detail"]
