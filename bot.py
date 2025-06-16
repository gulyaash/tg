import os
import time
import logging
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    JobQueue,
)

# Логирование
logging.basicConfig(
    format="%(asctime)s %(levelname)s:%(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка токена из .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не найден. Убедитесь, что он задан в .env")
    exit(1)

# Хранилища
user_credentials: dict[int, tuple[str, str]] = {}
last_counts: dict[int, int] = {}
error_sent: dict[int, bool] = {}

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    user_credentials.pop(chat_id, None)
    last_counts.pop(chat_id, None)
    error_sent.pop(chat_id, None)

    await update.message.reply_text(
        f"Ваш chat_id: {chat_id}\n"
        "Чтобы начать, отправьте:\n"
        "/set <логин> <пароль>"
    )

# Команда /set
async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        await update.message.reply_text("Формат: /set <логин> <пароль>")
        return
    login, password = context.args
    user_credentials[chat_id] = (login, password)
    last_counts[chat_id] = 0
    error_sent[chat_id] = False

    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    context.application.job_queue.run_repeating(
        check_messages,
        interval=60,
        first=0,
        name=str(chat_id),
        data=chat_id
    )

    await update.message.reply_text("Данные сохранены! Проверка каждые 60 секунд.")

# Проверка сообщений
async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    chat_id: int = context.job.data
    creds = user_credentials.get(chat_id)
    if not creds:
        return

    login, password = creds

    options = Options()
    options.binary_location = "/usr/bin/chromium"
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get("https://cabinet.nf.uust.ru")
        driver.find_element(By.ID, "login").send_keys(login)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(2)

        driver.get("https://cabinet.nf.uust.ru/chat/index")
        time.sleep(2)

        elems = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        count = sum(int(e.text) for e in elems if e.text.isdigit())

        prev = last_counts.get(chat_id, 0)
        if count > prev:
            await context.bot.send_message(
                chat_id,
                f"🔔 У вас {count - prev} новых сообщений (всего {count})."
            )
            last_counts[chat_id] = count
        error_sent[chat_id] = False

    except Exception:
        logger.exception("Ошибка в check_messages")
        if not error_sent.get(chat_id, False):
            await context.bot.send_message(chat_id, "⚠ Ошибка при проверке сообщений.")
            error_sent[chat_id] = True
    finally:
        driver.quit()

# Запуск бота
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_cmd))
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())