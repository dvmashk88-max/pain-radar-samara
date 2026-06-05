"""
Telegram-бот «Радар болей Самарской области».
Запуск: python bot.py
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

from scanner import scan_reviews, get_scan_summary
from ai_analyzer import analyze_complaints

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        "🔥 *Радар болей Самарской области*\n\n"
        "Этот бот сканирует отзывы и жалобы жителей Самары и Тольятти, "
        "находит повторяющиеся проблемы в малом бизнесе и предлагает идеи продуктов.\n\n"
        "📋 *Команды:*\n"
        "/scan — запустить сканирование и анализ болей\n"
        "/status — проверить состояние бота\n"
        "/start — это сообщение",
        parse_mode="Markdown",
    )


@dp.message(Command("status"))
async def cmd_status(message: types.Message) -> None:
    admin_id_display = ADMIN_ID if ADMIN_ID else "не задан"
    await message.answer(
        "✅ *Бот живой и готов к работе*\n\n"
        f"👤 Admin ID: `{admin_id_display}`\n"
        "📡 Источников данных: 30 демо-отзывов\n"
        "🤖 AI-анализ: OpenRouter (каскад из 4 моделей)\n"
        "🗺 Регион: Самара и Тольятти\n\n"
        "Готов к сканированию! Используй /scan",
        parse_mode="Markdown",
    )


@dp.message(Command("scan"))
async def cmd_scan(message: types.Message) -> None:
    status_msg = await message.answer("🔍 Запускаю сканирование отзывов...")

    reviews = scan_reviews()
    summary = get_scan_summary(reviews)

    await status_msg.edit_text(
        f"✅ Сканирование завершено!\n\n<pre>{summary}</pre>\n\n"
        "🤖 Отправляю данные на AI-анализ...",
        parse_mode="HTML",
    )

    if not reviews:
        await message.answer("❌ Жалобы с болевыми словами не найдены.")
        return

    analysis = await analyze_complaints(reviews)

    max_len = 4000
    if len(analysis) <= max_len:
        await message.answer(analysis, parse_mode="Markdown")
    else:
        chunks = [analysis[i:i + max_len] for i in range(0, len(analysis), max_len)]
        for chunk in chunks:
            await message.answer(chunk, parse_mode="Markdown")


async def main() -> None:
    logger.info("Запуск бота «Радар болей Самарской области»...")
    logger.info("Admin ID: %s", ADMIN_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
