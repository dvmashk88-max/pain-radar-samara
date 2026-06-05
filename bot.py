"""
Telegram-бот «Радар болей Самарской области».
Запуск: python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from dotenv import load_dotenv

from scanner import CITIES, DISABLED_SOURCES, scan_sources, build_scan_report
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

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🚀 Сканировать"), KeyboardButton(text="📊 Статус")],
        [KeyboardButton(text="ℹ️ Помощь"), KeyboardButton(text="🔄 Перезапуск")],
    ],
    resize_keyboard=True,
    persistent=True,
)

ACTIVE_SOURCES = ["Telegram t.me/s", "DuckDuckGo HTML", "VC.ru", "Habr Q&A"]


# --- Команды ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        "🔥 Радар болей Самарской области\n\n"
        "Сканирую публичные источники: Telegram-каналы и DuckDuckGo "
        "по Самаре, Тольятти, Новокуйбышевску и Сызрани.\n\n"
        "Нахожу повторяющиеся боли бизнеса и предлагаю идеи продуктов с помощью AI.\n\n"
        "Используй кнопки ниже или команды:\n"
        "/scan — запустить сканирование\n"
        "/status — состояние бота",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(Command("status"))
async def cmd_status(message: types.Message) -> None:
    admin_id_display = ADMIN_ID if ADMIN_ID else "не задан"
    cities_str = ", ".join(CITIES)
    active_str = "\n".join(f"  - {s}" for s in ACTIVE_SOURCES)
    disabled_str = "\n".join(f"  - {s}" for s in DISABLED_SOURCES)

    await message.answer(
        "✅ Бот активен\n\n"
        f"Admin ID: {admin_id_display}\n"
        f"Города: {cities_str}\n\n"
        "Режим: ручной скан\n\n"
        f"Активные источники:\n{active_str}\n\n"
        f"Отключённые источники (блокируют):\n{disabled_str}\n\n"
        "AI: OpenRouter (каскад из 4 моделей)\n\n"
        "Нажми 🚀 или /scan для сканирования",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(Command("scan"))
async def cmd_scan(message: types.Message) -> None:
    await _do_scan(message)


# --- Обработчики кнопок ---

@dp.message(F.text == "🚀 Сканировать")
async def btn_scan(message: types.Message) -> None:
    await _do_scan(message)


@dp.message(F.text == "📊 Статус")
async def btn_status(message: types.Message) -> None:
    await cmd_status(message)


@dp.message(F.text == "ℹ️ Помощь")
async def btn_help(message: types.Message) -> None:
    niches = "автосервис, стоматология, клиника, ремонт квартир, салоны красоты, доставка, банки, ЖКХ, юристы, грузоперевозки"
    await message.answer(
        "ℹ️ Радар болей Самарской области\n\n"
        "Что делает бот:\n"
        "Сканирует Telegram-каналы и публичные сайты в поисках жалоб "
        "жителей Самарской области на малый бизнес.\n\n"
        "Команды:\n"
        "🚀 /scan — сканировать источники и получить AI-анализ болей\n"
        "📊 /status — проверить состояние и список источников\n"
        "🔄 /start — перезапустить бота\n\n"
        f"Ниши: {niches}\n\n"
        "Болевые слова: не дозвониться, хамство, обман, дорого, долго и ещё 9",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(F.text == "🔄 Перезапуск")
async def btn_restart(message: types.Message) -> None:
    await cmd_start(message)


# --- Логика сканирования ---

async def _do_scan(message: types.Message) -> None:
    status_msg = await message.answer(
        "🔍 Сканирую публичные источники...\n"
        "Telegram каналы, DuckDuckGo — займёт 30-90 секунд",
        reply_markup=MAIN_KEYBOARD,
    )

    try:
        scan_result = await scan_sources()
    except Exception as exc:
        logger.error("[Bot] Ошибка scan_sources: %s", exc)
        await status_msg.edit_text(f"❌ Ошибка сканирования: {exc}")
        return

    signals = scan_result["signals"]
    stats = scan_result["stats"]
    logger.info("[Bot] Scan done: %s", stats)

    if not signals:
        await status_msg.edit_text(
            "⚠️ Источники пока не дали данных.\n"
            "Попробуйте позже или нажмите 🚀 ещё раз."
        )
        return

    report = build_scan_report(scan_result)

    await status_msg.edit_text(report + "\n\n🤖 AI-анализ запущен...")

    ai_result = await analyze_complaints(signals)

    final = f"{report}\n\n{ai_result}"

    max_len = 4000
    if len(final) <= max_len:
        await status_msg.edit_text(final)
    else:
        await status_msg.edit_text(report)
        chunks = [ai_result[i:i + max_len] for i in range(0, len(ai_result), max_len)]
        for chunk in chunks:
            await message.answer(chunk)


async def main() -> None:
    logger.info("Запуск бота «Радар болей Самарской области»...")
    logger.info("Admin ID: %s", ADMIN_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
