import os
import logging
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# включаем логи, чтобы видеть HTTP-запросы и ошибки
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# токен читаем из переменных окружения
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# хранилища логинов/паролей и предыдущих значений
user_credentials: dict[int, tuple[str, str]] = {}
last_counts: dict[int, int] = {}

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохраняет логин/пароль и запускает планировщик раз в 60 сек."""
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Используйте: /set <логин> <пароль>")
        return

    login, pwd = args
    chat_id = update.effective_chat.id
    user_credentials[chat_id] = (login, pwd)
    await update.message.reply_text("Данные сохранены! Проверка запущена каждые 60 секунд.")

    # отменим старую задачу, если была
    context.application.job_queue.stop()  # можно тоньше — удалять по идентификатору
    # запускаем новую задачу
    context.application.job_queue.run_repeating(
        check_messages,  # функция-колбэк
        interval=60,     # каждые 60 секунд
        first=0,         # сразу же отработать при установке
        data=chat_id     # передадим chat_id через job.data
    )

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    """Периодически вызывается планировщиком, проверяет новые сообщения."""
    chat_id = context.job.data
    creds = user_credentials.get(chat_id)
    if not creds:
        return

    login, pwd = creds
    try:
        # пример логики: Selenium + парсинг
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(options=options)

        driver.get("https://пример.сайт/авторизация")
        # ... ваш код авторизации:
        # driver.find_element(...).send_keys(login)
        # driver.find_element(...).send_keys(pwd)
        # driver.find_element(...).click()
        # driver.get("https://пример.сайт/входящие")
        # count = int(driver.find_element(...).text)

        # для примера, если не используете Selenium, можно так:
        # resp = requests.get(f"https://api.вашсайт.com/new_count?login={login}&pwd={pwd}")
        # resp.raise_for_status()
        # count = int(resp.json()["unread"])

        # заглушка:
        count = 0

        driver.quit()

        prev = last_counts.get(chat_id, 0)
        if count > prev:
            await context.bot.send_message(chat_id, f"У вас {count - prev} новых сообщений.")
        last_counts[chat_id] = count

    except Exception:
        logger.error("Ошибка при проверке сообщений:\n" + traceback.format_exc())
        await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set", set_cmd))

    app.run_polling()

if __name__ == "__main__":
    main()