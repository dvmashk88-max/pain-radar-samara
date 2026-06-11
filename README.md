# Не Взлетит

Telegram-бот-антикоуч, который жёстко разбирает бизнес-идеи.

Пользователь присылает идею одним сообщением, а бот прогоняет её через трёх персонажей:

- 🎭 Подъёбщик — ищет самообман и слабые допущения
- ⚖️ Прокурор — бьёт по рынку, деньгам, конкуренции и рискам
- 😈 Адвокат — ищет единственный сценарий, при котором идея может выжить

В конце бот даёт короткий тест на выживание и вердикт:

- 🟢 Жива
- 🟡 Сомнительно
- 🔴 Пошла нахуй

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и примеры идей |
| `/help` | Как работает разбор |
| `/status` | Статус бота и ключевых переменных |

Любое обычное текстовое сообщение бот воспринимает как идею для разбора.

## Стек

- Python 3.11
- [aiogram 3](https://docs.aiogram.dev/) — Telegram Bot API
- [aiohttp](https://docs.aiohttp.org/) — HTTP-клиент для OpenRouter
- [python-dotenv](https://pypi.org/project/python-dotenv/) — управление переменными окружения
- OpenRouter — AI-анализ идей
- Railway — деплой

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

```bash
TELEGRAM_BOT_TOKEN=  # Токен от @BotFather
TELEGRAM_ADMIN_ID=   # Telegram user ID администратора
OPENROUTER_API_KEY=  # API ключ от openrouter.ai
```

## Архитектура

```text
bot.py          — Telegram-бот, команды и обработка идей
ai_analyzer.py  — разбор идей через OpenRouter
scanner.py      — старый сканер, сохранён в репозитории, но не используется в UI
database.py     — старая база сигналов, сохранена в репозитории, но не используется в UI
sources/        — старые источники, сохранены в репозитории, но не используются в UI
```

## Каскад AI-моделей

Если одна модель недоступна — бот автоматически переключается на следующую:

1. `openai/gpt-oss-120b:free`
2. `openai/gpt-oss-20b:free`
3. `nvidia/nemotron-3-super-120b-a12b:free`
4. `openrouter/free`

## Деплой на Railway

Проект готов к деплою через [Railway](https://railway.app/). Настройки находятся в `railway.json`.

Установи переменные окружения в Railway Dashboard и нажми Deploy. Команда запуска остаётся прежней:

```bash
python3 bot.py
```
