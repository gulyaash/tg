FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    chromium chromium-driver \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROME_DRIVER=/usr/bin/chromedriver
CMD ["python", "bot.py"]