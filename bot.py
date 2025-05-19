import os
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, filters

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Ваш chat_id: {update.effective_chat.id}\n"
        "Чтобы настроить бота, отправьте:\n"
        "/set <логин> <пароль>"
    )

async def set_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Используйте: /set логин пароль")
        return

    login, pwd = args
    chat_id = update.effective_chat.id
    # сохраняем куда-нибудь login/pwd/chat_id, например в dict в памяти
    context.chat_data["creds"] = (login, pwd, chat_id)
    # запускаем задачу проверки каждую минуту
    context.job_queue.run_repeating(check_messages, interval=60, first=0, data=chat_id)
    await update.message.reply_text("Данные сохранены! Проверка запущена каждые 60 секунд.")

async def check_messages(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    login, pwd, _ = context.chat_data.get("creds", (None, None, None))
    if not login:
        return

    try:
        # логинимся
        service = Service("/usr/bin/chromedriver")
        opts = webdriver.ChromeOptions()
        opts.add_argument("--headless")
        opts.add_argument("--no-sandbox")
        driver = webdriver.Chrome(service=service, options=opts)

        driver.get("https://cabinet.nf.uust.ru/")
        # ... дальше ваши шаги авторизации ...
        # затем проверяем таб чат
        driver.get("https://cabinet.nf.uust.ru/chat/index")

        # ждём, пока прогрузится DOM
        WebDriverWait(driver, 10).until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, "span.badge.room-unread")))
        badges = driver.find_elements(By.CSS_SELECTOR, "span.badge.room-unread.pull-right")
        count = 0
        for b in badges:
            text = b.get_attribute("textContent").strip()
            if text.isdigit():
                count += int(text)

        if count > 0:
            await context.bot.send_message(chat_id, f"Новых сообщений: {count}")
        driver.quit()

    except Exception as e:
        logging.exception("Ошибка в check_messages")
        await context.bot.send_message(chat_id, "Ошибка при проверке сообщений.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("set", set_cmd, filters=None))

    app.run_polling()

if __name__ == "__main__":
    main()