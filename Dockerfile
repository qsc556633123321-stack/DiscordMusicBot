FROM python:3.11-slim

WORKDIR /app

# 安裝 FFmpeg，discord.py 會透過它播放語音串流。
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
