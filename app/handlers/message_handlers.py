"""
Message handler: receives text messages, detects YouTube URLs,
fetches video/playlist info, and presents the format selection menu.
"""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from app.config import settings
from app.services.youtube_service import youtube_service
from app.services.ui_builder import (
    msg_fetching, msg_video_info, msg_playlist_info,
    msg_error, msg_rate_limited, msg_live_not_supported,
    kb_format_selector, kb_playlist_menu,
    _store_url,
)
from app.utils.url_validator import is_youtube_url, classify_url, URLType
from app.utils.rate_limiter import rate_limiter
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main handler for all non-command text messages."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.effective_user

    # ── Detect YouTube URL ────────────────────────────────────────────────────
    if not is_youtube_url(text):
        await update.message.reply_text(
            "🔗 Please send a valid YouTube URL\\.\n\n"
            "_Example:_ `https://www\\.youtube\\.com/watch?v=dQw4w9WgXcQ`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # ── Rate limiting ─────────────────────────────────────────────────────────
    allowed, retry_after = await rate_limiter.check(user.id)
    if not allowed:
        await update.message.reply_text(
            msg_rate_limited(retry_after),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # ── Send "fetching" indicator ─────────────────────────────────────────────
    status_msg = await update.message.reply_text(
        msg_fetching(text),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    # ── Classify URL ──────────────────────────────────────────────────────────
    url_type, url_id = classify_url(text)
    url = text  # use original input as yt-dlp handles normalisation

    try:
        if url_type in (URLType.PLAYLIST,):
            await _handle_playlist(update, context, status_msg, url)
        else:
            # VIDEO, SHORT, or UNKNOWN — try as video
            await _handle_video(update, context, status_msg, url)

    except Exception as e:
        logger.error(f"Error handling message from {user.id}: {e}", exc_info=True)
        err_text = str(e)
        if "Sign in to confirm" in err_text or "age" in err_text.lower():
            err_text = "This video requires sign-in or is age-restricted."
        elif "Private video" in err_text:
            err_text = "This video is private."
        elif "not available" in err_text.lower():
            err_text = "This video is not available."
        await status_msg.edit_text(
            msg_error(err_text),
            parse_mode=ParseMode.MARKDOWN_V2,
        )


async def _handle_video(update, context, status_msg, url: str) -> None:
    """Fetch video info and show format keyboard."""
    info = await youtube_service.get_video_info(url)

    if info.is_live:
        await status_msg.edit_text(
            msg_live_not_supported(),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if not info.video_formats and not info.audio_formats:
        await status_msg.edit_text(
            msg_error("No downloadable formats found for this video."),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Store info in user_data for callback use
    context.user_data["current_info"] = info
    context.user_data["current_url"] = url

    keyboard = kb_format_selector(info, context, url)
    await status_msg.edit_text(
        msg_video_info(info),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )
    logger.info(
        f"Showed {len(info.video_formats)} video + {len(info.audio_formats)} audio "
        f"formats for {info.title[:40]}"
    )


async def _handle_playlist(update, context, status_msg, url: str) -> None:
    """Fetch playlist info and show playlist menu."""
    info = await youtube_service.get_playlist_info(url)

    if info.entry_count == 0:
        await status_msg.edit_text(
            msg_error("This playlist appears to be empty or private."),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    context.user_data["current_playlist"] = info
    context.user_data["current_url"] = url

    keyboard = kb_playlist_menu(info, context, url)
    await status_msg.edit_text(
        msg_playlist_info(info),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )
    logger.info(f"Showed playlist: {info.title} ({info.entry_count} videos)")
