import os
from dotenv import load_dotenv
load_dotenv()
import asyncio
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# 1) Простейшая настройка логирования
logging.basicConfig(
    format="%(asctime)s %(levelname)s:%(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — отвечает chat_id и подсказывает синтаксис /set."""
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id}\n"
        "Чтобы начать проверку, отправьте:\n"
        "/set <логин> <пароль>"
    )


async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /set — сохраняет логин/пароль и запускает задачу,
    которая каждую минуту вызывает check_messages().
    """
    if len(context.args) != 2:
        return await update.message.reply_text("Используйте: /set логин пароль")

    login, password = context.args
    chat_id = update.effective_chat.id

    # Cохраняем в chat_data
    context.chat_data["creds"] = (login, password)
    context.chat_data["last_count"] = 0

    # Удаляем предыдущую задачу (если была), чтобы не дублировать
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    # Регистрируем новую повторяющуюся задачу
    context.application.job_queue.run_repeating(
        check_messages,
        interval=60,           # каждые 60 секунд
        first=0,               # сразу после /set
        name=str(chat_id),     # имя задачи = chat_id
        chat_id=chat_id,       # куда шлём сообщения
    )

    await update.message.reply_text("Данные сохранены! Проверка запущена каждые 60 секунд.")


async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    """
    Функция-джоб: логинится на сайт, парсит бейджи и отправляет
    сообщение только если число непрочитанных увеличилось.
    """
    chat_id = context.job.chat_id

    creds = context.chat_data.get("creds")
    if not creds:
        # если логин/пароль не заданы — ничего не делаем
        return

    login, password = creds
    last_count = context.chat_data.get("last_count", 0)

    # Настраиваем headless Chrome
    chrome_opts = Options()
    chrome_opts.add_argument("--headless")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")

    # Берём автовыгружаемый chromedriver подходящей версии
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_opts)

    try:
        driver.get("https://cabinet.nf.uust.ru/")
        # ждём форму логина
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "username"))
        )
        driver.find_element(By.NAME, "username").send_keys(login)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()

        # ждём перехода в чат
        WebDriverWait(driver, 10).until(
            EC.url_contains("/chat/index")
        )

        # собираем все бейджи с числами
        badges = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        counts = [int(el.text) for el in badges if el.text.strip().isdigit()]
        total = sum(counts)

        # если новых > 0 — присылаем разницу
        if total > last_count:
            diff = total - last_count
            await context.bot.send_message(
                chat_id,
                f"Обнаружено новых сообщений: {diff}"
            )
            # сохраняем текущее значение
        context.chat_data["last_count"] = total

    except Exception as e:
        logger.exception("Ошибка при проверке сообщений")
        await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")
    finally:
        driver.quit()


async def main():
    # Токен берётся из переменной окружения TELEGRAM_TOKEN
    token = os.environ["TELEGRAM_TOKEN"]
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_cmd))

    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())