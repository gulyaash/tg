import os
import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import requests

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
user_credentials: dict[int, tuple[str, str]] = {}


async def send_telegram(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})


def check_messages(login: str, password: str, chat_id: int) -> None:
    """
    Открываем ЛК, забираем бейджи с непрочитанными сообщениями
    и шлём их в Telegram.
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # Вот здесь — даём каждому запуску свой каталог данных:
    profile_dir = f"/tmp/selenium_profile_{chat_id}"
    options.add_argument(f"--user-data-dir={profile_dir}")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get("https://cabinet.nf.uust.ru/login")
        driver.find_element(By.ID, "login").send_keys(login)
        driver.find_element(By.ID, "password").send_keys(password + Keys.RETURN)

        WebDriverWait(driver, 10).until(EC.url_contains("/chat/index"))

        badges = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        if not badges:
            return

        text = f"🔔 У вас {len(badges)} новых сообщений:\n"
        for b in badges:
            parent = b.find_element(By.XPATH, "../..")
            title = parent.find_element(By.CSS_SELECTOR, "a").text.strip()
            cnt = b.text.strip()
            text += f"{title}: {cnt}\n"

        asyncio.run(send_telegram(chat_id, text))
    finally:
        driver.quit()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Ваш chat_id: {chat_id}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234"
    )


async def set_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        await update.message.reply_text("Используйте: /set <логин> <пароль>")
        return

    login, pwd = context.args
    user_credentials[chat_id] = (login, pwd)
    await update.message.reply_text("Данные сохранены! Проверка запущена каждые 60 секунд.")

    # Планируем периодическую задачу
    context.job_queue.run_repeating(
        lambda ctx: check_messages(login, pwd, chat_id),
        interval=60,
        first=0,
        name=str(chat_id),
    )


def main() -> None:
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .drop_pending_updates(True)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_credentials))

    app.run_polling()


if  __name__ == "__main__":
    main()