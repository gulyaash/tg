import os
import time
import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# Включаем логирование, чтобы видеть HTTP-запросы и ошибки
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен берём из переменных окружения Railway
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не задан в переменных окружения")
    exit(1)

# Словарь { chat_id: (login, password) }
user_credentials: dict[int, tuple[str, str]] = {}
# Словарь { chat_id: last_unread_count }
last_counts: dict[int, int] = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — показывает chat_id и инструкцию."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Ваш chat_id: {chat_id}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234"
    )


async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /set — сохраняет логин/пароль и запускает периодическую проверку."""
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Используйте: /set <логин> <пароль>")
        return

    login, password = args
    user_credentials[chat_id] = (login, password)
    last_counts[chat_id] = 0

    # Запускаем задачу каждые 60 секунд
    context.job_queue.run_repeating(
        callback=check_messages,
        interval=60,
        first=0,
        data=chat_id
    )

    await update.message.reply_text("Данные сохранены! Проверка запускается каждые 60 секунд.")


async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    """Функция, которая лезет на сайт, считает бейджи и шлёт уведомления."""
    chat_id: int = context.job.data
    creds = user_credentials.get(chat_id)
    if not creds:
        return  # не настроено

    login, password = creds

    # Настраиваем headless Chrome
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get("https://cabinet.nf.ustu.ru/chat/index")

        # Логинимся
        driver.find_element(By.NAME, "username").send_keys(login)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        # Немного ждём загрузку
        time.sleep(2)

        # Собираем все бейджи непрочитанных
        elements = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        count = sum(int(el.text) for el in elements if el.text.isdigit())

        # Если стало больше, чем было
        if count > last_counts.get(chat_id, 0):
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"У вас {count} непрочитанных сообщений."
            )
            last_counts[chat_id] = count

    except Exception:
        logger.exception("Ошибка при проверке сообщений")
        await context.bot.send_message(chat_id=chat_id, text="Ошибка при проверке сообщений.")
    finally:
        driver.quit()


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Регистрируем команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_cmd))

    # Запускаем пуллинг (Railway держит контейнер живым)
    app.run_polling()