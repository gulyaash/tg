import os
import logging
import traceback
import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ==== 1) Загрузка .env (только для локальной разработки) ====
load_dotenv()  # автоматически читает .env в корне проекта

# ==== 2) Токен из окружения ====
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']

# ==== 3) Логирование ====
logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    level=logging.INFO
)

# ==== 4) Хранилища состояний ====
user_credentials: dict[int, tuple[str, str]] = {}
last_counts:       dict[int, int] = {}
error_notified:    dict[int, bool] = {}


async def send_telegram(chat_id: int, text: str):
    """Простая обёртка вокруг sendMessage API."""
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    try:
        requests.post(url, data={'chat_id': chat_id, 'text': text})
    except Exception:
        logging.exception("Не смогли отправить Telegram-сообщение")


async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    """
    Еженоминутная задача: логинимся в кабинет,
    собираем общее число непрочитанных, сравниваем с прошлым,
    шлём уведомление или ошибку один раз.
    """
    chat_id = context.job.chat_id
    creds = user_credentials.get(chat_id)
    if creds is None:
        return  # ещё не настроено

    login, password = creds

    try:
        # === Настраиваем selenium ===
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        driver = webdriver.Chrome(options=options)

        # === Логинимся ===
        driver.get('https://cabinet.ni.ifnt.ru/chat/')
        # TODO: тут ваш код заполнения полей login/password и входа

        # === Считаем непрочитанные ===
        elems = driver.find_elements_by_css_selector('span.badge.room-unread.pull-right')
        counts = [int(e.text) for e in elems if e.text.isdigit()]
        total = sum(counts)

        prev = last_counts.get(chat_id)
        if prev is None or total != prev:
            if total > 0:
                # шлём уведомление с деталями
                msg = f"🔔 У вас {total} новых сообщений:\n"
                # Собрать подписи к каждому чату можно через соседние элементы DOM
                names = driver.find_elements_by_css_selector('a.room-name-selector')  # пример
                for name_el, cnt in zip(names, counts):
                    msg += f"{name_el.text}: {cnt}\n"
                await send_telegram(chat_id, msg)

            last_counts[chat_id] = total

        # Сброс флага ошибки, если всё прошло успешно
        error_notified[chat_id] = False

    except Exception:
        logging.exception("Ошибка при check_messages")
        # шлём сообщение об ошибке только один раз подряд
        if not error_notified.get(chat_id, False):
            await send_telegram(chat_id, "Ошибка при проверке сообщений.")
            error_notified[chat_id] = True

    finally:
        try:
            driver.quit()
        except:
            pass


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Ваш chat_id: {chat_id}\n"
        "Чтобы настроить бота — отправьте:\n"
        "/set <логин> <пароль>\n"
        "Пример: /set abc_d 1234"
    )


async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args or []
    if len(args) != 2:
        await update.message.reply_text("Используйте: /set <логин> <пароль>")
        return

    login, pwd = args
    user_credentials[chat_id] = (login, pwd)
    last_counts[chat_id] = None
    error_notified[chat_id] = False
    await update.message.reply_text(
        "Данные сохранены! Проверка запущена каждые 60 секунд."
    )
    # запускаем задачу в JobQueue
    context.job_queue.run_repeating(
        check_messages,
        interval=60,       # раз в 60 секунд
        first=0,           # сразу запустить
        chat_id=chat_id    # чтобы знать, для какого чата
    )


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set",   set_cmd))
    app.run_polling()


if __name__ == "__main__":
    main()