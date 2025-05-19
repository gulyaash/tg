import os
import logging
import traceback
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ——— Настройка логов ———
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ——— Токен из окружения ———
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN не задана в окружении")
    exit(1)

# ——— Хранилища состояний ———
user_credentials: dict[int, tuple[str, str]] = {}
last_counts:       dict[int, int] = {}
ERROR_SENT:        dict[int, bool] = {}

CHECK_INTERVAL = 60  # секунд

def create_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=opts)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id,
        f"Ваш chat_id: {chat_id}\n"
        "Чтобы начать, отправьте:\n"
        "/set <логин> <пароль>"
    )
    # очистим старые задачи/статы
    user_credentials.pop(chat_id, None)
    last_counts.pop(chat_id, None)
    ERROR_SENT.pop(chat_id, None)
    # удаляем все job-и этого чата
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        return await context.bot.send_message(chat_id, "Используйте: /set <логин> <пароль>")
    login, pwd = context.args
    user_credentials[chat_id] = (login, pwd)
    last_counts[chat_id] = 0
    ERROR_SENT[chat_id] = False

    # удаляем предыдущие задачи
    for job in context.application.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()

    # запускаем новую задачу
    context.application.job_queue.run_repeating(
        callback=check_messages,
        interval=CHECK_INTERVAL,
        first=5,
        name=str(chat_id),
        data=chat_id
    )

    await context.bot.send_message(chat_id, f"Данные сохранены! Проверка раз в {CHECK_INTERVAL} сек.")

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    chat_id: int = context.job.data
    creds = user_credentials.get(chat_id)
    if not creds:
        # если нет creds — отменяем
        context.job.schedule_removal()
        return

    login, pwd = creds
    try:
        driver = create_driver()
        # --- Ваша логика авторизации и парсинга ---
        driver.get("https://cabinet.nf.uust.ru/chat/index")
        # driver.find_element(...).send_keys(login)
        # driver.find_element(...).send_keys(pwd)
        # driver.find_element(...).click()
        # далее находим бейджи с классом .badge.room-unread.pull-right
        elems = driver.find_elements("css selector", "span.badge.room-unread.pull-right")
        total = sum(int(e.text) for e in elems if e.text.isdigit())
        driver.quit()

        prev = last_counts.get(chat_id, 0)
        if total != prev:
            # только при изменении шлём
            if total > 0:
                await context.bot.send_message(
                    chat_id,
                    f"🔔 У вас {total} непрочитанных сообщений."
                )
            last_counts[chat_id] = total
        ERROR_SENT[chat_id] = False  # сброс флага ошибки

    except Exception as e:
        logger.exception("Ошибка в check_messages")
        if not ERROR_SENT.get(chat_id, False):
            await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")
            ERROR_SENT[chat_id] = True
        try:
            driver.quit()
        except:
            pass

def main():
    # создаём приложение
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    # регистрируем команды
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set",   set_cmd))

    # стартуем polling (собственно запускает цикл событий и не вылетает)
    app.run_polling()

if __name__ == "__main__":
    main()