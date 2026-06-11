"""
Telegram-бот «Не Взлетит».
Запуск: python3 bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import BotCommand, KeyboardButton, ReplyKeyboardMarkup
from dotenv import load_dotenv

from ai_analyzer import continue_idea_chat, roast_idea
from database import (
    get_idea_stats,
    get_recent_ideas,
    init_idea_db,
    save_idea,
    track_idea_user_message,
)

load_dotenv()

# На некоторых окружениях aiogram 3 + uvloop + Python 3.9 падают при создании
# Dispatcher вне активного event loop. Для Railway и локального запуска хватает
# стандартной политики asyncio.
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

BOT_COMMANDS = [
    BotCommand(command="start", description="Начать разбор идей"),
    BotCommand(command="help", description="Как это работает"),
    BotCommand(command="stats", description="Статистика бота"),
    BotCommand(command="ideas", description="Последние идеи"),
]

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💀 Разнести идею")],
        [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🗃 Идеи пользователей")],
        [KeyboardButton(text="❓ Как это работает")],
    ],
    resize_keyboard=True,
    persistent=True,
)

HELP_TEXT = (
    "Ты кидаешь идею.\n"
    "Бот запускает маленькое шоу из трёх персонажей:\n\n"
    "💀 Разъёбщик — ищет, где ты сам себя обманываешь.\n"
    "⚖️ Прокурор — бьёт по фактам, рынку, деньгам, конкуренции и слабым местам.\n"
    "😈 Адвокат — ищет единственный шанс, при котором идея может выжить.\n\n"
    "В конце бот даёт вердикт:\n"
    "🟢 Жива\n"
    "🟡 Сомнительно\n"
    "🔴 Пошла нахуй\n\n"
    "Потом идёт 2–3 раунда вопросов: клиент, деньги, канал продаж.\n"
    "В финале бот подводит итог, закрывает разговор и ждёт следующую идею."
)

START_TEXT = (
    "💀 Не Взлетит\n\n"
    "Принеси идею.\n"
    "Если она говно — я сэкономлю тебе полгода жизни.\n"
    "Если не говно — сам удивлюсь.\n\n"
    "Напиши идею одним сообщением.\n"
    "Например:\n"
    "“Хочу открыть кофейню возле института”\n"
    "“Хочу сделать сервис для владельцев китайских авто”\n"
    "“Хочу запустить маркетплейс цифровых услуг”"
)

NEW_IDEA_HINT = (
    "Кидай идею одним сообщением. Не презентацию на 40 слайдов, а суть: "
    "что продаёшь, кому, почему они должны платить.\n\n"
    "Если мы уже что-то разбирали, это начнёт новый разнос."
)

NON_IDEA_REPLIES = {
    "привет",
    "привет!",
    "здравствуйте",
    "добрый день",
    "добрый вечер",
    "спасибо",
    "спс",
    "ок",
    "как дела",
    "ты кто",
    "что ты умеешь",
}

CLOSING_REPLIES = {
    "спасибо",
    "спс",
    "понял",
    "поняла",
    "ок",
    "ладно",
    "ясно",
}

NEW_IDEA_STARTERS = (
    "хочу",
    "идея",
    "есть идея",
    "новая идея",
    "другая идея",
    "еще идея",
    "ещё идея",
    "открыть",
    "запустить",
    "сделать",
    "создать",
    "продавать",
)

IDEA_CONTEXT_MARKERS = (
    "сервис",
    "приложение",
    "бот",
    "маркетплейс",
    "кофейня",
    "сто",
    "автосервис",
    "стартап",
    "проект",
)

STAGE_FLOW = {
    "client": "money",
    "money": "channel",
    "channel": "final",
}

MAX_TURNS_PER_IDEA = 4
USER_SESSIONS: dict[int, dict[str, str | int | bool]] = {}


def _send_chunks(text: str, max_len: int = 4000) -> list[str]:
    return [text[i:i + max_len] for i in range(0, len(text), max_len)]


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\ufe0f", "")
    return re.sub(r"\s+", " ", text).strip()


def _is_command(message: types.Message, command: str) -> bool:
    text = _clean_text(message.text)
    return bool(re.fullmatch(rf"/{command}(?:@\w+)?", text, flags=re.IGNORECASE))


def _is_button(message: types.Message, label: str) -> bool:
    return _clean_text(message.text) == _clean_text(label)


def _looks_like_non_idea(text: str) -> bool:
    normalized = _clean_text(text).lower().strip(".,!?")
    return normalized in NON_IDEA_REPLIES


def _looks_like_closing(text: str) -> bool:
    normalized = _clean_text(text).lower().strip(".,!?")
    return normalized in CLOSING_REPLIES


def _looks_like_new_idea(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if len(normalized) < 8:
        return False
    if any(phrase in normalized for phrase in ("новая идея", "другая идея", "еще идея", "ещё идея")):
        return True
    if normalized.startswith(NEW_IDEA_STARTERS):
        return True
    return bool(
        re.search(
            r"\bхочу\b.{0,80}\b(открыть|запустить|сделать|создать|продавать|сервис|приложение|бот|маркетплейс|кофей|сто|автосервис)",
            normalized,
        )
        or re.search(
            r"\b(открыть|запустить|сделать|создать)\b.{0,80}\b(сервис|приложение|бот|маркетплейс|кофей|сто|автосервис|стартап|проект)",
            normalized,
        )
    )


def _is_admin(message: types.Message) -> bool:
    if not ADMIN_ID or not message.from_user:
        return False
    return str(message.from_user.id) == str(ADMIN_ID)


def _next_stage(stage: str) -> str:
    return STAGE_FLOW.get(stage, "final")


def _track_message(message: types.Message, text: str) -> None:
    if not message.from_user:
        return
    track_idea_user_message(
        user_id=message.from_user.id,
        text=text,
        username=message.from_user.username or "",
        first_name=message.from_user.first_name or "",
        last_name=message.from_user.last_name or "",
    )


def _format_idea_preview(text: str, max_len: int = 220) -> str:
    clean = _clean_text(text)
    if len(clean) <= max_len:
        return clean
    return clean[:max_len - 1].rstrip() + "…"


@dp.message(Command("start"))
@dp.message(lambda message: _is_command(message, "start"))
async def cmd_start(message: types.Message) -> None:
    _track_message(message, _clean_text(message.text) or "/start")
    await message.answer(START_TEXT, reply_markup=MAIN_KEYBOARD)


@dp.message(Command("help"))
@dp.message(lambda message: _is_command(message, "help"))
async def cmd_help(message: types.Message) -> None:
    _track_message(message, _clean_text(message.text) or "/help")
    await message.answer(HELP_TEXT, reply_markup=MAIN_KEYBOARD)


@dp.message(Command("stats"))
@dp.message(lambda message: _is_command(message, "stats"))
async def cmd_stats(message: types.Message) -> None:
    _track_message(message, _clean_text(message.text) or "/stats")
    stats = get_idea_stats()
    await message.answer(
        "📊 Статистика «Не Взлетит»\n\n"
        f"Людей всего: {stats['users_total']}\n"
        f"Людей сегодня: {stats['users_today']}\n"
        f"Сообщений всего: {stats['messages_total']}\n"
        f"Сообщений сегодня: {stats['messages_today']}\n"
        f"Идей всего: {stats['ideas_total']}\n"
        f"Идей за неделю: {stats['ideas_week']}\n"
        f"Идей сегодня: {stats['ideas_today']}\n\n"
        "Вот это уже похоже на движуху, а не на одинокий бизнес-план в заметках.",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(Command("ideas"))
@dp.message(lambda message: _is_command(message, "ideas"))
async def cmd_ideas(message: types.Message) -> None:
    _track_message(message, _clean_text(message.text) or "/ideas")
    if not _is_admin(message):
        await message.answer(
            "🗃 Архив идей — это backstage, братан.\n\n"
            "Пока он доступен только автору проекта, чтобы чужие идеи не гуляли по залу.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    ideas = get_recent_ideas(limit=10)
    if not ideas:
        await message.answer(
            "🗃 Идей пока нет.\n\n"
            "Кидай первую. Будет чем потом гордиться или над чем ржать.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    lines = ["🗃 Последние идеи пользователей\n"]
    for idea in ideas:
        username = idea.get("username")
        first_name = idea.get("first_name")
        author = f"@{username}" if username else (first_name or f"user {idea['user_id']}")
        lines.append(
            f"{idea['id']}. {author}\n"
            f"{_format_idea_preview(idea['idea_text'])}"
        )
    await message.answer("\n\n".join(lines), reply_markup=MAIN_KEYBOARD)


@dp.message(F.text == "💀 Разнести идею")
@dp.message(lambda message: _is_button(message, "💀 Разнести идею"))
async def btn_roast(message: types.Message) -> None:
    _track_message(message, _clean_text(message.text) or "💀 Разнести идею")
    if message.from_user:
        USER_SESSIONS[message.from_user.id] = {
            "awaiting_new_idea": True,
            "turn_count": 0,
            "stage": "new",
        }
    await message.answer(
        NEW_IDEA_HINT,
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(F.text == "❓ Как это работает")
@dp.message(lambda message: _is_button(message, "❓ Как это работает"))
async def btn_help(message: types.Message) -> None:
    await cmd_help(message)


@dp.message(F.text == "📊 Статистика")
@dp.message(lambda message: _is_button(message, "📊 Статистика"))
async def btn_stats(message: types.Message) -> None:
    await cmd_stats(message)


@dp.message(F.text == "🗃 Идеи пользователей")
@dp.message(lambda message: _is_button(message, "🗃 Идеи пользователей"))
async def btn_ideas(message: types.Message) -> None:
    await cmd_ideas(message)


@dp.message(F.text)
async def fallback_text(message: types.Message) -> None:
    text = _clean_text(message.text)
    _track_message(message, text)
    logger.info(
        "[Bot] Idea message: user_id=%s chat_id=%s len=%d text=%r",
        message.from_user.id if message.from_user else None,
        message.chat.id if message.chat else None,
        len(text),
        text[:300],
    )

    if text.startswith("/"):
        await message.answer(
            "Я не знаю такую команду. Тут всё проще: тащи идею — будем хоронить или спасать.\n\n"
            "Жми «💀 Разнести идею» или просто пиши идею текстом.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    user_id = message.from_user.id if message.from_user else 0
    session = USER_SESSIONS.get(user_id)

    if session and _looks_like_closing(text):
        USER_SESSIONS.pop(user_id, None)
        await message.answer(
            "Не ссы, братан. Главное, ты уже начал придумывать идеи, "
            "а не ждать знак с неба.\n\n"
            "Возвращайся ещё — попиздим, похороним или спасём следующую.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if not session and _looks_like_non_idea(text):
        await message.answer(
            "Я не психолог и не справочная. Тащи идею — будем хоронить или спасать.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    should_start_new_idea = (
        not session
        or bool(session.get("awaiting_new_idea"))
        or _looks_like_new_idea(text)
    )

    if session and not session.get("awaiting_new_idea") and session.get("original_idea") and not should_start_new_idea:
        await message.answer("💀 Докапываюсь дальше...", reply_markup=MAIN_KEYBOARD)
        turn_count = int(session.get("turn_count", 1)) + 1
        stage = str(session.get("stage", "client"))
        is_final = turn_count >= MAX_TURNS_PER_IDEA or stage == "final"
        result = await continue_idea_chat(
            original_idea=str(session.get("original_idea", "")),
            last_bot_reply=str(session.get("last_bot_reply", "")),
            user_text=text,
            turn_count=turn_count,
            stage=stage,
            is_final=is_final,
        )
        if is_final:
            USER_SESSIONS.pop(user_id, None)
        else:
            session["last_bot_reply"] = result
            session["turn_count"] = turn_count
            session["stage"] = _next_stage(stage)
            USER_SESSIONS[user_id] = session
    else:
        if user_id:
            save_idea(user_id, text)
        await message.answer("💀 Разбираю идею...", reply_markup=MAIN_KEYBOARD)
        result = await roast_idea(text)
        if user_id:
            USER_SESSIONS[user_id] = {
                "original_idea": text,
                "last_bot_reply": result,
                "turn_count": 1,
                "stage": "client",
                "awaiting_new_idea": False,
            }

    for chunk in _send_chunks(result):
        await message.answer(chunk)


@dp.message()
async def fallback_message(message: types.Message) -> None:
    await message.answer(
        "Я разбираю только текстовые идеи. Пришли одну фразу или абзац — и начнём.",
        reply_markup=MAIN_KEYBOARD,
    )


async def main() -> None:
    logger.info("Запуск бота «Не Взлетит»...")
    logger.info("Admin ID: %s", ADMIN_ID)
    init_idea_db()
    await bot.set_my_commands(BOT_COMMANDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
