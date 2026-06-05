"""
SQLite-хранилище сигналов Pain Radar.
База создаётся автоматически в data/pain_radar.db.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DB_DIR, "pain_radar.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS signals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT    NOT NULL,
    source     TEXT    NOT NULL DEFAULT '',
    city       TEXT    NOT NULL DEFAULT '',
    niche      TEXT    NOT NULL DEFAULT '',
    pains      TEXT    NOT NULL DEFAULT '',
    text       TEXT    NOT NULL DEFAULT '',
    url        TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals(created_at);
CREATE INDEX IF NOT EXISTS idx_signals_niche      ON signals(niche);
"""

# Текст обрезается до 300 символов для дедупликации
_TEXT_KEY_LEN = 300


def _conn() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    """Создаёт таблицу и индексы если их нет."""
    with _conn() as con:
        con.executescript(_CREATE_TABLE)
    logger.info("[DB] Инициализирована: %s", DB_PATH)


def save_signals(signals: list[dict]) -> tuple[int, int]:
    """
    Сохраняет сигналы в БД с дедупликацией по (source, url, text[:300]).
    Возвращает (saved, skipped).
    """
    if not signals:
        return 0, 0

    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    skipped = 0

    with _conn() as con:
        # Загружаем существующие ключи одним запросом
        existing: set[tuple[str, str, str]] = {
            (row["source"], row["url"], row["text"][:_TEXT_KEY_LEN])
            for row in con.execute("SELECT source, url, text FROM signals")
        }

        rows = []
        for s in signals:
            text = s.get("text", "")
            source = s.get("source", "")
            url = s.get("url", "")
            key = (source, url, text[:_TEXT_KEY_LEN])
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            pains_str = ", ".join(s.get("pains", []))
            rows.append((
                now,
                source,
                s.get("city", ""),
                s.get("niche", ""),
                pains_str,
                text,
                url,
            ))
            saved += 1

        if rows:
            con.executemany(
                "INSERT INTO signals (created_at, source, city, niche, pains, text, url) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    logger.info("[DB] Сохранено: %d, дублей: %d", saved, skipped)
    return saved, skipped


def get_signals_since(days: int) -> list[dict]:
    """Возвращает сигналы за последние N дней."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM signals WHERE created_at >= ? ORDER BY created_at DESC",
            (since,),
        ).fetchall()
    result = [dict(r) for r in rows]
    # Разворачиваем pains обратно в список
    for r in result:
        r["pains"] = [p.strip() for p in r["pains"].split(",") if p.strip()]
    logger.info("[DB] Запрос за %d дней: %d сигналов", days, len(result))
    return result


def get_stats() -> dict:
    """
    Возвращает агрегированную статистику:
    today, week, month, top_pains_week, top_niches_week, top_cities_month.
    """
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    with _conn() as con:
        today_count = con.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ?", (today,)
        ).fetchone()[0]

        week_count = con.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ?", (week_ago,)
        ).fetchone()[0]

        month_count = con.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ?", (month_ago,)
        ).fetchone()[0]

        week_rows = con.execute(
            "SELECT pains, niche FROM signals WHERE created_at >= ?", (week_ago,)
        ).fetchall()

        month_rows = con.execute(
            "SELECT city FROM signals WHERE created_at >= ?", (month_ago,)
        ).fetchall()

    # Подсчёт болей и ниш за неделю
    pain_counts: dict[str, int] = {}
    niche_counts: dict[str, int] = {}
    for row in week_rows:
        for p in [x.strip() for x in row["pains"].split(",") if x.strip()]:
            pain_counts[p] = pain_counts.get(p, 0) + 1
        n = row["niche"]
        if n:
            niche_counts[n] = niche_counts.get(n, 0) + 1

    # Подсчёт городов за месяц
    city_counts: dict[str, int] = {}
    for row in month_rows:
        c = row["city"]
        if c:
            city_counts[c] = city_counts.get(c, 0) + 1

    return {
        "today": today_count,
        "week": week_count,
        "month": month_count,
        "top_pains_week": sorted(pain_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        "top_niches_week": sorted(niche_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        "top_cities_month": sorted(city_counts.items(), key=lambda x: x[1], reverse=True)[:5],
    }
