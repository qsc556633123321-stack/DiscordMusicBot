import asyncio
import os
from collections import deque
from urllib.parse import urlparse

import discord
from discord.ext import commands
from dotenv import load_dotenv
from yt_dlp import YoutubeDL


# 載入 .env 檔案中的環境變數
load_dotenv()


# 設定 Discord Bot 需要的權限
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True


# 建立 Bot，指令前綴使用 !
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# 儲存每個 Discord 伺服器的播放狀態
# 結構範例：
# guild_music_data = {
#     123456789: {
#         "queue": deque([...]),
#         "current": {...},
#         "current_song": {...},
#         "is_playing": False,
#         "idle_task": None
#     }
# }
guild_music_data = {}


def get_guild_data(guild_id: int) -> dict:
    """取得指定伺服器的音樂資料，如果沒有就建立新的。"""
    if guild_id not in guild_music_data:
        guild_music_data[guild_id] = {
            "queue": deque(),
            "current": None,
            "current_song": None,
            "is_playing": False,
            "idle_task": None,
            "last_text_channel": None,
            "manual_stop": False,
        }
    return guild_music_data[guild_id]


YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
}


FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


# Railway / Docker 內會透過 apt 安裝 ffmpeg，因此直接使用系統 PATH 裡的 ffmpeg。
FFMPEG_EXECUTABLE = "ffmpeg"


def is_youtube_url(query: str) -> bool:
    """判斷使用者輸入是否為 YouTube 影片網址，雲端版先不支援關鍵字搜尋。"""
    parsed_url = urlparse(query.strip())

    if parsed_url.scheme not in ("http", "https"):
        return False

    hostname = parsed_url.netloc.lower()
    return hostname == "youtu.be" or hostname == "youtube.com" or hostname.endswith(".youtube.com")


def cancel_idle_timer(guild_id: int) -> None:
    """取消指定伺服器的自動離開計時器。"""
    guild_data = get_guild_data(guild_id)
    idle_task = guild_data.get("idle_task")

    if idle_task and not idle_task.done():
        idle_task.cancel()

    guild_data["idle_task"] = None


async def auto_leave_after_idle(guild_id: int, text_channel: discord.abc.Messageable) -> None:
    """歌單播完後等待 5 分鐘，期間沒有新歌就自動離開語音頻道。"""
    try:
        await asyncio.sleep(300)

        guild = bot.get_guild(guild_id)
        guild_data = get_guild_data(guild_id)
        voice_client = guild.voice_client if guild else None

        if (
            voice_client is not None
            and not voice_client.is_playing()
            and not voice_client.is_paused()
            and not guild_data["queue"]
        ):
            guild_data["current"] = None
            guild_data["current_song"] = None
            guild_data["is_playing"] = False

            await voice_client.disconnect()
            await text_channel.send("歌單已播放完畢，5 分鐘內沒有新歌曲，已自動離開語音頻道")
    except asyncio.CancelledError:
        return
    finally:
        guild_data = get_guild_data(guild_id)
        if guild_data.get("idle_task") is asyncio.current_task():
            guild_data["idle_task"] = None


def start_idle_timer(guild: discord.Guild, text_channel: discord.abc.Messageable | None) -> None:
    """建立自動離開計時器，並避免同一個伺服器重複建立多個任務。"""
    if text_channel is None:
        return

    guild_data = get_guild_data(guild.id)
    idle_task = guild_data.get("idle_task")

    if idle_task and not idle_task.done():
        return

    guild_data["idle_task"] = asyncio.create_task(auto_leave_after_idle(guild.id, text_channel))


async def join_user_voice_channel(ctx: commands.Context) -> discord.VoiceClient | None:
    """讓 Bot 加入使用者所在的語音頻道。"""
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("你目前不在語音頻道，請先加入語音頻道。")
        return None

    user_channel = ctx.author.voice.channel
    voice_client = ctx.voice_client

    if voice_client is None:
        voice_client = await user_channel.connect()
    elif voice_client.channel != user_channel:
        await voice_client.move_to(user_channel)

    return voice_client


async def extract_song_info(query: str) -> dict:
    """用 yt-dlp 取得歌曲資訊。"""

    def _extract():
        with YoutubeDL(YTDL_OPTIONS) as ydl:
            info = ydl.extract_info(query, download=False)

            # 如果是搜尋結果，取第一筆
            if "entries" in info:
                info = info["entries"][0]

            return {
                "title": info.get("title", "未知標題"),
                "webpage_url": info.get("webpage_url", query),
                "stream_url": info["url"],
            }

    return await asyncio.to_thread(_extract)


async def play_next_song(guild: discord.Guild) -> None:
    """播放下一首歌；如果歌單空了就結束。"""
    guild_data = get_guild_data(guild.id)
    voice_client = guild.voice_client

    if voice_client is None:
        guild_data["is_playing"] = False
        guild_data["current"] = None
        guild_data["current_song"] = None
        return

    if not guild_data["queue"]:
        should_start_idle_timer = not guild_data["manual_stop"]
        idle_text_channel = guild_data["last_text_channel"]

        guild_data["is_playing"] = False
        guild_data["current"] = None
        guild_data["current_song"] = None
        guild_data["manual_stop"] = False

        if should_start_idle_timer:
            start_idle_timer(guild, idle_text_channel)

        return

    cancel_idle_timer(guild.id)

    song = guild_data["queue"].popleft()
    guild_data["current"] = song
    guild_data["current_song"] = song
    guild_data["is_playing"] = True
    guild_data["manual_stop"] = False
    guild_data["last_text_channel"] = song["request_channel"]

    audio_source = discord.FFmpegPCMAudio(
        song["stream_url"],
        executable=FFMPEG_EXECUTABLE,
        **FFMPEG_OPTIONS,
    )

    def after_playing(error):
        if error:
            print(f"播放時發生錯誤：{error}")

        future = asyncio.run_coroutine_threadsafe(play_next_song(guild), bot.loop)
        try:
            future.result()
        except Exception as exc:
            print(f"切換下一首時發生錯誤：{exc}")

    voice_client.play(audio_source, after=after_playing)

    text_channel = song["request_channel"]
    await text_channel.send(f"現在播放：**{song['title']}**\n{song['webpage_url']}")


@bot.event
async def on_ready():
    print(f"Bot 已上線：{bot.user}")


@bot.command(name="加入", aliases=["join"])
async def join_command(ctx: commands.Context):
    """加入使用者所在語音頻道。"""
    voice_client = await join_user_voice_channel(ctx)
    if voice_client is not None:
        await ctx.send(f"已加入語音頻道：**{voice_client.channel.name}**")


@bot.command(name="播放", aliases=["play"])
async def play_command(ctx: commands.Context, *, query: str | None = None):
    """播放音樂或加入歌單。"""
    if not query:
        await ctx.send("請輸入 YouTube 影片網址，例如：`!播放 https://www.youtube.com/watch?v=dQw4w9WgXcQ`")
        return

    query = query.strip()

    if not is_youtube_url(query):
        await ctx.send("目前雲端環境搜尋功能受 YouTube 限制，請直接貼上 YouTube 影片網址")
        return

    voice_client = await join_user_voice_channel(ctx)
    if voice_client is None:
        return

    guild_data = get_guild_data(ctx.guild.id)
    cancel_idle_timer(ctx.guild.id)

    await ctx.send("正在搜尋歌曲，請稍候...")

    try:
        song_info = await extract_song_info(query)
    except Exception as exc:
        await ctx.send(f"找不到歌曲或讀取失敗：{exc}")
        if not guild_data["queue"] and not voice_client.is_playing() and not voice_client.is_paused():
            start_idle_timer(ctx.guild, ctx.channel)
        return

    song_info["request_channel"] = ctx.channel
    song_info["requester"] = ctx.author.display_name
    guild_data["queue"].append(song_info)

    await ctx.send(f"已加入歌單：**{song_info['title']}**")

    # 如果目前沒有在播放，立刻開始播放
    if not voice_client.is_playing() and not voice_client.is_paused() and not guild_data["is_playing"]:
        await play_next_song(ctx.guild)


@bot.command(name="暫停", aliases=["pause"])
async def pause_command(ctx: commands.Context):
    """暫停目前播放的歌曲。"""
    voice_client = ctx.voice_client
    if voice_client is None or not voice_client.is_playing():
        await ctx.send("目前沒有正在播放的歌曲。")
        return

    voice_client.pause()
    await ctx.send("已暫停播放。")


@bot.command(name="繼續", aliases=["resume"])
async def resume_command(ctx: commands.Context):
    """繼續播放已暫停的歌曲。"""
    voice_client = ctx.voice_client
    if voice_client is None or not voice_client.is_paused():
        await ctx.send("目前沒有已暫停的歌曲。")
        return

    voice_client.resume()
    await ctx.send("已繼續播放。")


@bot.command(name="跳過", aliases=["skip"])
async def skip_command(ctx: commands.Context):
    """跳過目前歌曲。"""
    voice_client = ctx.voice_client
    if voice_client is None or (not voice_client.is_playing() and not voice_client.is_paused()):
        await ctx.send("目前沒有可以跳過的歌曲。")
        return

    voice_client.stop()
    await ctx.send("已跳過目前歌曲。")


@bot.command(name="歌單", aliases=["queue"])
async def queue_command(ctx: commands.Context):
    """顯示目前歌單。"""
    guild_data = get_guild_data(ctx.guild.id)
    current_song = guild_data["current"]
    queue_list = list(guild_data["queue"])

    lines = []

    if current_song:
        lines.append(f"正在播放：1. {current_song['title']}")
    else:
        lines.append("正在播放：目前沒有歌曲")

    if queue_list:
        lines.append("")
        lines.append("接下來的歌單：")
        for index, song in enumerate(queue_list, start=1):
            lines.append(f"{index}. {song['title']}")
    else:
        lines.append("")
        lines.append("目前歌單是空的。")

    await ctx.send("\n".join(lines))


@bot.command(name="正在播放", aliases=["nowplaying", "np"])
async def now_playing_command(ctx: commands.Context):
    """顯示目前正在播放的歌曲。"""
    guild_data = get_guild_data(ctx.guild.id)
    current_song = guild_data["current_song"]

    if current_song is None:
        await ctx.send("目前沒有正在播放的歌曲")
        return

    requester = current_song.get("requester", "未知")
    await ctx.send(
        "目前正在播放：\n"
        f"歌名：**{current_song['title']}**\n"
        f"網址：{current_song['webpage_url']}\n"
        f"點歌者：{requester}"
    )


@bot.command(name="停止", aliases=["stop"])
async def stop_command(ctx: commands.Context):
    """停止播放並清空歌單。"""
    voice_client = ctx.voice_client
    guild_data = get_guild_data(ctx.guild.id)
    cancel_idle_timer(ctx.guild.id)

    guild_data["queue"].clear()
    guild_data["current"] = None
    guild_data["current_song"] = None
    guild_data["is_playing"] = False
    guild_data["manual_stop"] = True

    if voice_client is not None and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()

    await ctx.send("已停止播放並清空歌單。")


@bot.command(name="離開", aliases=["leave"])
async def leave_command(ctx: commands.Context):
    """離開語音頻道。"""
    voice_client = ctx.voice_client
    if voice_client is None:
        await ctx.send("Bot 目前不在任何語音頻道。")
        return

    guild_data = get_guild_data(ctx.guild.id)
    cancel_idle_timer(ctx.guild.id)

    guild_data["queue"].clear()
    guild_data["current"] = None
    guild_data["current_song"] = None
    guild_data["is_playing"] = False
    guild_data["manual_stop"] = True

    await voice_client.disconnect()
    await ctx.send("已離開語音頻道。")


@bot.command(name="幫助", aliases=["help"])
async def help_command(ctx: commands.Context):
    """顯示所有指令說明。"""
    help_text = (
        "可用指令如下：\n"
        "`!加入` / `!join`：加入你所在的語音頻道\n"
        "`!播放 <YouTube網址>` / `!play <YouTube網址>`：播放音樂或加入歌單\n"
        "`!暫停` / `!pause`：暫停播放\n"
        "`!繼續` / `!resume`：繼續播放\n"
        "`!跳過` / `!skip`：跳過目前歌曲\n"
        "`!歌單` / `!queue`：查看目前歌單\n"
        "`!正在播放` / `!nowplaying` / `!np`：查看目前正在播放的歌曲\n"
        "`!停止` / `!stop`：停止播放並清空歌單\n"
        "`!離開` / `!leave`：離開語音頻道\n"
        "`!幫助` / `!help`：顯示這份說明"
    )
    await ctx.send(help_text)


def main():
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        raise ValueError("找不到 DISCORD_TOKEN，請先在 .env 檔案中設定。")

    bot.run(token)


if __name__ == "__main__":
    main()
