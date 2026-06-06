# Радар болей Самарской области

Telegram-бот для сканирования отзывов и жалоб жителей Самары и Тольятти. Находит повторяющиеся проблемы в малом бизнесе и предлагает идеи продуктов с помощью AI.

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и описание бота |
| `/status` | Статус бота и конфигурации |
| `/scan` | Запустить сканирование и AI-анализ болей |
| `/stats` | Статистика из базы |
| `/ai_week` | AI-анализ сигналов за 7 дней |
| `/ai_month` | AI-анализ сигналов за 30 дней |

## Стек

- Python 3.11
- [aiogram 3](https://docs.aiogram.dev/) — Telegram Bot API
- [aiohttp](https://docs.aiohttp.org/) — HTTP-клиент для OpenRouter
- [python-dotenv](https://pypi.org/project/python-dotenv/) — управление переменными окружения
- [APScheduler](https://apscheduler.readthedocs.io/) — планировщик задач

## Быстрый старт

```bash
# 1. Клонировать репозиторий
git clone <repo-url>
cd pain-radar-samara

# 2. Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Установить зависимости
pip install -r requirements.txt

# 4. Настроить переменные окружения
cp .env.example .env
# Заполнить .env своими значениями

# 5. Запустить бота
python3 bot.py
```

## Переменные окружения

Скопируй `.env.example` в `.env` и заполни:

```
TELEGRAM_BOT_TOKEN=  # Токен от @BotFather
TELEGRAM_ADMIN_ID=   # Ваш Telegram user ID
OPENROUTER_API_KEY=  # API ключ от openrouter.ai
```

## Архитектура

```
bot.py          — Telegram-бот, обработка команд
scanner.py      — Сканер отзывов, поиск болевых слов
ai_analyzer.py  — AI-анализ через OpenRouter (каскад моделей)
```

### Каскад AI-моделей

Если одна модель недоступна — автоматически переключается на следующую:

1. `openai/gpt-oss-120b:free`
2. `openai/gpt-oss-20b:free`
3. `nvidia/nemotron-3-super-120b-a12b:free`
4. `openrouter/free`

### Болевые слова для поиска

> дорого, долго, не дозвониться, хамство, обман, очередь, не перезвонили, нет записи, плохой сервис, не работает

### Охватываемые ниши

Автосервисы, стоматологии, ЖКХ, доставка, ремонт квартир, салоны красоты, банки, клиники.

## Деплой на Railway

Проект готов к деплою через [Railway](https://railway.app/). Настройки в `railway.json`.

Установи переменные окружения в Railway Dashboard и нажми Deploy.
