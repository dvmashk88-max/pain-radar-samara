"""
AI-анализатор жалоб через OpenRouter с каскадом моделей.
"""

from __future__ import annotations

import os
import logging
import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Актуальный каскад бесплатных моделей OpenRouter (проверено 2026-06-05).
# Если одна недоступна (429/404/пустой ответ) — пробуем следующую.
MODEL_CASCADE = [
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/free",
]

SYSTEM_PROMPT = """Ты — аналитик рынка малого бизнеса Самарской области.
Пиши коротко, только списками. Без таблиц, без markdown-заголовков ## и ***, без лишних слов."""


def _build_user_prompt(complaints: list[dict]) -> str:
    lines = ["Жалобы жителей Самарской области:\n"]
    for i, c in enumerate(complaints[:30], 1):  # не больше 30 для экономии токенов
        pains_str = ", ".join(c.get("pains", []))
        src = c.get("source", "")
        lines.append(f"{i}. [{c['niche']} / {c['city']}]{f' ({src})' if src else ''} {c['text'][:200]}")
        if pains_str:
            lines.append(f"   Боли: {pains_str}")

    lines.append("""
Выдели главные боли и ответь СТРОГО в этом формате (только списки, без таблиц):

🤖 AI-вывод:
- Главная боль: [одна фраза]
- Самая интересная ниша: [ниша + почему]
- Идея продукта: [конкретная идея]
- Оценка возможности: [X]/10
- Быстрый старт: [что сделать первым]""")
    return "\n".join(lines)


def _extract_content(data: dict) -> str | None:
    """Извлекает текст ответа из структуры OpenRouter.
    Некоторые reasoning-модели возвращают content=null, но заполняют reasoning.
    """
    try:
        msg = data["choices"][0]["message"]
        content = msg.get("content")
        if content and len(content.strip()) > 50:
            return content.strip()
        # Fallback на reasoning (модели с chain-of-thought вроде nemotron)
        reasoning = msg.get("reasoning") or msg.get("reasoning_content")
        if reasoning and len(reasoning.strip()) > 50:
            logger.info("Using 'reasoning' field as content fallback")
            return reasoning.strip()
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Failed to extract content from response: %s", exc)
    return None


async def _call_model(session: aiohttp.ClientSession, model: str, prompt: str) -> str | None:
    logger.info("[OpenRouter] Calling model: %s", model)
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://pain-radar-samara.railway.app",
        "X-Title": "Pain Radar Samara",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 2000,
        "temperature": 0.7,
    }
    try:
        async with session.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=90),
        ) as resp:
            status = resp.status
            raw = await resp.text()
            logger.info("[OpenRouter] Model=%s status=%d body_len=%d", model, status, len(raw))

            if status != 200:
                # Логируем полный ответ ошибки для диагностики
                logger.warning("[OpenRouter] Model=%s HTTP %d error: %s", model, status, raw[:400])
                return None

            try:
                data = __import__("json").loads(raw)
            except Exception as parse_exc:
                logger.warning("[OpenRouter] Model=%s JSON parse error: %s | raw: %s",
                               model, parse_exc, raw[:200])
                return None

            content = _extract_content(data)
            if content:
                logger.info("[OpenRouter] Model=%s returned %d chars", model, len(content))
                return content

            logger.warning("[OpenRouter] Model=%s returned empty/null content. Full response: %s",
                           model, raw[:400])
            return None

    except aiohttp.ClientConnectorError as exc:
        logger.warning("[OpenRouter] Model=%s connection error: %s", model, exc)
    except aiohttp.ServerTimeoutError:
        logger.warning("[OpenRouter] Model=%s timed out after 90s", model)
    except Exception as exc:
        logger.warning("[OpenRouter] Model=%s unexpected error: %s (%s)",
                       model, exc, type(exc).__name__)
    return None


async def _run_cascade(prompt: str) -> str:
    """Прогоняет промпт через каскад моделей, возвращает первый успешный ответ."""
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."

    logger.info("[OpenRouter] Cascade start, prompt_len=%d", len(prompt))

    async with aiohttp.ClientSession() as session:
        for model in MODEL_CASCADE:
            result = await _call_model(session, model, prompt)
            if result:
                logger.info("[OpenRouter] Success: %s", model)
                return result
            logger.info("[OpenRouter] %s failed, trying next...", model)

    logger.error("[OpenRouter] All models failed.")
    return (
        "❌ Все модели OpenRouter недоступны или вернули пустой ответ.\n"
        "Попробуйте позже или проверьте API-ключ."
    )


async def analyze_complaints(complaints: list[dict]) -> str:
    """Анализирует сигналы текущего скана."""
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."
    prompt = _build_user_prompt(complaints)
    return await _run_cascade(prompt)


def _build_history_prompt(signals: list[dict], period_label: str) -> str:
    """Строит промпт для анализа исторических данных из БД."""
    lines = [f"Жалобы жителей Самарской области за {period_label}:\n"]

    pain_counts: dict[str, int] = {}
    niche_counts: dict[str, int] = {}

    for i, s in enumerate(signals[:40], 1):
        pains = s.get("pains", [])
        if isinstance(pains, str):
            pains = [p.strip() for p in pains.split(",") if p.strip()]
        pains_str = ", ".join(pains)
        lines.append(
            f"{i}. [{s.get('niche','?')} / {s.get('city','?')}] "
            f"{s.get('text','')[:150]}"
        )
        if pains_str:
            lines.append(f"   Боли: {pains_str}")
        for p in pains:
            pain_counts[p] = pain_counts.get(p, 0) + 1
        n = s.get("niche", "")
        if n:
            niche_counts[n] = niche_counts.get(n, 0) + 1

    top_pains = sorted(pain_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_niches = sorted(niche_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    summary = []
    if top_pains:
        summary.append("Топ болей: " + ", ".join(f"{p}({c})" for p, c in top_pains))
    if top_niches:
        summary.append("Топ ниш: " + ", ".join(f"{n}({c})" for n, c in top_niches))
    if summary:
        lines.append("\nСтатистика: " + " | ".join(summary))

    if period_label.startswith("7"):
        lines.append("""
Сделай короткий AI-вывод СТРОГО в формате (только список, без таблиц):

🤖 AI-вывод за неделю:
- Главная боль недели: [одна фраза]
- Ниша недели: [ниша + почему]
- Что проверить быстро: [конкретное действие]
- Идея продукта: [конкретная идея]
- Оценка возможности: [X]/10""")
    else:
        lines.append("""
Сделай короткий AI-вывод СТРОГО в формате (только список, без таблиц):

🤖 AI-вывод за месяц:
- Главная боль месяца: [одна фраза]
- Ниша месяца: [ниша + почему]
- Тренд месяца: [что нарастает]
- Идея продукта: [конкретная идея]
- Оценка возможности: [X]/10""")

    return "\n".join(lines)


async def analyze_history(signals: list[dict], period: str) -> str:
    """
    Анализирует исторические сигналы из БД.
    period: '7 дней' или '30 дней'
    """
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."
    if not signals:
        return (
            "Пока мало данных.\n"
            "Нажмите 🔍 Сканировать несколько раз в разные дни — "
            "данные накопятся и AI-анализ станет точнее."
        )
    prompt = _build_history_prompt(signals, period)
    return await _run_cascade(prompt)
