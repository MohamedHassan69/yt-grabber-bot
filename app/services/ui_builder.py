"""
UI builder for the Telegram bot.
Constructs all inline keyboards and message templates.
"""
import json
from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.services.youtube_service import VideoInfo, PlaylistInfo, VideoFormat, AudioFormat
from app.utils.formatters import format_duration, format_size, truncate, format_progress_bar
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# ─── Callback data prefix constants ───────────────────────────────────────────
CB_DL_VIDEO   = "dlv"   # download video:  dlv|format_id|ext|url_hash
CB_DL_AUDIO   = "dla"   # download audio:  dla|format_id|ext|url_hash
CB_PL_INFO    = "pli"   # playlist info:   pli|url_hash
CB_PL_DL_ONE  = "plo"   # pl download one: plo|idx|url_hash
CB_PL_DL_ALL  = "pla"   # pl download all: pla|url_hash
CB_PL_PAGE    = "plp"   # playlist page:   plp|page|url_hash
CB_BACK       = "back"  # back button:     back|url_hash
CB_CANCEL     = "cancel"

# URL hash → full URL mapping (held in bot_data)
URL_STORE_KEY = "url_store"


def _store_url(context, url: str) -> str:
    """Hash + store a URL in bot_data. Returns short key."""
    import hashlib
    key = hashlib.md5(url.encode()).hexdigest()[:10]
    store = context.bot_data.setdefault(URL_STORE_KEY, {})
    store[key] = url
    return key


def _load_url(context, key: str) -> Optional[str]:
    return context.bot_data.get(URL_STORE_KEY, {}).get(key)


# ─── Message templates ─────────────────────────────────────────────────────────

def msg_welcome() -> str:
    return (
        "👋 *Welcome to YTGrabBot\\!*\n\n"
        "I can download YouTube videos and audio with a SnapTube\\-like experience\\.\n\n"
        "🔗 Just send me any YouTube link to get started\\.\n\n"
        "📋 *Supported formats:*\n"
        "• MP4 \\(144p → 1080p\\+\\)\n"
        "• MP3 / M4A audio only\n"
        "• Playlists \\(up to 50 videos\\)\n\n"
        "⚡ *Commands:*\n"
        "/start — Show this message\n"
        "/help — Detailed help\n"
        "/cancel — Cancel active download\n"
        "/stats — Your usage stats"
    )


def msg_help() -> str:
    return (
        "📖 *YTGrabBot Help*\n\n"
        "*How to use:*\n"
        "1\\. Paste any YouTube link\n"
        "2\\. Choose your format from the menu\n"
        "3\\. Wait for the download\\!\n\n"
        "*Supported links:*\n"
        "• `youtube\\.com/watch?v=…`\n"
        "• `youtu\\.be/…`\n"
        "• `youtube\\.com/shorts/…`\n"
        "• `youtube\\.com/playlist?list=…`\n\n"
        "*Limits:*\n"
        "• Max file size: 45 MB \\(Telegram limit\\)\n"
        "• Max duration: 30 minutes\n"
        "• Max playlist: 50 videos\n"
        "• Rate limit: 5 requests per minute\n\n"
        "*Tips:*\n"
        "• Larger files may exceed Telegram's 50MB bot upload limit\\.\n"
        "• For very large files, use a direct download link instead\\."
    )


def msg_fetching(url: str) -> str:
    return f"🔍 *Fetching video info…*\n\n`{url[:60]}{'…' if len(url) > 60 else ''}`"


def msg_video_info(info: VideoInfo) -> str:
    views = f"{info.view_count:,}" if info.view_count else "?"
    dur = format_duration(info.duration)
    title = info.title.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")
    uploader = info.uploader.replace("*", "\\*")
    return (
        f"🎬 *{title}*\n\n"
        f"👤 {uploader}\n"
        f"⏱ {dur}   👁 {views} views\n\n"
        f"📥 *Choose a format to download:*"
    )


def msg_playlist_info(info: PlaylistInfo) -> str:
    title = info.title.replace("*", "\\*").replace("_", "\\_")
    uploader = info.uploader.replace("*", "\\*")
    return (
        f"📋 *{title}*\n\n"
        f"👤 {uploader}\n"
        f"🎞 {info.entry_count} videos\n\n"
        f"Choose an action:"
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
    t = truncate(title, 50).replace("*", "").replace("_", "")
    return (
        f"📥 *Downloading…*\n"
        f"`{t}`\n\n"
        f"{bar}\n"
        f"{speed_str}{eta_str}"
    )


def msg_uploading(title: str) -> str:
    t = truncate(title, 50).replace("*", "").replace("_", "")
    return f"📤 *Uploading to Telegram…*\n`{t}`"


def msg_done(title: str) -> str:
    t = truncate(title, 50).replace("*", "\\*").replace("_", "\\_")
    return f"✅ *Done\\!* Enjoy your download 🎉\n`{t}`"


def msg_error(reason: str) -> str:
    r = reason.replace("*", "\\*").replace("_", "\\_")[:200]
    return f"❌ *Error:* {r}\n\nPlease try again or use /cancel\\."


def msg_rate_limited(retry_after: float) -> str:
    return (
        f"⏳ *Slow down\\!*\n\n"
        f"You're sending requests too fast\\. Please wait *{int(retry_after)} seconds* and try again\\."
    )


def msg_file_too_large(filesize: int, max_mb: int) -> str:
    size_str = format_size(filesize).replace("~", "\\~")
    return (
        f"⚠️ *File too large*\n\n"
        f"This format is {size_str}, which exceeds the "
        f"*{max_mb}MB* Telegram upload limit\\.\n\n"
        f"Please choose a lower quality or audio\\-only option\\."
    )


def msg_live_not_supported() -> str:
    return "🔴 *Live streams are not supported*\\. Please try again after the stream ends\\."


def msg_playlist_downloading(done: int, total: int, title: str) -> str:
    pct = done / total * 100 if total else 0
    bar = format_progress_bar(pct)
    t = truncate(title, 40).replace("*", "").replace("_", "")
    return (
        f"📦 *Downloading playlist…*\n\n"
        f"{bar}\n"
        f"✅ {done}/{total} — `{t}`"
    )


# ─── Keyboard builders ─────────────────────────────────────────────────────────

def kb_format_selector(info: VideoInfo, context, url: str) -> InlineKeyboardMarkup:
    """Full format selection keyboard for a single video."""
    url_key = _store_url(context, url)
    rows: List[List[InlineKeyboardButton]] = []

    # ── Video section header ────
    if info.video_formats:
        rows.append([InlineKeyboardButton("── 📹 VIDEO ──", callback_data="noop")])
        for vf in info.video_formats[:8]:   # max 8 video options
            label = vf.label
            # Build format_spec: if video-only, merge with audio
            if vf.has_audio:
                spec = vf.format_id
            else:
                spec = f"{vf.format_id}+bestaudio/best"
            cb = f"{CB_DL_VIDEO}|{spec}|{vf.ext}|{url_key}"
            rows.append([InlineKeyboardButton(label, callback_data=cb)])

    # ── Audio section header ────
    if info.audio_formats:
        rows.append([InlineKeyboardButton("── 🎵 AUDIO ONLY ──", callback_data="noop")])
        audio_row = []
        for af in info.audio_formats:
            label = af.label
            cb = f"{CB_DL_AUDIO}|{af.format_id}|{af.ext}|{url_key}"
            audio_row.append(InlineKeyboardButton(label, callback_data=cb))
            if len(audio_row) == 2:
                rows.append(audio_row)
                audio_row = []
        if audio_row:
            rows.append(audio_row)

    # ── Cancel ─────────────────
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)])
    return InlineKeyboardMarkup(rows)


def kb_playlist_menu(info: PlaylistInfo, context, url: str) -> InlineKeyboardMarkup:
    """Playlist action keyboard."""
    url_key = _store_url(context, url)
    rows = [
        [
            InlineKeyboardButton(
                f"📥 Download All ({info.entry_count} videos)",
                callback_data=f"{CB_PL_DL_ALL}|{url_key}",
            )
        ],
        [
            InlineKeyboardButton(
                "🎵 Download All as MP3",
                callback_data=f"{CB_PL_DL_ALL}|{url_key}|mp3",
            )
        ],
        [
            InlineKeyboardButton(
                "📄 Browse & Pick Videos",
                callback_data=f"{CB_PL_PAGE}|0|{url_key}",
            )
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)],
    ]
    return InlineKeyboardMarkup(rows)


def kb_playlist_page(
    info: PlaylistInfo,
    context,
    url: str,
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Paged playlist browser keyboard."""
    url_key = _store_url(context, url)
    entries = info.entries
    start = page * page_size
    end = min(start + page_size, len(entries))
    rows = []

    for idx in range(start, end):
        entry = entries[idx]
        title = truncate(entry.get("title", f"Video {idx + 1}"), 35)
        rows.append([
            InlineKeyboardButton(
                f"{idx + 1}. {title}",
                callback_data=f"{CB_PL_DL_ONE}|{idx}|{url_key}",
            )
        ])

    # Pagination row
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀ Prev", callback_data=f"{CB_PL_PAGE}|{page - 1}|{url_key}"))
    total_pages = (len(entries) + page_size - 1) // page_size
    nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if end < len(entries):
        nav_row.append(InlineKeyboardButton("Next ▶", callback_data=f"{CB_PL_PAGE}|{page + 1}|{url_key}"))
    if nav_row:
        rows.append(nav_row)

    rows.append([
        InlineKeyboardButton("⬅ Back", callback_data=f"{CB_PL_INFO}|{url_key}"),
        InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL),
    ])
    return InlineKeyboardMarkup(rows)


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)]])


def kb_back(url_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Back to Formats", callback_data=f"{CB_BACK}|{url_key}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=CB_CANCEL)],
    ])
