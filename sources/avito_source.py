"""
Источник: Авито Услуги — публичный поиск объявлений по городам и нишам.
Собирает заголовки и описания объявлений как сигналы спроса/проблем.
Если Авито блокирует — логирует "source unavailable" и возвращает пустой список.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

SOURCE_NAME = "Авито"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.avito.ru/",
}

_TAG_RE = re.compile(r"<[^>]+>")

# Авито использует data-атрибуты и JSON-LD для контента
_TITLE_RE = re.compile(
    r'itemprop="name"[^>]*>\s*<span[^>]*>(.*?)</span>',
    re.DOTALL | re.IGNORECASE,
)
_DESC_RE = re.compile(
    r'data-marker="item-description"[^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE,
)
_ITEM_RE = re.compile(
    r'"title"\s*:\s*"([^"]{10,200})"',
    re.IGNORECASE,
)

# Маппинг город → URL-slug Авито
CITY_SLUG = {
    "Самара": "samara",
    "Тольятти": "tolyatti",
    "Новокуйбышевск": "novokuybyshevsk",
    "Сызрань": "syzran",
}

# Маппинг ниш → поисковые запросы Авито
NICHE_QUERY = {
    "автосервис": "ремонт автомобиля",
    "стоматология": "стоматология лечение зубов",
    "клиника": "медицинские услуги врач",
    "ремонт квартир": "ремонт квартиры",
    "салоны красоты": "салон красоты маникюр",
    "доставка еды": "доставка еды курьер",
    "банки": "финансовые услуги кредит",
    "жкх": "услуги жкх сантехник",
    "юристы": "юридические услуги адвокат",
    "грузоперевозки": "грузоперевозки переезд",
}


def _strip(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


async def _fetch_avito(
    session: aiohttp.ClientSession,
    city: str,
    niche: str,
) -> list[dict]:
    city_slug = CITY_SLUG.get(city, "samara")
    query = NICHE_QUERY.get(niche.lower(), niche)
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.avito.ru/{city_slug}/uslugi?q={encoded}"

    try:
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            if resp.status in (403, 429, 451):
                logger.warning("[Авито] source unavailable: HTTP %d для %s / %s",
                               resp.status, city, niche)
                return []
            if resp.status != 200:
                logger.warning("[Авито] HTTP %d для %s / %s", resp.status, city, niche)
                return []

            html = await resp.text(errors="replace")

            if "captcha" in html.lower() or "Доступ ограничен" in html:
                logger.warning("[Авито] source unavailable: антибот для %s / %s", city, niche)
                return []

            results = []

            # Пробуем JSON-данные в странице
            for match in _ITEM_RE.finditer(html):
                text = match.group(1).replace("\\u0022", '"').strip()
                if len(text) > 20 and not text.startswith("http"):
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

            # Fallback: HTML-заголовки
            if not results:
                for match in _TITLE_RE.finditer(html):
                    text = _strip(match.group(1))
                    if len(text) > 15:
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

            logger.info("[Авито] %s / %s: найдено %d", city, niche, len(results))
            return results

    except asyncio.TimeoutError:
        logger.warning("[Авито] source unavailable: таймаут для %s / %s", city, niche)
    except aiohttp.ClientConnectorError as exc:
        logger.warning("[Авито] source unavailable: %s", exc)
    except Exception as exc:
        logger.warning("[Авито] Ошибка %s / %s: %s", city, niche, exc)
    return []


async def fetch(
    cities: list[str],
    niches: list[str],
    pain_keywords: list[str],
    max_results: int = 20,
) -> list[dict]:
    """Собирает заголовки объявлений с Авито Услуги."""
    results: list[dict] = []

    async with aiohttp.ClientSession() as session:
        for city in cities:
            if len(results) >= max_results:
                break
            for niche in niches:
                if len(results) >= max_results:
                    break
                items = await _fetch_avito(session, city, niche)
                results.extend(items)
                await asyncio.sleep(1.2)

    logger.info("[Авито] Итого собрано: %d", len(results))
    return results[:max_results]
