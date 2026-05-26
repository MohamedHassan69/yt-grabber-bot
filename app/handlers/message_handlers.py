"""
Message handler: receives text messages, detects YouTube URLs,
fetches video info, and automatically downloads the best format (Userbot mode).
"""
import os
from pyrogram import Client, types
from pyrogram.enums import ParseMode

from app.config import settings
from app.services.youtube_service import youtube_service
from app.services.ui_builder import (
    msg_fetching, msg_error, msg_rate_limited, msg_live_not_supported
)
from app.utils.url_validator import is_youtube_url, classify_url, URLType
from app.utils.rate_limiter import rate_limiter
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def handle_message(client: Client, message: types.Message) -> None:
    """Main handler for all non-command text messages."""
    if not message.text:
        return

    text = message.text.strip()
    user = message.from_user
    user_id = user.id if user else message.chat.id

    # ── Detect YouTube URL ────────────────────────────────────────────────────
    if not is_youtube_url(text):
        await message.reply_text(
            "🔗 Please send a valid YouTube URL.\n\n"
            "**Example:** `https://www.youtube.com/watch?v=dQw4w9WgXcQ`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Rate limiting ─────────────────────────────────────────────────────────
    allowed, retry_after = await rate_limiter.check(user_id)
    if not allowed:
        # Assuming msg_rate_limited returns a string; basic cleanup for Pyrogram Markdown
        msg = msg_rate_limited(retry_after).replace('\\.', '.').replace('\\-', '-')
        await message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    # ── Send "fetching" indicator ─────────────────────────────────────────────
    status_msg = await message.reply_text(
        "🔍 **جاري فحص الرابط وجلب البيانات...**",
        parse_mode=ParseMode.MARKDOWN,
    )

    # ── Classify URL ──────────────────────────────────────────────────────────
    url_type, url_id = classify_url(text)
    url = text  # use original input as yt-dlp handles normalisation

    try:
        if url_type in (URLType.PLAYLIST,):
            await _handle_playlist(client, message, status_msg, url)
        else:
            # VIDEO, SHORT, or UNKNOWN — try as video
            await _handle_video(client, message, status_msg, url)

    except Exception as e:
        logger.error(f"Error handling message from {user_id}: {e}", exc_info=True)
        err_text = str(e)
        if "Sign in to confirm" in err_text or "age" in err_text.lower():
            err_text = "This video requires sign-in or is age-restricted. (Cookies are working on it!)"
        elif "Private video" in err_text:
            err_text = "This video is private."
        elif "not available" in err_text.lower():
            err_text = "This video is not available."
        
        await status_msg.edit_text(
            f"❌ **Error:**\n`{err_text}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _handle_video(client: Client, message: types.Message, status_msg: types.Message, url: str) -> None:
    """Fetch video info and download best format for Userbot (2GB limit)."""
    info = await youtube_service.get_video_info(url)

    if info.is_live:
        await status_msg.edit_text(
            "❌ **Live streams are not supported.**",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not info.video_formats and not info.audio_formats:
        await status_msg.edit_text(
            "❌ **No downloadable formats found for this video.**",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Auto-select the best available video format (or audio if video isn't present)
    best_format = info.video_formats if info.video_formats else info.audio_formats
    resolution_label = getattr(best_format, 'resolution', 'Audio Only')

    await status_msg.edit_text(
        f"⏳ **جاري التحميل بأعلى جودة:**\n`{info.title}`\n\n_يرجى الانتظار، قد يستغرق الأمر بعض الوقت للأحجام الكبيرة..._",
        parse_mode=ParseMode.MARKDOWN
    )

    async def progress_callback(prog):
        # Throttle updates to ~15% increments to avoid Telegram flood limits
        if prog.status == "downloading" and prog.pct and int(prog.pct) % 15 == 0:
            try:
                await status_msg.edit_text(f"⏳ **جاري التحميل:** `{prog.pct:.1f}%`\n`{info.title}`")
            except:
                pass

    # Download the file
    file_path = await youtube_service.download(
        url=url,
        format_spec=best_format.format_id,
        ext=best_format.ext,
        on_progress=progress_callback
    )

    await status_msg.edit_text("⬆️ **جاري الرفع إلى تيليجرام (مفتوح حتى 2 جيجا)...**\n_قد يستغرق الرفع وقتاً حسب حجم الملف._")
    
    # Upload to Telegram using Pyrogram's large file support
    await client.send_video(
        chat_id=message.chat.id,
        video=str(file_path),
        caption=f"✅ **تم التحميل بنجاح**\n🎬 `{info.title}`\n📱 **الدقة:** `{resolution_label}`",
        supports_streaming=True
    )
    
    await status_msg.delete()
    
    # Clean up the file after successful upload
    try:
        os.remove(file_path)
    except Exception as e:
        logger.warning(f"Could not delete temp file {file_path}: {e}")


async def _handle_playlist(client: Client, message: types.Message, status_msg: types.Message, url: str) -> None:
    """Handle playlists by downloading videos sequentially."""
    info = await youtube_service.get_playlist_info(url)

    if info.entry_count == 0:
        await status_msg.edit_text(
            "❌ **This playlist appears to be empty or private.**",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await status_msg.edit_text(
        f"📑 **تم العثور على قائمة تشغيل:** `{info.title}`\n"
        f"🔢 **عدد الفيديوهات:** `{info.entry_count}`\n\n"
        f"⏳ _سيتم تحميلها تباعاً..._",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Limit to MAX_PLAYLIST_ITEMS to avoid overloading
    entries = info.entries[:settings.MAX_PLAYLIST_ITEMS]
    for idx, entry in enumerate(entries, 1):
        vid_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
        msg = await message.reply_text(f"⏳ جاري معالجة فيديو {idx} من {len(entries)}...")
        try:
            await _handle_video(client, message, msg, vid_url)
        except Exception as e:
            await msg.edit_text(f"❌ **فشل تحميل فيديو {idx}:**\n`{str(e)[:100]}`")
            
    await message.reply_text(f"✅ **تم الانتهاء من قائمة التشغيل:**\n`{info.title}`")
    
