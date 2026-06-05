"""
Источник: vc.ru — статьи и обсуждения о бизнесе.
vc.ru использует JavaScript-рендеринг, поэтому публичный поиск без JS недоступен.
Попытка fetch возвращает пустой список; источник зарезервирован для будущей реализации.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SOURCE_NAME = "VC.ru"


async def fetch(
    cities: list[str],
    niches: list[str],
    pain_keywords: list[str],
    max_results: int = 20,
) -> list[dict]:
    """vc.ru требует JS-рендеринг — источник временно недоступен без браузера."""
    logger.info("[VC.ru] source unavailable: требует JS-рендеринг. Пропускаем.")
    return []
