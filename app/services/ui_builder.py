"""
UI builder for the Telegram bot.
Constructs message templates adapted for Pyrogram Userbot.
"""
from typing import Optional

from app.services.youtube_service import VideoInfo, PlaylistInfo, VideoFormat, AudioFormat
from app.utils.formatters import format_duration, format_size, truncate, format_progress_bar
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# ─── Message templates ─────────────────────────────────────────────────────────

def msg_welcome() -> str:
    return (
        "👋 **Welcome to YTGrabBot!**\n\n"
        "I can download YouTube videos and audio with a SnapTube-like experience.\n\n"
        "🔗 Just send me any YouTube link to get started.\n\n"
        "📋 **Supported formats:**\n"
        "• MP4 (144p → 1080p+)\n"
        "• MP3 / M4A audio only\n"
        "• Playlists (up to 50 videos)\n\n"
        "⚡ **Commands:**\n"
        "/start — Show this message\n"
        "/help — Detailed help\n"
        "/cancel — Cancel active download\n"
        "/stats — Your usage stats"
    )

def msg_help() -> str:
    return (
        "📖 **YTGrabBot Help**\n\n"
        "**How to use:**\n"
        "1. Paste any YouTube link\n"
        "2. Wait for the automatic high-quality download!\n\n"
        "**Supported links:**\n"
        "• `youtube.com/watch?v=…`\n"
        "• `youtu.be/…`\n"
        "• `youtube.com/shorts/…`\n"
        "• `youtube.com/playlist?list=…`\n\n"
        "**Limits:**\n"
        "• Max file size: 2000 MB (Userbot limit)\n"
        "• Max playlist: 50 videos\n"
        "• Rate limit: 5 requests per minute\n\n"
        "**Tips:**\n"
        "• We are using a 2GB limit to provide the highest quality possible!"
    )

def msg_fetching(url: str) -> str:
    return f"🔍 **Fetching video info…**\n\n`{url[:60]}{'…' if len(url) > 60 else ''}`"

def msg_video_info(info: VideoInfo) -> str:
    views = f"{info.view_count:,}" if info.view_count else "?"
    dur = format_duration(info.duration)
    title = info.title
    uploader = info.uploader
    return (
        f"🎬 **{title}**\n\n"
        f"👤 {uploader}\n"
        f"⏱ {dur}   👁 {views} views\n\n"
        f"⏳ **جاري التجهيز والتحميل بأعلى جودة...**"
    )

def msg_playlist_info(info: PlaylistInfo) -> str:
    title = info.title
    uploader = info.uploader
    return (
        f"📋 **{title}**\n\n"
        f"👤 {uploader}\n"
        f"🎞 {info.entry_count} videos\n\n"
        f"⏳ **جاري تحميل قائمة التشغيل...**"
    )

def msg_downloading(title: str, pct: float, speed_bytes: Optional[float], eta: Optional[int]) -> str:
    bar = format_progress_bar(pct)
    speed_str = ""
    if speed_bytes and speed_bytes > 0:
        if speed_bytes > 1024 * 1024:
            speed_str = f"⚡ {speed_bytes / 1024 / 1024:.1f} MB/s"
        else:
            speed_str = f"⚡ {speed_bytes / 1024:.0f} KB/s"
    eta_str = f"  ⏳ {eta}s" if eta else ""
    t = truncate(title, 50)
    return (
        f"📥 **Downloading…**\n"
        f"`{t}`\n\n"
        f"{bar}\n"
        f"{speed_str}{eta_str}"
    )

def msg_uploading(title: str) -> str:
    t = truncate(title, 50)
    return f"📤 **Uploading to Telegram (up to 2GB)…**\n`{t}`"

def msg_done(title: str) -> str:
    t = truncate(title, 50)
    return f"✅ **Done!** Enjoy your download 🎉\n`{t}`"

def msg_error(reason: str) -> str:
    r = reason[:200]
    return f"❌ **Error:** {r}\n\nPlease try again."

def msg_rate_limited(retry_after: float) -> str:
    return (
        f"⏳ **Slow down!**\n\n"
        f"You're sending requests too fast. Please wait **{int(retry_after)} seconds** and try again."
    )

def msg_file_too_large(filesize: int, max_mb: int) -> str:
    size_str = format_size(filesize)
    return (
        f"⚠️ **File too large**\n\n"
        f"This format is {size_str}, which exceeds the "
        f"**{max_mb}MB** upload limit.\n\n"
    )

def msg_live_not_supported() -> str:
    return "🔴 **Live streams are not supported**. Please try again after the stream ends."

def msg_playlist_downloading(done: int, total: int, title: str) -> str:
    pct = done / total * 100 if total else 0
    bar = format_progress_bar(pct)
    t = truncate(title, 40)
    return (
        f"📦 **Downloading playlist…**\n\n"
        f"{bar}\n"
        f"✅ {done}/{total} — `{t}`"
    )

# ─── Dummy functions to prevent import errors in other modules ────────────────

def kb_format_selector(*args, **kwargs):
    return None

def kb_playlist_menu(*args, **kwargs):
    return None

def kb_playlist_page(*args, **kwargs):
    return None

def kb_cancel(*args, **kwargs):
    return None

def kb_back(*args, **kwargs):
    return None

def _store_url(*args, **kwargs):
    return "dummy_url_key"

def _load_url(*args, **kwargs):
    return None
    
