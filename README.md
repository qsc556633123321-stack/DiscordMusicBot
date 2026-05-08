# Discord 中文音樂機器人

這是一個簡易 Discord 音樂機器人，使用 `discord.py`、`yt-dlp` 和 `FFmpeg` 播放 YouTube 音訊。

目前版本保留單檔 `bot.py`，適合初學者閱讀，也可以部署到 Railway。

## 功能

- 中文指令與英文別名
- YouTube 網址或歌名搜尋播放
- 每個 Discord server 有獨立 queue
- 播放完一首歌後自動播放下一首
- 使用環境變數 `DISCORD_TOKEN`
- Dockerfile 會在雲端環境安裝 FFmpeg

## 指令

- `!加入` / `!join`：加入你所在的語音頻道
- `!播放 <YouTube網址或歌名>` / `!play <YouTube網址或歌名>`：播放音樂或加入歌單
- `!暫停` / `!pause`：暫停播放
- `!繼續` / `!resume`：繼續播放
- `!跳過` / `!skip`：跳過目前歌曲
- `!歌單` / `!queue`：查看目前歌單
- `!停止` / `!stop`：停止播放並清空歌單
- `!離開` / `!leave`：離開語音頻道
- `!幫助` / `!help`：顯示所有指令說明

## 本機執行

### 1. 安裝 Python 套件

```powershell
pip install -r requirements.txt
```

### 2. 建立 `.env`

可以參考 `.env.example`，建立 `.env`：

```env
DISCORD_TOKEN=你的DiscordBotToken
```

### 3. 安裝 FFmpeg

Windows 可以使用 winget：

```powershell
winget install Gyan.FFmpeg
```

安裝後重新開啟終端機，確認：

```powershell
ffmpeg -version
```

### 4. 啟動 Bot

```powershell
python bot.py
```

## Railway 部署

### 1. 準備 GitHub Repository

把專案推到 GitHub，至少需要包含：

- `bot.py`
- `requirements.txt`
- `Dockerfile`
- `.dockerignore`
- `.env.example`
- `README.md`

注意：不要把 `.env` 上傳到 GitHub。這個專案已經用 `.dockerignore` 避免 `.env` 被包進 Docker image，但仍建議你另外建立 `.gitignore` 排除 `.env`。

### 2. 在 Railway 建立專案

1. 打開 Railway
2. 選擇 `New Project`
3. 選擇 `Deploy from GitHub repo`
4. 選擇這個 Discord Bot repository
5. Railway 會偵測 `Dockerfile` 並使用 Docker 部署

### 3. 設定環境變數

到 Railway 專案的 Variables 頁面，新增：

```env
DISCORD_TOKEN=你的DiscordBotToken
```

`bot.py` 會使用：

```python
os.getenv("DISCORD_TOKEN")
```

所以 Railway 上不需要 `.env` 檔案。

### 4. 確認啟動指令

Dockerfile 已經設定啟動指令：

```dockerfile
CMD ["python", "bot.py"]
```

Railway 部署後會自動執行這個指令。

### 5. FFmpeg 設定

部署到 Railway 後，不能使用 Windows 本機路徑。Dockerfile 會安裝 FFmpeg，程式會使用：

```python
executable="ffmpeg"
```

播放設定仍保留 reconnect 參數，降低 YouTube 音訊串流中斷機率：

```python
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
```

## Discord Developer Portal 設定

請確認 Bot 已開啟：

- `MESSAGE CONTENT INTENT`

Bot 邀請到伺服器時，建議至少給以下權限：

- View Channels
- Send Messages
- Connect
- Speak

## 常見問題

### Railway 顯示找不到 DISCORD_TOKEN

請到 Railway 的 Variables 頁面確認是否已設定：

```env
DISCORD_TOKEN=你的DiscordBotToken
```

設定後請重新部署或重新啟動服務。

### Railway 顯示 ffmpeg was not found

請確認 Railway 使用的是本專案的 `Dockerfile` 部署，而且 Dockerfile 內有：

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
```

### Bot 上線但不能播放

請確認：

- Bot 有 `Connect` 和 `Speak` 權限
- 使用者和 Bot 在同一個語音頻道
- YouTube 網址或歌名可以正常搜尋
- `yt-dlp` 是最新版本

可以更新：

```powershell
pip install -U yt-dlp
```
