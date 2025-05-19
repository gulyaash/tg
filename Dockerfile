FROM python:3.11-slim

# Устанавливаем Chromium и драйвер
RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Запуск бота
CMD ["python", "bot.py"]