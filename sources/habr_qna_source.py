"""
Источник: Habr Q&A (qna.habr.com) — вопросы и ответы.
Habr использует JavaScript-рендеринг, поэтому поиск без JS недоступен.
Попытка fetch возвращает пустой список; источник зарезервирован для будущей реализации.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SOURCE_NAME = "Habr Q&A"


async def fetch(
    cities: list[str],
    niches: list[str],
    pain_keywords: list[str],
    max_results: int = 20,
) -> list[dict]:
    """qna.habr.com требует JS-рендеринг — источник временно недоступен без браузера."""
    logger.info("[HabrQnA] source unavailable: требует JS-рендеринг. Пропускаем.")
    return []
