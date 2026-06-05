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

SYSTEM_PROMPT = """Ты — аналитик рынка малого бизнеса.
Анализируй отзывы и жалобы жителей Самарской области.
Отвечай строго в указанном формате, без лишних слов."""


def _build_user_prompt(complaints: list[dict]) -> str:
    lines = ["Вот жалобы жителей Самарской области:\n"]
    for i, c in enumerate(complaints, 1):
        pains_str = ", ".join(c["pains"])
        lines.append(f"{i}. [{c['niche']} / {c['city']}] {c['text']}")
        lines.append(f"   Болевые слова: {pains_str}\n")

    lines.append("""
На основе этих жалоб выдели ТОП-5 болей и ответь СТРОГО в формате:

🔥 ТОП БОЛЕЙ САМАРСКОЙ ОБЛАСТИ

1. Ниша: [название ниши]
Проблема: [описание проблемы]
Повторяемость: [как часто встречается]
Идея продукта: [конкретная идея решения]
Можно решить ботом/ИИ: [Да/Нет + объяснение]
Оценка возможности: [X]/10

(и так для каждой из 5 болей)""")
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


async def analyze_complaints(complaints: list[dict]) -> str:
    """Отправляет жалобы в OpenRouter и возвращает анализ ТОП болей."""
    key_loaded = bool(OPENROUTER_API_KEY)
    logger.info("[OpenRouter] API key loaded: %s", key_loaded)

    if not key_loaded:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."

    prompt = _build_user_prompt(complaints)
    logger.info("[OpenRouter] Starting cascade over %d models, prompt_len=%d",
                len(MODEL_CASCADE), len(prompt))

    async with aiohttp.ClientSession() as session:
        for model in MODEL_CASCADE:
            result = await _call_model(session, model, prompt)
            if result:
                logger.info("[OpenRouter] Success with model: %s", model)
                return f"_Модель: {model}_\n\n{result}"
            logger.info("[OpenRouter] Model %s failed, trying next...", model)

    logger.error("[OpenRouter] All %d models failed.", len(MODEL_CASCADE))
    return (
        "❌ Все модели OpenRouter недоступны или вернули пустой ответ.\n"
        "Попробуйте позже или проверьте API-ключ."
    )
