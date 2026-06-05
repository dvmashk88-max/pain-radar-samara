"""
Источник: Яндекс поиск (публичные сниппеты через XML API / HTML-парсинг).
Собирает заголовки и сниппеты из поисковой выдачи по запросу "{город} {ниша} {боль}".
Если Яндекс блокирует — логирует и возвращает пустой список.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

SOURCE_NAME = "Яндекс"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_SNIPPET_RE = re.compile(
    r'<div[^>]+class="[^"]*(?:OrganicText|Extended|text-container)[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r'<h2[^>]*>\s*<a[^>]+>(.*?)</a>\s*</h2>',
    re.DOTALL | re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    return _TAG_RE.sub("", html).strip()


async def _fetch_query(
    session: aiohttp.ClientSession,
    query: str,
    niche: str,
    city: str,
    pain: str,
) -> list[dict]:
    encoded = urllib.parse.quote_plus(query)
    url = f"https://yandex.ru/search/?text={encoded}&lr=51"  # lr=51 Самара

    try:
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            if resp.status == 403:
                logger.warning("[Яндекс] 403 Forbidden для запроса: %s", query)
                return []
            if resp.status != 200:
                logger.warning("[Яндекс] HTTP %d для запроса: %s", resp.status, query)
                return []

            html = await resp.text(errors="replace")

            if "captcha" in html.lower() or "showcaptcha" in html.lower():
                logger.warning("[Яндекс] CAPTCHA на запросе: %s", query)
                return []

            results = []
            titles = [_strip_tags(t) for t in _TITLE_RE.findall(html)]
            snippets = [_strip_tags(s) for s in _SNIPPET_RE.findall(html)]

            for i, snippet in enumerate(snippets[:5]):
                if len(snippet) < 30:
                    continue
                title = titles[i] if i < len(titles) else ""
                text = f"{title}. {snippet}".strip(". ")
                if text:
                    results.append({
                        "source": SOURCE_NAME,
                        "niche": niche,
                        "city": city,
                        "text": text[:400],
                        "url": url,
                        "pain_hint": pain,
                    })

            logger.info("[Яндекс] Запрос «%s»: найдено %d сниппетов", query, len(results))
            return results

    except asyncio.TimeoutError:
        logger.warning("[Яндекс] Таймаут для запроса: %s", query)
    except Exception as exc:
        logger.warning("[Яндекс] Ошибка для запроса «%s»: %s", query, exc)
    return []


async def fetch(
    cities: list[str],
    niches: list[str],
    pain_keywords: list[str],
    max_results: int = 30,
) -> list[dict]:
    """Собирает сниппеты из Яндекс.Поиска по комбинациям город+ниша+боль."""
    results: list[dict] = []

    async with aiohttp.ClientSession() as session:
        for city in cities:
            if len(results) >= max_results:
                break
            for niche in niches:
                if len(results) >= max_results:
                    break
                # Берём только первые 3 болевых слова чтобы не перегружать
                for pain in pain_keywords[:3]:
                    if len(results) >= max_results:
                        break
                    query = f"{city} {niche} отзывы {pain}"
                    items = await _fetch_query(session, query, niche, city, pain)
                    results.extend(items)
                    # Небольшая задержка между запросами
                    await asyncio.sleep(1.5)

    logger.info("[Яндекс] Итого собрано: %d", len(results))
    return results[:max_results]
