import os
import asyncio
import traceback
import tempfile
import uuid

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ------------  Настройка токена  ------------

# Если используете локально, создайте .env рядом и напишите в нём:
# TELEGRAM_TOKEN=ваш_токен
# а затем раскомментируйте:
# from dotenv import load_dotenv
# load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Переменная окружения TELEGRAM_TOKEN не задана")

# ------------  Память  ------------

# По chat_id храним { login, password, last_counts }
USER_CFG: dict[int, dict] = {}

# ------------  Обработчики  ------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id!r}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Используйте: /set логин пароль")
        return

    login, password = args
    USER_CFG[chat_id] = {
        "login": login,
        "password": password,
        "last_counts": {}
    }

    # Запускаем фоновую задачу (если она уже была — она переедет)
    context.job_queue.run_repeating(
        check_job,
        interval=60,
        first=0,
        chat_id=chat_id,
    )

    await update.message.reply_text(
        "Данные сохранены! Проверка запущена каждые 60 секунд."
    )

# ------------  Фонная задача  ------------

async def check_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    cfg = USER_CFG.get(chat_id)
    if not cfg:
        return

    try:
        new_counts = fetch_unread_counts(cfg["login"], cfg["password"])
        diffs = []
        total_new = 0

        for name, cnt in new_counts.items():
            prev = cfg["last_counts"].get(name, 0)
            if cnt > prev:
                diffs.append(f"{name}: {cnt - prev}")
                total_new += cnt - prev

        if diffs:
            text = f"🔔 У вас {total_new} новых сообщений:\n" + "\n".join(diffs)
            await context.bot.send_message(chat_id=chat_id, text=text)

        cfg["last_counts"] = new_counts

    except Exception:
        tb = traceback.format_exc()
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗ Ошибка при проверке:\n" + tb[:2000]
        )

# ------------  Selenium-логика  ------------

def fetch_unread_counts(login: str, password: str) -> dict[str, int]:
    """
    Логинимся и возвращаем {название_диалога: число_непрочитанных, ...}
    """

    # Собираем опции Chrome
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")

    # Уникальный каталог профиля, чтобы не было коллизий
    profile_dir = tempfile.mkdtemp(prefix="chrome-profile-")
    options.add_argument(f"--user-data-dir={profile_dir}")

    driver = webdriver.Chrome(options=options)
    try:
        # 1) Открываем страницу логина
        driver.get("https://cabinet.nf.ваш_домен/chat/index")

        # 2) Вводим логин/пароль и нажимаем кнопку
        driver.find_element(By.CSS_SELECTOR, "#login_input").send_keys(login)
        driver.find_element(By.CSS_SELECTOR, "#password_input").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "#login_button").click()

        # 3) Ждём загрузки списка чатов
        driver.implicitly_wait(10)
        # 4) Считываем непрочитанные
        badges = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        titles = driver.find_elements(By.CSS_SELECTOR, "a.room.nav-item")
        result: dict[str, int] = {}
        for title_el, badge_el in zip(titles, badges):
            name = title_el.text.strip()
            count = int(badge_el.text.strip())
            result[name] = count

        return result

    finally:
        driver.quit()

# ------------  Запуск бота  ------------

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_cmd))

    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())