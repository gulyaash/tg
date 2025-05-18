import os
import logging
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен читаем из переменных окружения
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# Хранилище логинов/паролей и предыдущих значений
user_credentials: dict[int, tuple[str, str]] = {}
last_counts: dict[int, int] = {}

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает /start."""
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает /set, сохраняет логин/пароль и запускает задачу."""
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) != 2:
        return await update.message.reply_text("Используйте: /set логин пароль")

    login, password = args
    user_credentials[chat_id] = (login, password)
    await update.message.reply_text("Данные сохранены! Проверка запущена каждые 60 секунд.")

    # запускаем или перезапускаем задачу
    # при повторном /set предыдущая отменится автоматически
    context.job_queue.run_repeating(
        check_messages,
        interval=60,
        first=0,
        data=chat_id,
        name=str(chat_id)  # уникально по chat_id
    )

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет сообщения по логину/паролю, присланным в /set."""
    chat_id = int(context.job.data)
    login, password = user_credentials.get(chat_id, (None, None))

    if not login or not password:
        # если нет данных — отменяем задачу и выходим
        context.job.schedule_removal()
        return

    try:
        # Здесь ваш код проверки через selenium или requests.
        # Приведу заглушку:
        # driver = webdriver.Chrome(options=Options().add_argument("--headless"))
        # ... логинимся, парсим ...
        #
        # count = ...  # новое значение
        #
        # if count != last_counts.get(chat_id):
        #     await context.bot.send_message(chat_id, f"Новое число: {count}")
        #     last_counts[chat_id] = count
        #
        raise RuntimeError("заглушка ошибки для примера")

    except Exception as e:
        logger.exception("Ошибка в check_messages")
        await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")

async def main():
    # собираем приложение
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # регистрируем хендлеры
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set", set_cmd))

    # запускаем long polling
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())