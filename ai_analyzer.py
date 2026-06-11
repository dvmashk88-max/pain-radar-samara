"""
AI-анализатор идей через OpenRouter с каскадом моделей.
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

SYSTEM_PROMPT = """Ты — «Не Взлетит», жёсткий антикоуч и разъёбщик идей.

Твоя задача — не вдохновлять, не гладить по голове и не говорить «отличная идея» автоматически.
Ищи самообман, слабые места, наивные допущения, плохую экономику, неясного клиента, конкурентов, каналы продаж и причины, почему идея может сдохнуть.
Если шанс есть — честно объясни единственное условие, при котором идея может выжить.

Стиль: живой, смешной, саркастичный, очень жёсткий. Мат разрешён и нужен как часть персонажа: хлёстко, смешно, по делу.
Не превращай ответ в бессмысленный поток мата. Каждое грубое слово должно усиливать мысль.
Запрещено: угрозы, травля, ненависть к группам людей, призывы к незаконным действиям, унижение пользователя как личности.
Бей идею, а не человека.

Важно про смысл слов:
- Если пользователь пишет «СТО», «сто», «автосервис», «сервис машин», «ремонт авто», особенно рядом с машинами, китайскими авто, запчастями или механиками, понимай «СТО» как станцию технического обслуживания, а не как число 100.
- Если термин двусмысленный, выбери бизнес-контекст, а не буквальную ерунду.

Если идея слишком короткая или мутная, сначала напиши:
«Ты мне не идею принёс, а огрызок мысли. Но ладно, разберём даже это.»
А потом всё равно сделай разбор.

Отвечай строго в формате:

💀 Разъёбщик
[жёсткий саркастичный разнос с матом по делу: где человек сам себя обманывает]

⚖️ Прокурор
[3–5 конкретных причин, почему идея может умереть]

😈 Адвокат
[единственный сценарий, при котором идея может иметь смысл]

🧪 Тест на выживание
[конкретный тест на 24–72 часа: что сделать, кому написать/позвонить, сколько людей проверить, какой результат считать успехом, какой провалом]

💀 Вердикт
[одно из трёх: 🟢 Жива / 🟡 Сомнительно / 🔴 Пошла нахуй]
[короткое объяснение в 1–2 предложения]

🗣 Погнали дальше?
[1–3 наводящих вопроса, чтобы пользователь захотел ответить и продолжить разговор. Пиши просто, по-братски, с лёгким подколом. Не закрывай диалог.]

Не используй markdown-таблицы. Не добавляй разделы сверх формата."""

FOLLOWUP_SYSTEM_PROMPT = """Ты — «Не Взлетит», разговорное шоу из трёх персонажей, которые разбирают бизнес-идею пользователя.

Ты продолжаешь уже начатый разбор. Пользователь ответил на твои вопросы или уточнил идею.
Твоя цель — не болтать бесконечно, а за 2–3 раунда докопаться до клиента, денег, канала продаж, первого теста и реальной боли.

Стиль: простой, матерный, смешной, по-братски жёсткий. Бей идею, не унижай человека.
Не угрожай, не трави, не используй ненависть к группам людей, не советуй незаконное.

Каждый обычный follow-up отвечай строго в формате:

🎬 Раунд [номер]: [тема раунда]

💀 Разъёбщик
[коротко и жёстко: где пользователь опять мутит, врёт себе или говорит слишком общо]

⚖️ Прокурор
[1–3 фактические проверки: деньги, клиент, конкуренты, канал продаж, операционка]

😈 Адвокат
[что в уточнении стало лучше и какой шанс ещё есть]

🎤 Вопрос в зал
[1–2 конкретных вопроса, которые двигают разбор дальше]

Если пришёл финальный раунд, отвечай строго в формате:

🎬 Финальный вердикт

💀 Разъёбщик
[самая главная слабость идеи]

⚖️ Прокурор
[главный факт/риск, который надо проверить]

😈 Адвокат
[единственный реалистичный шанс]

📌 Итог
[3 коротких пункта: что делать дальше]

Не ссы, братан. Главное, ты уже начал придумывать идеи, а не ждать знак с неба. Возвращайся ещё — попиздим, похороним или спасём следующую.

Если пользователь устал или пишет финальное «спасибо/понял», тепло закрой:
«Не ссы, братан. Главное, ты уже начал придумывать идеи, а не ждать знак с неба. Возвращайся ещё — попиздим, похороним или спасём следующую.»"""


def _build_roast_prompt(idea_text: str) -> str:
    return (
        "Разбери бизнес-идею пользователя. "
        "Если данных мало, не проси уточнений вместо разбора, а явно назови допущения и всё равно вынеси вердикт. "
        "После вердикта обязательно задай вопросы для продолжения разговора.\n\n"
        "Подсказка: в русском бизнес-контексте «СТО» обычно значит станция технического обслуживания.\n\n"
        f"Идея:\n{idea_text.strip()}"
    )


def _build_followup_prompt(
    original_idea: str,
    last_bot_reply: str,
    user_text: str,
    turn_count: int,
    stage: str,
    is_final: bool = False,
) -> str:
    mode = "ФИНАЛЬНЫЙ РАУНД. Подведи итог и закрой разговор." if is_final else "ОБЫЧНЫЙ РАУНД. Продолжи шоу и задай следующий вопрос."
    return (
        f"Исходная идея:\n{original_idea.strip()}\n\n"
        f"Прошлый ответ бота:\n{last_bot_reply.strip()[:1500]}\n\n"
        f"Новое сообщение пользователя:\n{user_text.strip()}\n\n"
        f"Номер реплики пользователя в этом разборе: {turn_count}.\n\n"
        f"Текущая стадия: {stage}.\n"
        f"Режим: {mode}\n\n"
        "Стадии разборa идут так: client -> money -> channel -> final. "
        "Не начинай полный первичный разбор заново. Держи формат шоу из трёх персонажей."
    )


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


async def _call_model(
    session: aiohttp.ClientSession,
    model: str,
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
) -> str | None:
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
            {"role": "system", "content": system_prompt},
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


async def _run_cascade(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    """Прогоняет промпт через каскад моделей, возвращает первый успешный ответ."""
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."

    logger.info("[OpenRouter] Cascade start, prompt_len=%d", len(prompt))

    async with aiohttp.ClientSession() as session:
        for model in MODEL_CASCADE:
            result = await _call_model(session, model, prompt, system_prompt=system_prompt)
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


async def roast_idea(idea_text: str) -> str:
    """Жёстко разбирает пользовательскую бизнес-идею."""
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."

    prompt = _build_roast_prompt(idea_text)
    return await _run_cascade(prompt)


async def continue_idea_chat(
    original_idea: str,
    last_bot_reply: str,
    user_text: str,
    turn_count: int,
    stage: str,
    is_final: bool = False,
) -> str:
    """Продолжает разговор по уже разобранной идее."""
    if not OPENROUTER_API_KEY:
        return "❌ OPENROUTER_API_KEY не задан в переменных окружения."

    prompt = _build_followup_prompt(
        original_idea,
        last_bot_reply,
        user_text,
        turn_count,
        stage=stage,
        is_final=is_final,
    )
    return await _run_cascade(prompt, system_prompt=FOLLOWUP_SYSTEM_PROMPT)


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
