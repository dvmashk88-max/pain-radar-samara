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

from ai_analyzer import roast_idea

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
    BotCommand(command="status", description="Статус бота"),
]

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💀 Разнести идею")],
        [KeyboardButton(text="❓ Как это работает"), KeyboardButton(text="ℹ️ Статус")],
    ],
    resize_keyboard=True,
    persistent=True,
)

HELP_TEXT = (
    "Ты кидаешь идею.\n"
    "Бот прогоняет её через трёх персонажей:\n\n"
    "🎭 Подъёбщик — ищет, где ты сам себя обманываешь.\n"
    "⚖️ Прокурор — бьёт по фактам, рынку, деньгам, конкуренции и слабым местам.\n"
    "😈 Адвокат — ищет единственный шанс, при котором идея может выжить.\n\n"
    "В конце бот даёт вердикт:\n"
    "🟢 Жива\n"
    "🟡 Сомнительно\n"
    "🔴 Пошла нахуй"
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


@dp.message(Command("start"))
@dp.message(lambda message: _is_command(message, "start"))
async def cmd_start(message: types.Message) -> None:
    await message.answer(START_TEXT, reply_markup=MAIN_KEYBOARD)


@dp.message(Command("help"))
@dp.message(lambda message: _is_command(message, "help"))
async def cmd_help(message: types.Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=MAIN_KEYBOARD)


@dp.message(Command("status"))
@dp.message(lambda message: _is_command(message, "status"))
async def cmd_status(message: types.Message) -> None:
    admin_id_display = ADMIN_ID if ADMIN_ID else "не задан"
    openrouter_status = "задан" if OPENROUTER_API_KEY else "не задан"

    await message.answer(
        "✅ Не Взлетит активен\n\n"
        "Режим: разбор идей по одному сообщению\n"
        "Сканирование источников: отключено\n"
        "База статистики: не используется в интерфейсе\n\n"
        f"Admin ID: {admin_id_display}\n"
        f"OpenRouter API key: {openrouter_status}",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(F.text == "💀 Разнести идею")
@dp.message(lambda message: _is_button(message, "💀 Разнести идею"))
async def btn_roast(message: types.Message) -> None:
    await message.answer(
        "Кидай идею одним сообщением. Не презентацию на 40 слайдов, а суть: "
        "что продаёшь, кому, почему они должны платить.",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(F.text == "❓ Как это работает")
@dp.message(lambda message: _is_button(message, "❓ Как это работает"))
async def btn_help(message: types.Message) -> None:
    await cmd_help(message)


@dp.message(F.text == "ℹ️ Статус")
@dp.message(lambda message: _is_button(message, "ℹ️ Статус"))
async def btn_status(message: types.Message) -> None:
    await cmd_status(message)


@dp.message(F.text)
async def fallback_text(message: types.Message) -> None:
    text = _clean_text(message.text)
    logger.info(
        "[Bot] Idea message: user_id=%s chat_id=%s len=%d text=%r",
        message.from_user.id if message.from_user else None,
        message.chat.id if message.chat else None,
        len(text),
        text[:300],
    )

    if text.startswith("/"):
        await message.answer(
            "Я не знаю такую команду. Тут всё проще: тащи идею — будем хоронить или спасать.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if _looks_like_non_idea(text):
        await message.answer(
            "Я не психолог и не справочная. Тащи идею — будем хоронить или спасать.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await message.answer("💀 Разбираю идею...", reply_markup=MAIN_KEYBOARD)
    result = await roast_idea(text)
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
    await bot.set_my_commands(BOT_COMMANDS)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
