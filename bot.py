import os
import time
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ——— Настройка логов ———
logging.basicConfig(
    format="%(asctime)s %(levelname)s:%(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не задан в окружении")
    exit(1)

# По chat_id храним (login, password)
user_credentials: dict[int, tuple[str, str]] = {}
# По chat_id храним последнее число непрочитанных
last_counts: dict[int, int] = {}
# Флаг, чтобы не спамить ошибками
error_sent: dict[int, bool] = {}

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # очистка
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    user_credentials.pop(chat_id, None)
    last_counts.pop(chat_id, None)
    error_sent.pop(chat_id, None)

    await update.message.reply_text(
        f"Ваш chat_id: {chat_id}\n"
        "Чтобы запустить мониторинг, отправьте:\n"
        "/set <логин> <пароль>"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        return await update.message.reply_text("Используйте: /set <логин> <пароль>")
    login, pwd = context.args
    user_credentials[chat_id] = (login, pwd)
    last_counts[chat_id] = 0
    error_sent[chat_id] = False

    # отменяем старые задачи
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    # ставим новую задачу
    context.application.job_queue.run_repeating(
        callback=check_messages,
        interval=60,
        first=0,
        name=str(chat_id),
        data=chat_id
    )
    await update.message.reply_text("Данные приняты, проверка каждые 60 секунд.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    # подавляем Telegram-409 Conflict
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logger.warning("Игнорируем Conflict от getUpdates")
    else:
        logger.error("Необработанная ошибка:", exc_info=context.error)

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    chat_id: int = context.job.data
    creds = user_credentials.get(chat_id)
    if not creds:
        context.job.schedule_removal()
        return
    login, pwd = creds

    # настройка Chromium
    opts = Options()
    opts.binary_location = "/usr/bin/chromium"
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=opts)

    try:
        # 1) авторизация
        driver.get("https://cabinet.nf.uust.ru/")
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "login")))
        driver.find_element(By.ID, "login").send_keys(login)
        driver.find_element(By.ID, "password").send_keys(pwd)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        # 2) дождаться перехода в чат
        WebDriverWait(driver, 10).until(EC.url_contains("/chat/index"))
        logger.info(f"[{chat_id}] Успешный вход, URL: {driver.current_url}")

        # 3) считываем бейджи
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
            )
        )
        elems = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        count = sum(int(e.text) for e in elems if e.text.isdigit())
        logger.info(f"[{chat_id}] Найдено бейджей: {len(elems)}, count={count}")

        prev = last_counts.get(chat_id, 0)
        if count > prev:
            diff = count - prev
            await context.bot.send_message(
                chat_id,
                f"🔔 У вас {diff} новых сообщений (всего {count})."
            )
            last_counts[chat_id] = count
        error_sent[chat_id] = False

    except Exception:
        logger.exception("Ошибка в check_messages")
        if not error_sent.get(chat_id, False):
            await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")
            error_sent[chat_id] = True

    finally:
        driver.quit()

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set",   set_cmd))
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == "__main__":
    main()