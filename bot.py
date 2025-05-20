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
    chat_id = update.effective_chat.id
    # очищаем всё старое для этого чата
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()
    await update.message.reply_text(
        f"Ваш chat_id: {chat_id}\n"
        "Для запуска мониторинга введите:\n"
        "/set <логин> <пароль>"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        return await update.message.reply_text("Используйте: /set <логин> <пароль>")
    login, pwd = context.args

    # создаём задачу, храня в data: (login, pwd, chat_id, last_count)
    context.application.job_queue.run_repeating(
        callback=check_messages,
        interval=60,
        first=5,
        name=str(chat_id),
        data={"login": login, "pwd": pwd, "chat_id": chat_id, "last": 0}
    )
    await update.message.reply_text("Данные сохранены! Мониторинг запущен (каждые 60 с).")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logger.warning("Игнорируем Conflict при getUpdates")
    else:
        logger.error("Необработанная ошибка:", exc_info=context.error)

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    login = job_data["login"]
    pwd   = job_data["pwd"]
    chat_id = job_data["chat_id"]
    last = job_data["last"]

    # Настройка headless Chrome (используем системный chromedriver из образа)
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

        # 2) Переход в раздел «Конференции»
        chat_url = "https://cabinet.nf.uust.ru/chat/index"
        driver.get(chat_url)
        logger.info(f"[{chat_id}] Открыл {chat_url}")

        # 3) Сбор бейджей непрочитанных
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "span.badge.room-unread"))
        )
        spans = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")

        count = 0
        for span in spans:
            if not span.is_displayed():
                continue
            txt = span.text.strip()
            if txt.isdigit():
                count += int(txt)

        logger.info(f"[{chat_id}] Найдено непрочитанных: {count} (предыдущее — {last})")
        # 4) Отправка уведомления только при увеличении
        if count > last:
            diff = count - last
            await context.bot.send_message(
                chat_id,
                f"🔔 У вас {diff} новых сообщений (всего {count})."
            )
            job_data["last"] = count  # обновляем в data

    except Exception:
        logger.exception("Ошибка в check_messages")
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