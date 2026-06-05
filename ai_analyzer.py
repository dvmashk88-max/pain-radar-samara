"""
AI-анализатор жалоб через OpenRouter с каскадом моделей.
"""

import os
import logging
import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MODEL_CASCADE = [
    "qwen/qwen3-30b-a3b:free",
    "deepseek/deepseek-r1-0528:free",
    "google/gemma-3-27b-it:free",
    "mistralai/mistral-7b-instruct:free",
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


async def _call_model(session: aiohttp.ClientSession, model: str, prompt: str) -> str | None:
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
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.warning("Model %s returned %d: %s", model, resp.status, text[:200])
                return None
            data = await resp.json()
            content = data["choices"][0]["message"]["content"]
            if content and len(content.strip()) > 50:
                return content.strip()
            logger.warning("Model %s returned empty/short response", model)
            return None
    except Exception as exc:
        logger.warning("Model %s failed: %s", model, exc)
        return None


async def analyze_complaints(complaints: list[dict]) -> str:
    """Отправляет жалобы в OpenRouter и возвращает анализ ТОП болей."""
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."

    prompt = _build_user_prompt(complaints)

    async with aiohttp.ClientSession() as session:
        for model in MODEL_CASCADE:
            logger.info("Trying model: %s", model)
            result = await _call_model(session, model, prompt)
            if result:
                logger.info("Got response from model: %s", model)
                return f"_Модель: {model}_\n\n{result}"

    return (
        "❌ Все модели OpenRouter недоступны или вернули пустой ответ.\n"
        "Попробуйте позже или проверьте API-ключ."
    )
