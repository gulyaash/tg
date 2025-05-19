import os
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from webdriver_manager.chrome import ChromeDriverManager

# --- Логи для отладки HTTP/JobQueue ---
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# токен из переменных окружения
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# храним креденшиалы и последний count
user_credentials: dict[int, tuple[str, str]] = {}
last_counts: dict[int, int] = {}

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id}\n"
        f"Чтобы настроить бота: /set <login> <password>\n"
        f"Пример: /set abc_d 1234"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        await update.message.reply_text("Используйте: /set логин пароль")
        return

    login, pwd = context.args
    user_credentials[chat_id] = (login, pwd)
    last_counts[chat_id] = 0

    # запускаем проверку раз в минуту
    context.job_queue.run_repeating(
        check_messages,
        interval=60,
        first=5,
        name=str(chat_id),
        data=chat_id
    )
    await update.message.reply_text(
        "Данные сохранены! Проверка будет каждые 60 секунд."
    )

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    """Проверяем бейджи и приращиваем count"""
    job = context.job
    chat_id = job.data

    if chat_id not in user_credentials:
        return  # не настроен

    login, pwd = user_credentials[chat_id]

    # запускаем Selenium
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)

    try:
        # заходим в кабинет
        driver.get("https://cabinet.nf.uust.ru/login")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "username")))
        driver.find_element(By.NAME, "username").send_keys(login)
        driver.find_element(By.NAME, "password").send_keys(pwd)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()

        # ждём редиректа
        WebDriverWait(driver, 10).until(EC.url_contains("/dashboard"))

        # открываем чат-лист
        driver.get("https://cabinet.nf.uust.ru/chat/index")
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.room.nav-item")))

        # находим все бейджи
        spans = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        logger.info(f"[{chat_id}] Всего бейджей найдено: {len(spans)}")

        # считаем только видимые и с цифрой внутри
        count = 0
        for span in spans:
            if not span.is_displayed():
                continue
            text = span.text.strip()
            logger.info(f"[{chat_id}] бейдж текст = {repr(text)}")
            if text.isdigit():
                count += int(text)

        logger.info(f"[{chat_id}] Итоговое число непрочитанных: {count}")

        # если появилось больше, чем раньше — шлём уведомление
        if count > last_counts.get(chat_id, 0):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 У вас {count} непрочитанных сообщений!"
            )

        last_counts[chat_id] = count

    except Exception as e:
        logger.error(f"Ошибка в check_messages: {e}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text="Ошибка при проверке сообщений.")
    finally:
        driver.quit()
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set", set_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()