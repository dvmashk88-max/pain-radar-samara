"""
Источник: DuckDuckGo HTML поиск (https://html.duckduckgo.com/html/).
Использует заранее составленные запросы {город} {ниша} {боль}.
Возвращает заголовки результатов; боль аннотируется из запроса.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

SOURCE_NAME = "DuckDuckGo"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Конкретные запросы: (query_text, niche, city, pain_keyword)
# Максимум 25 запросов на один /scan
QUERIES: list[tuple[str, str, str, str]] = [
    ("Самара не дозвониться автосервис отзывы", "автосервис", "Самара", "не дозвониться"),
    ("Тольятти не дозвониться автосервис отзывы", "автосервис", "Тольятти", "не дозвониться"),
    ("Самара долго клиника жалоба", "клиника", "Самара", "долго"),
    ("Тольятти нет записи клиника", "клиника", "Тольятти", "нет записи"),
    ("Самара дорого стоматология", "стоматология", "Самара", "дорого"),
    ("Тольятти дорого стоматология", "стоматология", "Тольятти", "дорого"),
    ("Самара плохой сервис доставка жалоба", "доставка еды", "Самара", "плохой сервис"),
    ("Тольятти сорвали сроки ремонт квартиры", "ремонт квартир", "Тольятти", "сорвали сроки"),
    ("Самара хамство банк жалоба", "банки", "Самара", "хамство"),
    ("Самара не отвечают ЖКХ жалоба", "жкх", "Самара", "не отвечают"),
    ("Тольятти обман ремонт квартиры", "ремонт квартир", "Тольятти", "обман"),
    ("Самара очередь поликлиника жалоба", "клиника", "Самара", "очередь"),
    ("Тольятти не перезвонили салон красоты", "салоны красоты", "Тольятти", "не перезвонили"),
    ("Тольятти хамство банк отзывы", "банки", "Тольятти", "хамство"),
    ("Самара навязали услуги жалоба", "банки", "Самара", "навязали"),
    ("Тольятти долго ждать автосервис", "автосервис", "Тольятти", "долго"),
    ("Самара не работает ЖКХ жалоба", "жкх", "Самара", "не работает"),
    ("Новокуйбышевск жалоба сервис", "клиника", "Новокуйбышевск", "плохой сервис"),
    ("Сызрань жалоба не дозвониться", "клиника", "Сызрань", "не дозвониться"),
    ("Самара юрист обман жалоба", "юристы", "Самара", "обман"),
    ("Тольятти грузоперевозки сорвали сроки", "грузоперевозки", "Тольятти", "сорвали сроки"),
    ("Самара стоматология хамство очередь", "стоматология", "Самара", "хамство"),
    ("Тольятти доставка не привезли жалоба", "доставка еды", "Тольятти", "долго"),
    ("Самара ремонт квартиры обман", "ремонт квартир", "Самара", "обман"),
]

_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r'class="result__a"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
_HTML_ENT = [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&nbsp;", " ")]
STOP_TOPICS = [
    "дтп",
    "авария",
    "пожар",
    "погиб",
    "задержали",
    "задержан",
    "полиция",
    "сво",
    "дрон",
    "бпла",
    "происшеств",
    "криминал",
    "суд",
    "арест",
    "колони",
    "нож",
]


def _clean(html: str) -> str:
    text = _TAG_RE.sub("", html)
    for ent, ch in _HTML_ENT:
        text = text.replace(ent, ch)
    return " ".join(text.split()).strip()


def _is_irrelevant(text: str) -> bool:
    text_lower = text.lower()
    return any(stop_word in text_lower for stop_word in STOP_TOPICS)


async def _fetch_query(
    session: aiohttp.ClientSession,
    query: str,
    niche: str,
    city: str,
    pain: str,
) -> list[dict]:
    params = urllib.parse.urlencode({"q": query})
    url = f"https://html.duckduckgo.com/html/?{params}"

    try:
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 403:
                logger.warning("[DDG] 403 на запросе: %s", query[:50])
                return []
            if resp.status != 200:
                logger.warning("[DDG] HTTP %d на запросе: %s", resp.status, query[:50])
                return []

            html = await resp.text(errors="replace")

            if "captcha" in html.lower():
                logger.warning("[DDG] CAPTCHA на запросе: %s", query[:50])
                return []

            titles = _TITLE_RE.findall(html)
            results = []

            for raw_title in titles:
                title = _clean(raw_title)
                if len(title) < 15:
                    continue
                if _is_irrelevant(title):
                    continue
                # Формируем текст сигнала: заголовок + контекст из запроса
                text = f"{title}. Запрос: {query}"
                results.append({
                    "source": SOURCE_NAME,
                    "niche": niche,
                    "city": city,
                    "text": text[:400],
                    "url": url,
                    "pains": [pain],
                })
                break

            logger.info("[DDG] «%s»: %d заголовков", query[:50], len(results))
            return results

    except asyncio.TimeoutError:
        logger.warning("[DDG] Таймаут: %s", query[:50])
    except Exception as exc:
        logger.warning("[DDG] Ошибка «%s»: %s", query[:50], exc)
    return []


async def fetch(
    cities: list[str],
    niches: list[str],
    pain_keywords: list[str],
    max_results: int = 30,
) -> list[dict]:
    """Собирает заголовки из DuckDuckGo по заданным запросам."""
    results: list[dict] = []
    queries = QUERIES.copy()
    random.shuffle(queries)

    async with aiohttp.ClientSession() as session:
        for query, niche, city, pain in queries:
            if len(results) >= max_results:
                break
            items = await _fetch_query(session, query, niche, city, pain)
            results.extend(items)
            # Задержка между запросами
            await asyncio.sleep(2.5)

    logger.info("[DDG] Итого: %d сигналов", len(results))
    return results[:max_results]
