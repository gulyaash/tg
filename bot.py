import os
import threading
import traceback
import time
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Читаем токен из env
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# Храним учётки и chat_id
# Format: {chat_id: (login, password)}
user_credentials: dict[int, tuple[str, str]] = {}

# Последнее число непрочитанных по каждому чату
last_unread: dict[int, dict[str,int]] = {}

def send_telegram(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})

async def start(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id, f"Ваш chat_id: {chat_id}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234")

async def set_credentials(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    try:
        login, pwd = context.args
    except ValueError:
        return await context.bot.send_message(chat_id, "Используйте: /set логин пароль")
    user_credentials[chat_id] = (login, pwd)
    last_unread[chat_id] = {}
    await context.bot.send_message(chat_id, "Данные сохранены! Проверка запускается каждые 60 секунд.")

def check_messages(login: str, password: str, chat_id: int):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    # уникальный user-data-dir, чтобы selenium не падал
    options.add_argument(f"--user-data-dir=/tmp/user{chat_id}")

    driver = webdriver.Chrome(options=options)
    driver.get("https://cabinet.nf.uust.ru/chat/index")
    # ждем список чатов
    WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.room.nav-item"))
    )
    # авторизуемся
    driver.find_element(By.NAME, "login").send_keys(login)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()

    # собираем все непрочитанные
    elems = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
    counts = {}
    for el in elems:
        cnt = int(el.text)
        # имя чата берём у родителя
        name = el.find_element(By.XPATH, "./ancestor::a").text.strip()
        counts[name] = cnt

    driver.quit()

    prev = last_unread.get(chat_id, {})
    diffs = []
    for name, cnt in counts.items():
        old = prev.get(name, 0)
        if cnt > old:
            diffs.append(f"{name}: {cnt-old}")
    last_unread[chat_id] = counts

    if diffs:
        text = "🔔 У вас новые сообщения:\n" + "\n".join(diffs)
        send_telegram(chat_id, text)

def background_loop():
    while True:
        for chat_id, (login, pwd) in user_credentials.items():
            try:
                check_messages(login, pwd, chat_id)
            except Exception:
                traceback.print_exc()
                send_telegram(chat_id, "Ошибка при проверке сообщений.")
        time.sleep(60)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_credentials))

    # Запускаем фон
    threading.Thread(target=background_loop, daemon=True).start()

    # Запускаем бота
    # drop_pending_updates по умолчанию = True
    app.run_polling()

if __name__ == "__main__":
    main()