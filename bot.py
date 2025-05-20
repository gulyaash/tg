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
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ——— Логирование ———
logging.basicConfig(
    format="%(asctime)s %(levelname)s:%(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——— Токен из окружения ———
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не задан")
    exit(1)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id}\n"
        "Для запуска мониторинга введите:\n"
        "/set <логин> <пароль>"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        return await update.message.reply_text("Используйте: /set <логин> <пароль>")

    login, pwd = context.args
    chat_id = update.effective_chat.id

    # Отменяем предыдущие задачи для этого чата
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    # Запускаем новую задачу, передаём login/pwd/chat_id/last через context
    context.application.job_queue.run_repeating(
        check_messages,
        interval=60,
        first=5,
        name=str(chat_id),
        context={"login": login, "pwd": pwd, "chat_id": chat_id, "last": 0}
    )

    await update.message.reply_text("Данные сохранены! Мониторинг запущен (каждые 60 сек).")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logger.warning("Игнорируем Conflict при getUpdates")
    else:
        logger.error("Необработанная ошибка:", exc_info=context.error)

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    job_ctx = context.job.context
    login  = job_ctx["login"]
    pwd    = job_ctx["pwd"]
    chat_id= job_ctx["chat_id"]
    last   = job_ctx["last"]

    # Настройка headless Chrome
    opts = Options()
    opts.binary_location = "/usr/bin/chromium"
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=opts)

    try:
        # 1) Авторизация
        driver.get("https://cabinet.nf.uust.ru/")
        WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.ID, "login")))
        driver.find_element(By.ID, "login").send_keys(login)
        driver.find_element(By.ID, "password").send_keys(pwd)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(1)

        # 2) Переход в чат
        chat_url = "https://cabinet.nf.uust.ru/chat/index"
        driver.get(chat_url)
        logger.info(f"[{chat_id}] Перешли на {chat_url}")

        # 3) Ждём появления бейджей
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "span.badge.room-unread"))
        )
        spans = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")

        # 4) Считаем только видимые цифры
        count = 0
        for sp in spans:
            if not sp.is_displayed():
                continue
            txt = sp.text.strip()
            if txt.isdigit():
                count += int(txt)

        logger.info(f"[{chat_id}] Непрочитанных: {count} (предыдущее={last})")
        # 5) Только при появлении новых
        if count > last:
            await context.bot.send_message(
                chat_id,
                f"🔔 У вас {count-last} новых сообщений (всего {count})."
            )
            job_ctx["last"] = count

    except Exception:
        logger.exception("Ошибка при check_messages")
        await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")
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