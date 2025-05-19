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

# ——— Логирование ———
logging.basicConfig(format="%(asctime)s %(levelname)s:%(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ——— Токен из окружения ———
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не задан")
    exit(1)

# ——— Состояния по chat_id ———
user_credentials: dict[int, tuple[str, str]] = {}
last_counts:       dict[int, int] = {}
error_sent:        dict[int, bool] = {}

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # очищаем старые задачи и данные
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

    # удаляем предыдущие задачи
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    # планируем новую задачу
    context.application.job_queue.run_repeating(
        callback=check_messages,
        interval=60,
        first=0,
        name=str(chat_id),
        data=chat_id
    )
    await update.message.reply_text("Данные сохранены! Проверка каждые 60 секунд.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        logger.warning("Игнорируем Conflict при getUpdates")
    else:
        logger.error("Необработанная ошибка:", exc_info=context.error)

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    creds = user_credentials.get(chat_id)
    if not creds:
        context.job.schedule_removal()
        return
    login, pwd = creds

    # headless Chrome
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
        WebDriverWait(driver, 15).until(EC.visibility_of_element_located((By.ID, "login")))
        driver.find_element(By.ID, "login").send_keys(login)
        driver.find_element(By.ID, "password").send_keys(pwd)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(1)

        # 2) Переходим в «Конференции»
        chat_url = "https://cabinet.nf.uust.ru/chat/index"
        driver.get(chat_url)
        logger.info(f"[{chat_id}] Зашли на {chat_url}")

        # 3) Собираем только видимые бейджи с непустым текстом
        WebDriverWait(driver, 15).until(
            EC.presence_of_all_elements_located(
                (By.XPATH, "//span[contains(@class,'badge') and normalize-space(string())!='']")
            )
        )
        elems = driver.find_elements(
            By.XPATH, "//span[contains(@class,'badge') and normalize-space(string())!='']"
        )
        count = 0
        for e in elems:
            if not e.is_displayed():
                continue
            txt = e.text.strip()
            if txt.isdigit():
                count += int(txt)
                logger.info(f"[{chat_id}] Непрочитанных в бейдже: {txt}")

        logger.info(f"[{chat_id}] Итоговое число непрочитанных: {count}")

        prev = last_counts.get(chat_id, 0)
        if count > prev:
            await context.bot.send_message(
                chat_id,
                f"🔔 У вас {count-prev} новых сообщений (всего {count})."
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