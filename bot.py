"""
Telegram-бот «Радар болей Самарской области».
Запуск: python3 bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from dotenv import load_dotenv

from scanner import CITIES, DISABLED_SOURCES, scan_sources, build_scan_report
from ai_analyzer import analyze_complaints, analyze_history
from database import (
    clear_signals,
    filter_new_signals,
    get_signals_since,
    get_stats,
    init_db,
    save_signals,
)

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
        [KeyboardButton(text="🔍 Сканировать"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="🤖 AI за 7 дней"), KeyboardButton(text="🤖 AI за 30 дней")],
        [KeyboardButton(text="ℹ️ Статус"), KeyboardButton(text="❓ Помощь")],
    ],
    resize_keyboard=True,
    persistent=True,
)

ACTIVE_SOURCES = ["Telegram t.me/s", "DuckDuckGo HTML", "VC.ru", "Habr Q&A"]
MIN_SIGNALS_FOR_AI = 3


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


def _is_admin(message: types.Message) -> bool:
    if not ADMIN_ID or not message.from_user:
        return False
    return str(message.from_user.id) == str(ADMIN_ID)


# --- Команды ---

@dp.message(Command("start"))
@dp.message(lambda message: _is_command(message, "start"))
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        "🔥 Радар болей Самарской области\n\n"
        "Сканирую Telegram-каналы и DuckDuckGo по Самаре, Тольятти, "
        "Новокуйбышевску и Сызрани.\n"
        "Накапливаю сигналы в базе и делаю AI-анализ за 7 и 30 дней.\n\n"
        "Команды:\n"
        "/scan — собрать новые сигналы\n"
        "/stats — статистика из базы\n"
        "/ai_week — AI-анализ за 7 дней\n"
        "/ai_month — AI-анализ за 30 дней\n"
        "/status — состояние бота\n"
        "/reset_data — очистить тестовую базу (только админ)",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(Command("status"))
@dp.message(lambda message: _is_command(message, "status"))
async def cmd_status(message: types.Message) -> None:
    admin_id_display = ADMIN_ID if ADMIN_ID else "не задан"
    cities_str = ", ".join(CITIES)
    active_str = "\n".join(f"  - {s}" for s in ACTIVE_SOURCES)
    disabled_str = "\n".join(f"  - {s}" for s in DISABLED_SOURCES)

    await message.answer(
        "✅ Бот активен\n\n"
        f"Admin ID: {admin_id_display}\n"
        f"Города: {cities_str}\n\n"
        "Режим: ручной скан\n"
        "База данных: SQLite (data/pain_radar.db)\n\n"
        f"Активные источники:\n{active_str}\n\n"
        f"Отключённые (блокируют с Railway):\n{disabled_str}\n\n"
        "AI: OpenRouter (каскад из 4 моделей)",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message(Command("scan"))
@dp.message(lambda message: _is_command(message, "scan"))
async def cmd_scan(message: types.Message) -> None:
    await _do_scan(message)


@dp.message(Command("stats"))
@dp.message(lambda message: _is_command(message, "stats"))
async def cmd_stats(message: types.Message) -> None:
    await _do_stats(message)


@dp.message(Command("ai_week"))
@dp.message(lambda message: _is_command(message, "ai_week"))
async def cmd_ai_week(message: types.Message) -> None:
    await _do_ai_history(message, days=7, period="7 дней")


@dp.message(Command("ai_month"))
@dp.message(lambda message: _is_command(message, "ai_month"))
async def cmd_ai_month(message: types.Message) -> None:
    await _do_ai_history(message, days=30, period="30 дней")


@dp.message(Command("reset_data"))
@dp.message(lambda message: _is_command(message, "reset_data"))
async def cmd_reset_data(message: types.Message) -> None:
    if not _is_admin(message):
        await message.answer("⛔ Команда доступна только администратору.")
        return

    deleted = clear_signals()
    await message.answer(
        f"🧹 Тестовая база очищена: удалено {deleted} сигналов.\n"
        "Теперь нажмите 🔍 Сканировать, чтобы собрать статистику заново.",
        reply_markup=MAIN_KEYBOARD,
    )


# --- Обработчики кнопок ---

@dp.message(F.text == "🔍 Сканировать")
@dp.message(lambda message: _is_button(message, "🔍 Сканировать"))
async def btn_scan(message: types.Message) -> None:
    await _do_scan(message)


@dp.message(F.text == "📊 Статистика")
@dp.message(lambda message: _is_button(message, "📊 Статистика"))
async def btn_stats(message: types.Message) -> None:
    await _do_stats(message)


@dp.message(F.text == "🤖 AI за 7 дней")
@dp.message(lambda message: _is_button(message, "🤖 AI за 7 дней"))
async def btn_ai_week(message: types.Message) -> None:
    await _do_ai_history(message, days=7, period="7 дней")


@dp.message(F.text == "🤖 AI за 30 дней")
@dp.message(lambda message: _is_button(message, "🤖 AI за 30 дней"))
async def btn_ai_month(message: types.Message) -> None:
    await _do_ai_history(message, days=30, period="30 дней")


@dp.message(F.text == "ℹ️ Статус")
@dp.message(lambda message: _is_button(message, "ℹ️ Статус"))
async def btn_status(message: types.Message) -> None:
    await cmd_status(message)


@dp.message(F.text == "❓ Помощь")
@dp.message(lambda message: _is_button(message, "❓ Помощь"))
async def btn_help(message: types.Message) -> None:
    niches = (
        "автосервис, стоматология, клиника, ремонт квартир, "
        "салоны красоты, доставка, банки, ЖКХ, юристы, грузоперевозки"
    )
    await message.answer(
        "❓ Радар болей Самарской области\n\n"
        "Что делает бот:\n"
        "Сканирует Telegram-каналы и DuckDuckGo, собирает жалобы "
        "жителей Самарской области на малый бизнес, сохраняет в базу "
        "и делает AI-анализ накопленных данных.\n\n"
        "Команды:\n"
        "🔍 /scan — сканировать и сохранить новые сигналы\n"
        "📊 /stats — статистика из базы\n"
        "🤖 /ai_week — AI-анализ за 7 дней\n"
        "🤖 /ai_month — AI-анализ за 30 дней\n"
        "ℹ️ /status — состояние бота\n"
        "🧹 /reset_data — очистить тестовую базу (только админ)\n\n"
        f"Ниши: {niches}\n\n"
        "Болевые слова: не дозвониться, хамство, обман, дорого, долго и ещё 9",
        reply_markup=MAIN_KEYBOARD,
    )


@dp.message()
async def fallback_message(message: types.Message) -> None:
    logger.info(
        "[Bot] Unmatched message: user_id=%s chat_id=%s content_type=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.chat.id if message.chat else None,
        message.content_type,
        message.text,
    )
    await message.answer(
        "Не распознал команду. Нажмите /start или выберите кнопку в меню.",
        reply_markup=MAIN_KEYBOARD,
    )


# --- Бизнес-логика ---

async def _do_scan(message: types.Message) -> None:
    await message.answer(
        "🔍 Сканирую публичные источники...\n"
        "Telegram каналы, DuckDuckGo — займёт 30-90 секунд",
        reply_markup=MAIN_KEYBOARD,
    )

    try:
        scan_result = await scan_sources()
    except Exception as exc:
        logger.error("[Bot] Ошибка scan_sources: %s", exc)
        await message.answer(f"❌ Ошибка сканирования: {exc}")
        return

    signals = scan_result["signals"]
    stats = scan_result["stats"]
    logger.info("[Bot] Scan done: %s", stats)

    if not signals:
        await message.answer(
            "⚠️ Источники пока не дали данных.\n"
            "Попробуйте позже или нажмите 🔍 ещё раз."
        )
        return

    # Сохраняем в БД только новые сигналы. Иначе AI будет повторять старый анализ.
    new_signals, existing_duplicates = filter_new_signals(signals)
    saved, save_duplicates = save_signals(new_signals)
    skipped = existing_duplicates + save_duplicates

    report = build_scan_report(scan_result)
    db_line = f"\nСохранено в базу: {saved} новых, {skipped} дублей пропущено"
    await message.answer(report + db_line)

    if saved == 0:
        await message.answer(
            "Новых сигналов с прошлого скана нет.\n"
            "Источники часто отдают те же публичные посты и поисковые заголовки; "
            "AI-анализ не запускаю, чтобы не повторять старый ответ.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    await message.answer("🤖 AI-анализ текущего скана запущен...")

    ai_result = await analyze_complaints(new_signals)
    for chunk in _send_chunks(ai_result):
        await message.answer(chunk)


async def _do_stats(message: types.Message) -> None:
    try:
        st = get_stats()
    except Exception as exc:
        logger.error("[Bot] Ошибка get_stats: %s", exc)
        await message.answer(f"❌ Ошибка чтения базы: {exc}")
        return

    lines = [
        "📊 Статистика Pain Radar\n",
        f"Сегодня: {st['today']} сигналов",
        f"За 7 дней: {st['week']} сигналов",
        f"За 30 дней: {st['month']} сигналов",
    ]

    if st["top_pains_week"]:
        lines += ["", "ТОП-10 болей за 7 дней:"]
        for i, (pain, cnt) in enumerate(st["top_pains_week"], 1):
            lines.append(f"  {i}. {pain} — {cnt}")

    if st["top_niches_week"]:
        lines += ["", "ТОП-10 ниш за 7 дней:"]
        for i, (niche, cnt) in enumerate(st["top_niches_week"], 1):
            lines.append(f"  {i}. {niche.capitalize()} — {cnt}")

    if st["top_cities_month"]:
        lines += ["", "ТОП-5 городов за 30 дней:"]
        for i, (city, cnt) in enumerate(st["top_cities_month"], 1):
            lines.append(f"  {i}. {city} — {cnt}")

    if st["month"] == 0:
        lines += ["", "База пуста. Нажмите 🔍 Сканировать для сбора данных."]

    await message.answer("\n".join(lines), reply_markup=MAIN_KEYBOARD)


async def _do_ai_history(message: types.Message, days: int, period: str) -> None:
    label = "7 дней" if days == 7 else "30 дней"
    await message.answer(
        f"🤖 Загружаю данные за {label} и запускаю AI-анализ...",
        reply_markup=MAIN_KEYBOARD,
    )

    try:
        signals = get_signals_since(days)
    except Exception as exc:
        logger.error("[Bot] Ошибка get_signals_since: %s", exc)
        await message.answer(f"❌ Ошибка чтения базы: {exc}")
        return

    if len(signals) < MIN_SIGNALS_FOR_AI:
        await message.answer(
            f"Пока мало данных за {label} ({len(signals)} сигналов).\n"
            "Нажмите 🔍 Сканировать несколько раз в разные дни — "
            "данные накопятся и AI-анализ станет точнее."
        )
        return

    logger.info("[Bot] AI history: %d signals for %s", len(signals), period)
    result = await analyze_history(signals, period)

    for chunk in _send_chunks(result):
        await message.answer(chunk)


async def main() -> None:
    logger.info("Запуск бота «Радар болей Самарской области»...")
    logger.info("Admin ID: %s", ADMIN_ID)
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
