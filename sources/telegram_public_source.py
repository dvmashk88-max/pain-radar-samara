"""
Источник: публичные Telegram-каналы через t.me/s/channel_name.
Не использует Telegram API и Telethon — только публичные web-страницы.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

SOURCE_NAME = "Telegram"

# Публичные каналы о Самарской области: (channel_name, fallback_city)
CHANNELS = [
    ("chp_samara", "Самара"),       # ЧП Самара — происшествия, жалобы
    ("samara", "Самара"),           # Самара — городские новости
    ("tlt_online", "Тольятти"),      # Тольятти онлайн
    ("typ_tlt", "Тольятти"),         # Типичный Тольятти
    ("tolyattij", "Тольятти"),       # Тольятти Подслушано
    ("podslushano_tlt", "Тольятти"), # Подслушано Тольятти
    ("MoyGorodNSK", "Новокуйбышевск"),
    ("nvklife63", "Новокуйбышевск"),
    ("syzranvip", "Сызрань"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TAG_RE = re.compile(r"<[^>]+>")
_POST_RE = re.compile(
    r'class="tgme_widget_message_text(?:[^"]*)"[^>]*>(.*?)</div>',
    re.DOTALL | re.IGNORECASE,
)
_HTML_ENTITIES = [
    ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
    ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
    ("&#33;", "!"), ("&#8212;", "—"), ("&#8211;", "–"),
]

STOP_TOPICS = [
    "дтп",
    "авария",
    "пожар",
    "погиб",
    "погибл",
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

QUEUE_FALSE_POSITIVES = [
    "в первую очередь",
    "во вторую очередь",
    "вторую очередь",
    "третью очередь",
    "очередь аллеи",
    "очередь строительства",
]


def _clean(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    for entity, char in _HTML_ENTITIES:
        text = text.replace(entity, char)
    return " ".join(text.split()).strip()


async def _fetch_channel(
    session: aiohttp.ClientSession,
    channel: str,
    fallback_city: str,
    pain_keywords: list[str],
) -> list[dict]:
    url = f"https://t.me/s/{channel}"
    try:
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                logger.warning("[Telegram] @%s: HTTP %d", channel, resp.status)
                return []

            html = await resp.text(errors="replace")

            if "tgme_widget_message" not in html:
                logger.warning("[Telegram] @%s: нет постов в HTML", channel)
                return []

            results = []

            for match in _POST_RE.finditer(html):
                text = _clean(match.group(1))
                if len(text) < 30:
                    continue

                text_lower = text.lower()
                if _is_irrelevant(text_lower):
                    continue

                found_pains = _find_pains(text_lower, pain_keywords)
                if not found_pains:
                    continue

                city = _detect_city(text_lower, fallback_city)
                niche = _detect_niche(text_lower)

                results.append({
                    "source": SOURCE_NAME,
                    "niche": niche,
                    "city": city,
                    "text": text[:400],
                    "url": url,
                    "pains": found_pains,
                })

            logger.info("[Telegram] @%s: постов с болями: %d", channel, len(results))
            return results

    except asyncio.TimeoutError:
        logger.warning("[Telegram] @%s: таймаут", channel)
    except aiohttp.ClientConnectorError as exc:
        logger.warning("[Telegram] @%s: недоступен: %s", channel, exc)
    except Exception as exc:
        logger.warning("[Telegram] @%s: ошибка: %s", channel, exc)
    return []


def _is_irrelevant(text: str) -> bool:
    return any(stop_word in text for stop_word in STOP_TOPICS)


def _find_pains(text: str, pain_keywords: list[str]) -> list[str]:
    found = []
    for keyword in pain_keywords:
        if keyword not in text:
            continue
        if keyword == "очередь" and any(phrase in text for phrase in QUEUE_FALSE_POSITIVES):
            continue
        found.append(keyword)
    return found


def _detect_city(text: str, fallback_city: str) -> str:
    city_map = [
        ("Новокуйбышевск", ["новокуйбышевск", "новокуйбышевц"]),
        ("Сызрань", ["сызран", "сызранск"]),
        ("Тольятти", ["тольятти", "тлт", "tlt"]),
        ("Самара", ["самар", "samara"]),
    ]
    for city, markers in city_map:
        if any(marker in text for marker in markers):
            return city
    return fallback_city


def _detect_niche(text: str) -> str:
    niche_map = [
        (
            "жкх",
            [
                "жкх",
                "управляющая",
                "коммунал",
                "жилищн",
                "водоснабж",
                "теплоснабж",
                "мусор",
                "свалк",
                "не убирают",
                "уборка",
                "гряз",
                "двор",
                "дорога",
                "дороги",
                "дорогу",
                "дорогах",
                "тротуар",
                "площадк",
                "автостанц",
            ],
        ),
        ("автосервис", ["автосервис", "ремонт авто", "шиномонтаж"]),
        ("клиника", ["больниц", "поликлиник", "врач", "скорая", "медицин", "клиник"]),
        ("стоматология", ["стоматолог", "зуб", "дантист"]),
        ("доставка еды", ["доставк", "курьер", "привез", "заказ еды"]),
        ("банки", ["банк", "кредит", "карта", "займ", "вклад"]),
        ("ремонт квартир", ["ремонт квартир", "строитель", "прораб", "бригада"]),
        ("салоны красоты", ["салон красот", "парикмахер", "маникюр", "косметолог"]),
        ("юристы", ["юрист", "адвокат", "нотариус", "правовая"]),
        ("грузоперевозки", ["грузоперевоз", "переезд", "грузчик", "такелаж"]),
    ]
    for niche, keywords in niche_map:
        if any(kw in text for kw in keywords):
            return niche
    return "другое"


async def fetch(
    cities: list[str],
    niches: list[str],
    pain_keywords: list[str],
    max_results: int = 40,
) -> list[dict]:
    """Собирает посты с болевыми словами из публичных Telegram-каналов."""
    results: list[dict] = []

    async with aiohttp.ClientSession() as session:
        for channel, fallback_city in CHANNELS:
            if len(results) >= max_results:
                break
            items = await _fetch_channel(session, channel, fallback_city, pain_keywords)
            results.extend(items)
            await asyncio.sleep(1.0)

    logger.info("[Telegram] Итого: %d сигналов", len(results))
    return results[:max_results]
