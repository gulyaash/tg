import os
import time
import threading
from dotenv import load_dotenv

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Подгружаем переменные из .env
load_dotenv()
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

# словарь chat_id → (login, password)
user_credentials: dict[str, tuple[str, str]] = {}
# словарь chat_id → {chat_name: last_count}
last_unread: dict[str, dict[str, int]] = {}

def send_telegram(chat_id: str, text: str):
    import requests
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id, "text": text})

def check_messages(login: str, password: str, chat_id: str):
    options = Options()
    # options.add_argument("--headless")  # раскомментируйте для невидимого режима
    driver = webdriver.Chrome(options=options)

    try:
        # 1) Логинимся
        driver.get("https://cabinet.nf.uust.ru")
        time.sleep(2)
        driver.find_element(By.ID, "login").send_keys(login)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.ID, "password").send_keys(Keys.RETURN)
        time.sleep(3)

        # 2) Открываем список конференций
        driver.get("https://cabinet.nf.uust.ru/chat/index")
        time.sleep(5)  # ждём подгрузки JS

        # 3) Снимаем текущее число непрочитанных по каждому чату
        badges = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        current: dict[str,int] = {}
        for b in badges:
            txt = b.text.strip()
            if txt.isdigit() and int(txt) > 0:
                name = b.find_element(By.XPATH, "./ancestor::a").text.replace(txt, "").strip()
                current[name] = int(txt)

    except Exception as e:
        print(f"[{chat_id}] Ошибка при проверке: {e}")
        driver.quit()
        return
    finally:
        driver.quit()

    # 4) Сравниваем с предыдущим состоянием и шлём только новые
    prev = last_unread.get(chat_id, {})
    last_unread[chat_id] = current

    if not prev:
        # первый запуск — инициализируем без уведомлений
        print(f"[{chat_id}] Инициализировано: {current}")
        return

    diffs = []
    for name, cnt in current.items():
        old = prev.get(name, 0)
        if cnt > old:
            diffs.append(f"{name}: +{cnt - old}")

    if diffs:
        send_telegram(chat_id, "🔔 Новые сообщения:\n" + "\n".join(diffs))
    else:
        print(f"[{chat_id}] Ничего нового")

# --- обработчик /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"Ваш chat_id: {cid}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234"
    )

# --- обработчик /set логин пароль ---
async def set_credentials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    cid = str(update.effective_chat.id)
    if len(args) != 2:
        return await update.message.reply_text("Используйте: /set логин пароль")
    user_credentials[cid] = (args[0], args[1])
    last_unread.pop(cid, None)  # сбрасываем старое состояние
    await update.message.reply_text("Данные сохранены! Проверка запущена каждые 60 секунд.")

# --- фоновая проверка ---
def background_loop():
    while True:
        for cid, (login, pwd) in user_credentials.items():
            check_messages(login, pwd, cid)
        time.sleep(60)

# --- точка входа ---
if __name__ == "__main__":
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_credentials))

    threading.Thread(target=background_loop, daemon=True).start()
    app.run_polling()