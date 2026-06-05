"""
Сканер реальных публичных источников по Самарской области.
Ручной запуск через /scan — без автоматического расписания.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

CITIES = ["Самара", "Тольятти", "Новокуйбышевск", "Сызрань"]

NICHES = [
    "автосервис",
    "стоматология",
    "клиника",
    "ремонт квартир",
    "салоны красоты",
    "доставка еды",
    "банки",
    "жкх",
    "юристы",
    "грузоперевозки",
]

PAIN_KEYWORDS = [
    "не дозвониться",
    "не перезвонили",
    "дорого",
    "долго",
    "очередь",
    "хамство",
    "обман",
    "не работает",
    "плохой сервис",
    "нет записи",
    "задержали",
    "не отвечают",
    "навязали",
    "сорвали сроки",
]

MAX_SIGNALS = 50


def _has_pain(text: str) -> list[str]:
    t = text.lower()
    return [kw for kw in PAIN_KEYWORDS if kw in t]


def _dedup(signals: list[dict]) -> tuple[list[dict], int]:
    seen: set[str] = set()
    unique: list[dict] = []
    for s in signals:
        key = s["text"][:120].lower().strip()
        url_key = s.get("url", "")
        dedup_key = f"{key}||{url_key}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique.append(s)
    removed = len(signals) - len(unique)
    return unique, removed


async def scan_sources() -> dict:
    """
    Запускает все источники, собирает сигналы, фильтрует по болевым словам.
    Возвращает словарь с результатами и статистикой.
    """
    from sources.yandex_search_source import fetch as yandex_fetch
    from sources.otzovik_source import fetch as otzovik_fetch
    from sources.avito_source import fetch as avito_fetch

    logger.info("[Scanner] Старт сканирования. Города: %s", CITIES)
    logger.info("[Scanner] Ниши: %s", NICHES)

    # Запускаем источники параллельно
    yandex_task = asyncio.create_task(
        yandex_fetch(CITIES, NICHES, PAIN_KEYWORDS, max_results=30)
    )
    otzovik_task = asyncio.create_task(
        otzovik_fetch(CITIES, NICHES, PAIN_KEYWORDS, max_results=20)
    )
    avito_task = asyncio.create_task(
        avito_fetch(CITIES, NICHES, PAIN_KEYWORDS, max_results=20)
    )

    yandex_raw, otzovik_raw, avito_raw = await asyncio.gather(
        yandex_task, otzovik_task, avito_task, return_exceptions=True
    )

    # Обработка возможных исключений от gather
    def safe(result, name: str) -> list[dict]:
        if isinstance(result, Exception):
            logger.warning("[Scanner] Источник %s упал с исключением: %s", name, result)
            return []
        return result or []

    yandex_items = safe(yandex_raw, "Яндекс")
    otzovik_items = safe(otzovik_raw, "Отзовик")
    avito_items = safe(avito_raw, "Авито")

    logger.info("[Scanner] Сырые данные — Яндекс: %d, Отзовик: %d, Авито: %d",
                len(yandex_items), len(otzovik_items), len(avito_items))

    all_signals = yandex_items + otzovik_items + avito_items

    # Дедупликация
    unique_signals, duplicates_removed = _dedup(all_signals)
    logger.info("[Scanner] После дедупликации: %d (удалено дублей: %d)",
                len(unique_signals), duplicates_removed)

    # Фильтрация по болевым словам
    filtered: list[dict] = []
    for s in unique_signals:
        pains = _has_pain(s["text"])
        if pains:
            s["pains"] = pains
            filtered.append(s)

    logger.info("[Scanner] После фильтрации по болевым словам: %d", len(filtered))

    # Ограничиваем итог
    result_signals = filtered[:MAX_SIGNALS]

    return {
        "signals": result_signals,
        "stats": {
            "yandex": len(yandex_items),
            "otzovik": len(otzovik_items),
            "avito": len(avito_items),
            "total_raw": len(all_signals),
            "after_dedup": len(unique_signals),
            "duplicates_removed": duplicates_removed,
            "after_filter": len(filtered),
            "final": len(result_signals),
        },
    }


def build_scan_report(scan_result: dict) -> str:
    """Формирует текстовый отчёт для Telegram."""
    signals = scan_result["signals"]
    stats = scan_result["stats"]

    if not signals:
        return (
            "⚠️ Реальные источники пока не дали данных. "
            "Попробуйте позже или расширьте список источников."
        )

    # Подсчёт по нишам и болям
    niche_counts: dict[str, int] = {}
    pain_counts: dict[str, int] = {}
    for s in signals:
        niche_counts[s["niche"]] = niche_counts.get(s["niche"], 0) + 1
        for p in s.get("pains", []):
            pain_counts[p] = pain_counts.get(p, 0) + 1

    top_niches = sorted(niche_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_pains = sorted(pain_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    lines = [
        "🔥 *Радар болей Самарской области*\n",
        f"Города: {', '.join(CITIES)}",
        f"Найдено сигналов: *{stats['final']}*",
        "",
        "Источники:",
        f"• Яндекс: {stats['yandex']}",
        f"• Отзовик: {stats['otzovik']}",
        f"• Авито: {stats['avito']}",
        "",
        "ТОП-5 болей:",
    ]
    for i, (pain, cnt) in enumerate(top_pains, 1):
        lines.append(f"{i}. {pain} — {cnt}")

    lines += ["", "ТОП-5 ниш:"]
    for i, (niche, cnt) in enumerate(top_niches, 1):
        lines.append(f"{i}. {niche.capitalize()} — {cnt}")

    return "\n".join(lines)


# --- Обратная совместимость для синхронного кода ---

def scan_reviews() -> list[dict]:
    """Синхронная обёртка — запускает async-сканирование через asyncio.run()."""
    result = asyncio.run(scan_sources())
    return result["signals"]


def get_scan_summary(results: list[dict]) -> str:
    """Оставлена для совместимости; возвращает краткую сводку."""
    if not results:
        return "Сигналов не найдено."
    niche_counts: dict[str, int] = {}
    pain_counts: dict[str, int] = {}
    for r in results:
        niche_counts[r["niche"]] = niche_counts.get(r["niche"], 0) + 1
        for p in r.get("pains", []):
            pain_counts[p] = pain_counts.get(p, 0) + 1
    top_n = sorted(niche_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    top_p = sorted(pain_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    lines = [f"Сигналов: {len(results)}"]
    if top_n:
        lines += ["Ниши: " + ", ".join(f"{n}({c})" for n, c in top_n)]
    if top_p:
        lines += ["Боли: " + ", ".join(f"{p}({c})" for p, c in top_p)]
    return " | ".join(lines)
