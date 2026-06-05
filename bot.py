"""
Telegram-бот «Радар болей Самарской области».
Запуск: python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

from scanner import CITIES, scan_sources, build_scan_report
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
        "Сканирую публичные отзывы и жалобы жителей Самары, Тольятти, "
        "Новокуйбышевска и Сызрани. Нахожу повторяющиеся боли бизнеса "
        "и предлагаю идеи продуктов.\n\n"
        "📋 *Команды:*\n"
        "/scan — запустить ручное сканирование\n"
        "/status — состояние бота\n"
        "/start — это сообщение",
        parse_mode="Markdown",
    )


@dp.message(Command("status"))
async def cmd_status(message: types.Message) -> None:
    admin_id_display = ADMIN_ID if ADMIN_ID else "не задан"
    cities_str = ", ".join(CITIES)
    await message.answer(
        "✅ *Бот активен*\n\n"
        f"👤 Admin ID: `{admin_id_display}`\n"
        f"🗺 Города: {cities_str}\n"
        "📡 Режим: ручной скан (/scan)\n"
        "🔍 Источники: Яндекс поиск, Отзовик, Авито\n"
        "🤖 AI: OpenRouter (каскад из 4 моделей)\n\n"
        "Готов к сканированию! Используй /scan",
        parse_mode="Markdown",
    )


@dp.message(Command("scan"))
async def cmd_scan(message: types.Message) -> None:
    status_msg = await message.answer(
        "🔍 Сканирую публичные источники...\n"
        "_(Яндекс, Отзовик, Авито — может занять 30-60 секунд)_",
        parse_mode="Markdown",
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

    # Строим отчёт с данными о сигналах
    report = build_scan_report(scan_result)

    if not signals:
        await status_msg.edit_text(
            "⚠️ Реальные источники пока не дали данных.\n"
            "Попробуйте позже или расширьте список источников."
        )
        return

    # Обновляем статус-сообщение → отчёт + запуск AI
    await status_msg.edit_text(
        report + "\n\n🤖 _Запускаю AI-анализ..._",
        parse_mode="Markdown",
    )

    # AI-анализ
    ai_result = await analyze_complaints(signals)

    # Итоговое сообщение: отчёт + AI-вывод
    final = f"{report}\n\n{ai_result}"

    max_len = 4000
    if len(final) <= max_len:
        await status_msg.edit_text(final, parse_mode="Markdown")
    else:
        # Обновляем первое сообщение отчётом, AI шлём отдельно
        await status_msg.edit_text(report, parse_mode="Markdown")
        chunks = [ai_result[i:i + max_len] for i in range(0, len(ai_result), max_len)]
        for chunk in chunks:
            await message.answer(chunk, parse_mode="Markdown")


async def main() -> None:
    logger.info("Запуск бота «Радар болей Самарской области»...")
    logger.info("Admin ID: %s", ADMIN_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
