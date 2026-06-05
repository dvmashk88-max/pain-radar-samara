"""
Источник: Отзовик (otzovik.com) — публичные страницы отзывов.
Поиск по запросам через публичный поиск сайта и Google/Яндекс-сниппеты.
Если источник недоступен — логирует и возвращает пустой список.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

SOURCE_NAME = "Отзовик"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://otzovik.com/",
}

_TAG_RE = re.compile(r"<[^>]+>")
_REVIEW_TEXT_RE = re.compile(
    r'class="review-body[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
_ITEM_TITLE_RE = re.compile(
    r'<span[^>]+class="[^"]*product-name[^"]*"[^>]*>(.*?)</span>',
    re.DOTALL | re.IGNORECASE,
)
_SEARCH_DESC_RE = re.compile(
    r'<div[^>]+class="[^"]*review_text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)


def _strip(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


# Маппинг ниш → поисковые теги Отзовика
NICHE_TO_OTZOVIK = {
    "автосервис": "авто сервис ремонт автомобиля",
    "стоматология": "стоматология зубы клиника",
    "клиника": "клиника врач поликлиника",
    "ремонт квартир": "ремонт квартиры бригада",
    "салоны красоты": "салон красоты парикмахерская",
    "доставка еды": "доставка еды курьер",
    "банки": "банк кредит",
    "жкх": "управляющая компания жкх",
    "юристы": "юрист адвокат",
    "грузоперевозки": "грузоперевозки переезд",
}


async def _fetch_otzovik_search(
    session: aiohttp.ClientSession,
    city: str,
    niche: str,
) -> list[dict]:
    niche_tag = NICHE_TO_OTZOVIK.get(niche.lower(), niche)
    query = urllib.parse.quote_plus(f"{city} {niche_tag}")
    url = f"https://otzovik.com/search/?search_text={query}"

    try:
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            if resp.status in (403, 429):
                logger.warning("[Отзовик] HTTP %d — источник временно заблокирован", resp.status)
                return []
            if resp.status != 200:
                logger.warning("[Отзовик] HTTP %d для %s / %s", resp.status, city, niche)
                return []

            html = await resp.text(errors="replace")

            if "captcha" in html.lower():
                logger.warning("[Отзовик] CAPTCHA для %s / %s", city, niche)
                return []

            results = []
            # Пробуем вытащить тексты отзывов
            for match in _SEARCH_DESC_RE.finditer(html):
                text = _strip(match.group(1))
                if len(text) > 40:
                    results.append({
                        "source": SOURCE_NAME,
                        "niche": niche,
                        "city": city,
                        "text": text[:400],
                        "url": url,
                        "pain_hint": "",
                    })
                if len(results) >= 5:
                    break

            # Fallback: вытащить заголовки продуктов
            if not results:
                for match in _ITEM_TITLE_RE.finditer(html):
                    text = _strip(match.group(1))
                    if len(text) > 10:
                        results.append({
                            "source": SOURCE_NAME,
                            "niche": niche,
                            "city": city,
                            "text": text[:400],
                            "url": url,
                            "pain_hint": "",
                        })
                    if len(results) >= 3:
                        break

            logger.info("[Отзовик] %s / %s: найдено %d", city, niche, len(results))
            return results

    except asyncio.TimeoutError:
        logger.warning("[Отзовик] Таймаут для %s / %s", city, niche)
    except aiohttp.ClientConnectorError as exc:
        logger.warning("[Отзовик] Недоступен: %s", exc)
    except Exception as exc:
        logger.warning("[Отзовик] Ошибка %s / %s: %s", city, niche, exc)
    return []


async def fetch(
    cities: list[str],
    niches: list[str],
    pain_keywords: list[str],
    max_results: int = 20,
) -> list[dict]:
    """Собирает отзывы с Отзовика по городам и нишам."""
    results: list[dict] = []

    async with aiohttp.ClientSession() as session:
        for city in cities:
            if len(results) >= max_results:
                break
            for niche in niches:
                if len(results) >= max_results:
                    break
                items = await _fetch_otzovik_search(session, city, niche)
                results.extend(items)
                await asyncio.sleep(1.0)

    logger.info("[Отзовик] Итого собрано: %d", len(results))
    return results[:max_results]
