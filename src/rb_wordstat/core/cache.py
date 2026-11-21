"""Журнал всех ответов провайдеров — он же кэш.

Каждый полученный ответ пишется сюда всегда (вся история, сжатый сырой JSON),
новой строкой: старые ответы не перезаписываются. Ключ — провайдер, тип
частоты, регион и запрос (`norm_phrase`): форматы ответов у провайдеров
разные, так что ответ одного не подменяет другой. Читать из кэша вызывающий
решает сам (`wordstat search --cache`): берётся самая свежая запись по ключу.

Хранится в базе инструмента (`core/db.py`, таблица `wordstat_responses`): общая
PostgreSQL при `WORDSTAT_DATABASE_URL`, иначе локальный SQLite. Свой кэш, а не
готовый, как в serp: hishel ключует по URL, а в нём логин и ключ провайдера;
diskcache — это key→value без истории и выборки по дате.
"""

from __future__ import annotations

import json
import logging
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from pydantic import BaseModel

from . import db
from .normalize import norm_phrase
from .tables import responses

log = logging.getLogger(__name__)


def default_path() -> Path:
    """Локальный файл базы: `WORDSTAT_DB_PATH` или папка данных приложения (~/Library/Application Support/wordstat).

    Не папка кэша: это журнал всей истории, а Caches чистят ОС и программы-уборщики.
    """
    return db.sqlite_path()


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


def files_size(path: Path) -> int:
    """Размер базы вместе с журналом WAL (-wal, -shm); 0, если базы ещё нет."""
    return sum(p.stat().st_size for p in path.parent.glob(path.name + "*")) if path.parent.is_dir() else 0


def help_line() -> str:
    """Строка для --help: где журнал и сколько весит — без открытия базы."""
    if db.database_url():
        return f"Журнал ответов: PostgreSQL из {db.ENV_VAR}."
    path = default_path()
    size = files_size(path)
    return f"Журнал ответов: {path} — {human_size(size) if size else 'пока пуст'}."


def scope(device: str | None, limit: int | None) -> str:
    """Условия ответа одной строкой: `<устройства>|<глубина>`; `''` — умолчания провайдера."""
    if not device and limit is None:
        return ""
    return f"{device or ''}|{limit or ''}"


def query_key(query: str) -> str:
    """Регистр, ё и лишние пробелы на частоту не влияют — и на ключ тоже."""
    return norm_phrase(query)


def _utc(value: datetime) -> datetime:
    """SQLite отдаёт даты без пояса; пишем всегда UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class CachedResponse(BaseModel):
    data: dict
    provider: str
    fetched_at: datetime


class CacheEntry(BaseModel):
    id: int
    fetched_at: datetime
    provider: str
    freq_type: str
    region: int
    query: str
    total_value: int
    size: int


class CacheStats(BaseModel):
    path: str
    file_size: int
    entries: int
    oldest: datetime | None
    newest: datetime | None
    by_provider: dict[str, int]


class ResponseCache:
    """Журнал в базе инструмента. `engine` — для тестов и библиотеки; по умолчанию `db.open_db()` при первом обращении."""

    def __init__(self, engine: sa.Engine | None = None) -> None:
        self._engine = engine

    @property
    def engine(self) -> sa.Engine:
        """Открыть базу (SQLite — с миграцией, PostgreSQL — с проверкой ревизии); ошибки — DATABASE_*."""
        if self._engine is None:
            self._engine = db.open_db()
        return self._engine

    @property
    def location(self) -> str:
        """Где журнал: путь к файлу SQLite или адрес PostgreSQL без пароля."""
        engine = self.engine
        return engine.url.database or "" if engine.dialect.name == "sqlite" else db.describe(engine)

    def put(
        self,
        *,
        provider: str,
        freq_type: str,
        region: int | str,
        query: str,
        total_value: int,
        data: dict,
        scope: str = "",
    ) -> datetime:
        fetched_at = datetime.now(UTC)
        blob = zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        with self.engine.begin() as conn:
            conn.execute(
                sa.insert(responses).values(
                    fetched_at=fetched_at, provider=provider, freq_type=freq_type, region=int(region), phrase=query,
                    phrase_key=query_key(query), total_value=total_value, data=blob, scope=scope,
                )
            )  # fmt: skip
        return fetched_at

    def latest(
        self,
        *,
        provider: str,
        freq_type: str,
        region: int | str,
        query: str,
        max_age: timedelta | None = None,
        scope: str = "",
    ) -> CachedResponse | None:
        """Самая свежая запись этого провайдера по ключу, или None.

        Нечитаемая запись (не сжатый zlib JSON) — тоже None и одно предупреждение: живой
        ответ ляжет новой строкой, и в следующий раз прочитается он.
        """
        t = responses.c
        sql = sa.select(t.id, t.data, t.provider, t.fetched_at).where(
            t.provider == provider,
            t.freq_type == freq_type,
            t.region == int(region),
            t.phrase_key == query_key(query),
            t.scope == scope,
        )
        if max_age is not None:
            sql = sql.where(t.fetched_at >= _cutoff(max_age))
        with self.engine.connect() as conn:
            row = conn.execute(sql.order_by(t.fetched_at.desc()).limit(1)).first()
        if row is None:
            return None
        try:
            data = json.loads(zlib.decompress(row.data).decode("utf-8"))
        except (zlib.error, ValueError) as exc:  # ValueError — и JSON, и UTF-8
            log.warning("Журнал: запись %s (провайдер %s) не читается — считаю промахом: %s", row.id, row.provider, exc)
            return None
        return CachedResponse(data=data, provider=row.provider, fetched_at=_utc(row.fetched_at))

    def stats(self) -> CacheStats:
        t = responses.c
        engine = self.engine
        with engine.connect() as conn:
            count, oldest, newest = conn.execute(
                sa.select(sa.func.count(), sa.func.min(t.fetched_at), sa.func.max(t.fetched_at))
            ).one()
            by_provider = dict(conn.execute(sa.select(t.provider, sa.func.count()).group_by(t.provider)).all())
            if engine.dialect.name == "sqlite":
                size = files_size(Path(engine.url.database or ""))
            else:
                size = conn.execute(sa.select(sa.func.pg_total_relation_size(responses.name))).scalar_one()
        return CacheStats(
            path=self.location,
            file_size=size,
            entries=count,
            oldest=_utc(oldest) if oldest else None,
            newest=_utc(newest) if newest else None,
            by_provider=by_provider,
        )

    def entries(self, *, query: str | None = None, limit: int = 50) -> list[CacheEntry]:
        """Последние записи журнала (без ответов), свежие первыми; `query` — подстрока запроса."""
        t = responses.c
        sql = sa.select(
            t.id, t.fetched_at, t.provider, t.freq_type, t.region, t.phrase, t.total_value, sa.func.length(t.data)
        )
        if query:
            sql = sql.where(t.phrase_key.contains(query_key(query), autoescape=True))
        with self.engine.connect() as conn:
            rows = conn.execute(sql.order_by(t.fetched_at.desc()).limit(limit)).all()
        return [
            CacheEntry(
                id=r[0], fetched_at=_utc(r[1]), provider=r[2], freq_type=r[3], region=r[4], query=r[5],
                total_value=r[6], size=r[7],
            )
            for r in rows
        ]  # fmt: skip

    def count_older(self, older_than: timedelta | None) -> int:
        """Сколько записей удалит `clear` с тем же аргументом (None — все)."""
        sql = sa.select(sa.func.count()).select_from(responses)
        if older_than is not None:
            sql = sql.where(responses.c.fetched_at < _cutoff(older_than))
        with self.engine.connect() as conn:
            return conn.execute(sql).scalar_one()

    def clear(self, older_than: timedelta | None) -> int:
        """Удалить записи старше `older_than` (None — все); локальный файл ещё и сжать."""
        sql = sa.delete(responses)
        if older_than is not None:
            sql = sql.where(responses.c.fetched_at < _cutoff(older_than))
        with self.engine.begin() as conn:
            deleted = conn.execute(sql).rowcount
        if self.engine.dialect.name == "sqlite":
            with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.exec_driver_sql("VACUUM")  # иначе файл не уменьшится
        return deleted


def _cutoff(age: timedelta) -> datetime:
    return datetime.now(UTC) - age
