import os
import time
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Логи
logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не задан")
    exit(1)

user_credentials: dict[int, tuple[str, str]] = {}
last_counts: dict[int, int] = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) != 2:
        return await update.message.reply_text("Используйте: /set <логин> <пароль>")
    login, password = args
    user_credentials[chat_id] = (login, password)
    last_counts[chat_id] = 0

    # Планируем проверку раз в 60 секунд
    context.application.job_queue.run_repeating(
        check_messages,
        interval=60,
        first=0,
        name=str(chat_id),
        data=chat_id
    )
    await update.message.reply_text("Данные сохранены! Проверка каждые 60 секунд.")

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    creds = user_credentials.get(chat_id)
    if not creds:
        return
    login, password = creds

    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.get("https://cabinet.nf.uust.ru")
        driver.find_element(By.NAME, "login").send_keys(login)
        driver.find_element(By.NAME, "password").send_keys(password)
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
                f"У вас {count - prev} новых сообщений."
            )
            last_counts[chat_id] = count

    except Exception:
        logger.exception("Ошибка при проверке сообщений")
        await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")
    finally:
        driver.quit()

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()