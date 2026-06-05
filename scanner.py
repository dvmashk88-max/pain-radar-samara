"""
Сканер публичных источников по Самарской области.
Ручной запуск через /scan — без автоматического расписания.

Активные источники:   Telegram t.me/s, DuckDuckGo HTML, vc.ru, Habr Q&A
Отключённые:          Яндекс, Авито, Отзовик (блокируют с Railway IP)
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

# Отключённые источники — заблокированы на Railway
DISABLED_SOURCES = ["Яндекс", "Авито", "Отзовик"]


def _dedup(signals: list[dict]) -> tuple[list[dict], int]:
    seen: set[str] = set()
    unique: list[dict] = []
    for s in signals:
        key = s["text"][:100].lower().strip()
        dedup_key = f"{key}||{s.get('url', '')}"
        if dedup_key not in seen:
            seen.add(dedup_key)
            unique.append(s)
    removed = len(signals) - len(unique)
    return unique, removed


async def scan_sources() -> dict:
    """
    Запускает активные источники параллельно, дедуплицирует и возвращает
    словарь с сигналами и статистикой.
    """
    from sources.telegram_public_source import fetch as tg_fetch
    from sources.duckduckgo_source import fetch as ddg_fetch
    from sources.vc_source import fetch as vc_fetch
    from sources.habr_qna_source import fetch as habr_fetch

    logger.info("[Scanner] Старт. Активные источники: Telegram, DuckDuckGo, VC.ru, Habr Q&A")

    tg_task = asyncio.create_task(
        tg_fetch(CITIES, NICHES, PAIN_KEYWORDS, max_results=40)
    )
    ddg_task = asyncio.create_task(
        ddg_fetch(CITIES, NICHES, PAIN_KEYWORDS, max_results=30)
    )
    vc_task = asyncio.create_task(
        vc_fetch(CITIES, NICHES, PAIN_KEYWORDS, max_results=20)
    )
    habr_task = asyncio.create_task(
        habr_fetch(CITIES, NICHES, PAIN_KEYWORDS, max_results=20)
    )

    tg_raw, ddg_raw, vc_raw, habr_raw = await asyncio.gather(
        tg_task, ddg_task, vc_task, habr_task, return_exceptions=True
    )

    def safe(result: object, name: str) -> list[dict]:
        if isinstance(result, Exception):
            logger.warning("[Scanner] %s упал с исключением: %s", name, result)
            return []
        return result or []  # type: ignore[return-value]

    tg_items = safe(tg_raw, "Telegram")
    ddg_items = safe(ddg_raw, "DuckDuckGo")
    vc_items = safe(vc_raw, "VC.ru")
    habr_items = safe(habr_raw, "Habr Q&A")

    logger.info(
        "[Scanner] Сырые: Telegram=%d DuckDuckGo=%d VC.ru=%d HabrQnA=%d",
        len(tg_items), len(ddg_items), len(vc_items), len(habr_items),
    )

    # Telegram-сигналы уже отфильтрованы по болям внутри источника.
    # DDG-сигналы уже содержат pains из запроса.
    # VC/Habr возвращают [] — фильтровать нечего.
    all_signals = tg_items + ddg_items + vc_items + habr_items

    unique_signals, duplicates_removed = _dedup(all_signals)
    logger.info("[Scanner] После дедупликации: %d (дублей: %d)",
                len(unique_signals), duplicates_removed)

    result_signals = unique_signals[:MAX_SIGNALS]
    logger.info("[Scanner] Итого сигналов: %d", len(result_signals))

    return {
        "signals": result_signals,
        "stats": {
            "telegram": len(tg_items),
            "duckduckgo": len(ddg_items),
            "vc": len(vc_items),
            "habr": len(habr_items),
            "total_raw": len(all_signals),
            "duplicates_removed": duplicates_removed,
            "final": len(result_signals),
        },
    }


def build_scan_report(scan_result: dict) -> str:
    """Формирует компактный текстовый отчёт для Telegram."""
    signals = scan_result["signals"]
    stats = scan_result["stats"]

    if not signals:
        return (
            "⚠️ Реальные источники пока не дали данных.\n"
            "Попробуйте позже или расширьте список источников."
        )

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
        f"• Telegram: {stats['telegram']}",
        f"• DuckDuckGo: {stats['duckduckgo']}",
        f"• VC\\.ru: {stats['vc']}",
        f"• Habr Q&A: {stats['habr']}",
        "",
        "ТОП\\-5 болей:",
    ]
    for i, (pain, cnt) in enumerate(top_pains, 1):
        lines.append(f"{i}\\. {pain} — {cnt}")

    lines += ["", "ТОП\\-5 ниш:"]
    for i, (niche, cnt) in enumerate(top_niches, 1):
        lines.append(f"{i}\\. {niche.capitalize()} — {cnt}")

    return "\n".join(lines)


# --- Обратная совместимость ---

def scan_reviews() -> list[dict]:
    return asyncio.run(scan_sources())["signals"]


def get_scan_summary(results: list[dict]) -> str:
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
    parts = [f"Сигналов: {len(results)}"]
    if top_n:
        parts.append("Ниши: " + ", ".join(f"{n}({c})" for n, c in top_n))
    if top_p:
        parts.append("Боли: " + ", ".join(f"{p}({c})" for p, c in top_p))
    return " | ".join(parts)
