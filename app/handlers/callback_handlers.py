"""
Callback query handler for all inline keyboard button presses.
Handles format selection, download initiation, playlist navigation,
progress reporting, and file uploading to Telegram.
"""
import asyncio
import uuid
from pathlib import Path
from typing import Optional

from telegram import Update, Message
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut

from app.config import settings
from app.services.youtube_service import youtube_service, DownloadProgress
from app.services.queue_service import download_queue, DownloadJob, JobStatus
from app.services.cleanup_service import cleanup_service
from app.services.ui_builder import (
    CB_DL_VIDEO, CB_DL_AUDIO, CB_PL_INFO, CB_PL_DL_ONE,
    CB_PL_DL_ALL, CB_PL_PAGE, CB_BACK, CB_CANCEL,
    msg_downloading, msg_uploading, msg_done, msg_error,
    msg_video_info, msg_playlist_info, msg_file_too_large,
    kb_format_selector, kb_playlist_menu, kb_playlist_page, kb_cancel,
    _load_url,
)
from app.utils.formatters import format_size, format_duration, truncate
from app.utils.rate_limiter import rate_limiter
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route all callback queries to the appropriate handler."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "noop":
        return
    if data == CB_CANCEL:
        await _handle_cancel(query, context)
        return

    parts = data.split("|")
    prefix = parts[0]

    try:
        if prefix == CB_DL_VIDEO:
            await _handle_download(query, context, parts, is_audio=False)
        elif prefix == CB_DL_AUDIO:
            await _handle_download(query, context, parts, is_audio=True)
        elif prefix == CB_PL_INFO:
            await _handle_playlist_back(query, context, parts)
        elif prefix == CB_PL_PAGE:
            await _handle_playlist_page(query, context, parts)
        elif prefix == CB_PL_DL_ONE:
            await _handle_playlist_download_one(query, context, parts)
        elif prefix == CB_PL_DL_ALL:
            await _handle_playlist_download_all(query, context, parts)
        elif prefix == CB_BACK:
            await _handle_back(query, context, parts)
        else:
            await query.edit_message_text("❓ Unknown action.")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass  # harmless
        else:
            logger.warning(f"BadRequest in callback: {e}")
    except Exception as e:
        logger.error(f"Callback handler error: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                msg_error(str(e)[:200]),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            pass


# ─── Download flow ─────────────────────────────────────────────────────────────

async def _handle_download(query, context, parts: list, is_audio: bool) -> None:
    """Initiate a single video/audio download."""
    # parts: [prefix, format_spec_or_id, ext, url_key]
    if len(parts) < 4:
        await query.edit_message_text(msg_error("Malformed download request."), parse_mode=ParseMode.MARKDOWN_V2)
        return

    _, format_spec, ext, url_key = parts[0], parts[1], parts[2], parts[3]
    url = _load_url(context, url_key)
    if not url:
        await query.edit_message_text(msg_error("Session expired. Please send the link again."), parse_mode=ParseMode.MARKDOWN_V2)
        return

    user = query.from_user

    # Rate limit check
    allowed, retry_after = await rate_limiter.check(user.id)
    if not allowed:
        from app.services.ui_builder import msg_rate_limited
        await query.edit_message_text(msg_rate_limited(retry_after), parse_mode=ParseMode.MARKDOWN_V2)
        return

    # Get video info to validate size
    info = context.user_data.get("current_info")
    if not info:
        try:
            info = await youtube_service.get_video_info(url)
            context.user_data["current_info"] = info
        except Exception as e:
            await query.edit_message_text(msg_error(str(e)), parse_mode=ParseMode.MARKDOWN_V2)
            return

    title = info.title

    # Show initial downloading message
    try:
        await query.edit_message_text(
            msg_downloading(title, 0, None, None),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except BadRequest:
        pass

    status_msg: Message = query.message

    # Progress update callback (throttled by youtube_service already)
    async def on_progress(prog: DownloadProgress):
        if prog.status == "downloading":
            try:
                await status_msg.edit_text(
                    msg_downloading(title, prog.pct, prog.speed, prog.eta),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except (BadRequest, TimedOut):
                pass
        elif prog.status == "finished":
            try:
                await status_msg.edit_text(
                    msg_uploading(title),
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except (BadRequest, TimedOut):
                pass

    job_id = uuid.uuid4().hex[:8]
    done_event = asyncio.Event()
    result_holder = {"path": None, "error": None}

    async def on_done(job: DownloadJob):
        result_holder["path"] = job.result_path
        done_event.set()

    async def on_error(job: DownloadJob):
        result_holder["error"] = job.error
        done_event.set()

    job = DownloadJob(
        job_id=job_id,
        user_id=user.id,
        url=url,
        format_spec=format_spec,
        ext=ext,
        on_progress=on_progress,
        on_done=on_done,
        on_error=on_error,
    )

    await download_queue.enqueue(job)

    # Start worker if not running
    await download_queue.start()

    # Wait for job to complete (with timeout)
    try:
        await asyncio.wait_for(done_event.wait(), timeout=600)  # 10 min max
    except asyncio.TimeoutError:
        download_queue.cancel_user_jobs(user.id)
        await status_msg.edit_text(
            msg_error("Download timed out. Please try a smaller file."),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if result_holder["error"]:
        await status_msg.edit_text(
            msg_error(result_holder["error"]),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    file_path: Path = result_holder["path"]
    if not file_path or not file_path.exists():
        await status_msg.edit_text(
            msg_error("Download completed but file not found."),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Check file size against Telegram limit
    file_size = file_path.stat().st_size
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        await cleanup_service.clean_file(file_path)
        await status_msg.edit_text(
            msg_file_too_large(file_size, settings.MAX_FILE_SIZE_MB),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Upload to Telegram
    await status_msg.edit_text(msg_uploading(title), parse_mode=ParseMode.MARKDOWN_V2)
    await _upload_file(query, context, file_path, title, ext, is_audio, info)

    # Delete status message, clean up file
    try:
        await status_msg.delete()
    except Exception:
        pass
    asyncio.create_task(cleanup_service.clean_file(file_path, delay=60))


async def _upload_file(
    query, context, file_path: Path, title: str, ext: str,
    is_audio: bool, info
) -> None:
    """Upload downloaded file to Telegram with caption."""
    chat_id = query.message.chat_id
    caption = (
        f"🎬 *{truncate(title, 50)}*\n"
        f"⏱ {format_duration(info.duration)} · 👤 {truncate(info.uploader, 30)}\n"
        f"📦 {format_size(file_path.stat().st_size)}"
    )

    try:
        with open(file_path, "rb") as f:
            if is_audio or ext in ("mp3", "m4a", "opus"):
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    title=truncate(title, 64),
                    performer=truncate(info.uploader, 64),
                    duration=info.duration,
                    read_timeout=120,
                    write_timeout=120,
                )
            else:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    duration=info.duration,
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )
        logger.info(f"Uploaded {file_path.name} to chat {chat_id}")
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg_error(f"Upload failed: {str(e)[:100]}"),
            parse_mode=ParseMode.MARKDOWN_V2,
        )


# ─── Playlist handlers ─────────────────────────────────────────────────────────

async def _handle_playlist_back(query, context, parts: list) -> None:
    """Show playlist menu again."""
    url_key = parts[1] if len(parts) > 1 else None
    url = _load_url(context, url_key) if url_key else None
    info = context.user_data.get("current_playlist")
    if not info or not url:
        await query.edit_message_text(msg_error("Session expired."), parse_mode=ParseMode.MARKDOWN_V2)
        return
    keyboard = kb_playlist_menu(info, context, url)
    await query.edit_message_text(
        msg_playlist_info(info),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )


async def _handle_playlist_page(query, context, parts: list) -> None:
    """Show a page of the playlist browser."""
    _, page_str, url_key = parts[0], parts[1], parts[2]
    page = int(page_str)
    url = _load_url(context, url_key)
    info = context.user_data.get("current_playlist")
    if not info or not url:
        await query.edit_message_text(msg_error("Session expired."), parse_mode=ParseMode.MARKDOWN_V2)
        return
    keyboard = kb_playlist_page(info, context, url, page)
    await query.edit_message_text(
        msg_playlist_info(info),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )


async def _handle_playlist_download_one(query, context, parts: list) -> None:
    """Download a single video from a playlist by index."""
    _, idx_str, url_key = parts[0], parts[1], parts[2]
    idx = int(idx_str)
    url = _load_url(context, url_key)
    info = context.user_data.get("current_playlist")

    if not info or not url or idx >= len(info.entries):
        await query.edit_message_text(msg_error("Session expired or invalid index."), parse_mode=ParseMode.MARKDOWN_V2)
        return

    entry = info.entries[idx]
    video_url = entry.get("url") or entry.get("webpage_url")
    if not video_url:
        # Reconstruct from video_id
        vid_id = entry.get("id") or entry.get("video_id")
        if vid_id:
            video_url = f"https://www.youtube.com/watch?v={vid_id}"
        else:
            await query.edit_message_text(msg_error("Could not get video URL."), parse_mode=ParseMode.MARKDOWN_V2)
            return

    # Fetch that video's formats
    try:
        await query.edit_message_text("🔍 *Fetching video info…*", parse_mode=ParseMode.MARKDOWN_V2)
        video_info = await youtube_service.get_video_info(video_url)
        context.user_data["current_info"] = video_info
        context.user_data["current_url"] = video_url
        keyboard = kb_format_selector(video_info, context, video_url)
        await query.edit_message_text(
            msg_video_info(video_info),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=keyboard,
        )
    except Exception as e:
        await query.edit_message_text(msg_error(str(e)), parse_mode=ParseMode.MARKDOWN_V2)


async def _handle_playlist_download_all(query, context, parts: list) -> None:
    """Download all playlist videos, queuing them one by one."""
    url_key = parts[1]
    ext = parts[2] if len(parts) > 2 else "mp4"
    url = _load_url(context, url_key)
    info = context.user_data.get("current_playlist")
    user = query.from_user

    if not info or not url:
        await query.edit_message_text(msg_error("Session expired."), parse_mode=ParseMode.MARKDOWN_V2)
        return

    entries = info.entries
    total = len(entries)
    done = 0
    status_msg = query.message

    await status_msg.edit_text(
        f"📦 *Starting playlist download…*\n0/{total} videos",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    await download_queue.start()

    for idx, entry in enumerate(entries):
        video_url = entry.get("url") or entry.get("webpage_url")
        if not video_url:
            vid_id = entry.get("id") or entry.get("video_id")
            if vid_id:
                video_url = f"https://www.youtube.com/watch?v={vid_id}"
            else:
                continue

        entry_title = entry.get("title", f"Video {idx + 1}")
        done_event = asyncio.Event()
        result_holder = {"path": None, "error": None}

        async def on_done(job: DownloadJob, _dv=done_event, _rh=result_holder):
            _rh["path"] = job.result_path
            _dv.set()

        async def on_error(job: DownloadJob, _dv=done_event, _rh=result_holder):
            _rh["error"] = job.error
            _dv.set()

        job = DownloadJob(
            job_id=uuid.uuid4().hex[:8],
            user_id=user.id,
            url=video_url,
            format_spec="bestaudio/best" if ext in ("mp3", "m4a") else "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            ext=ext,
            on_done=on_done,
            on_error=on_error,
        )
        await download_queue.enqueue(job)

        try:
            await asyncio.wait_for(done_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            continue

        if result_holder["path"] and result_holder["path"].exists():
            # Upload silently
            try:
                file_path = result_holder["path"]
                file_size = file_path.stat().st_size
                if file_size <= settings.MAX_FILE_SIZE_MB * 1024 * 1024:
                    caption = f"📦 Playlist: *{truncate(info.title, 30)}*\n🎬 {truncate(entry_title, 50)}"
                    with open(file_path, "rb") as f:
                        if ext in ("mp3", "m4a"):
                            await query.message.chat.send_audio(audio=f, caption=caption, parse_mode=ParseMode.MARKDOWN, title=entry_title[:64], write_timeout=120)
                        else:
                            await query.message.chat.send_video(video=f, caption=caption, parse_mode=ParseMode.MARKDOWN, supports_streaming=True, write_timeout=120)
                asyncio.create_task(cleanup_service.clean_file(file_path, delay=30))
            except Exception as e:
                logger.error(f"Failed to upload playlist item {idx}: {e}")

        done += 1
        try:
            from app.services.ui_builder import msg_playlist_downloading
            await status_msg.edit_text(
                msg_playlist_downloading(done, total, entry_title),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            pass

    try:
        await status_msg.edit_text(
            f"✅ *Playlist download complete\\!*\n{done}/{total} videos sent\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception:
        pass


# ─── Utility handlers ─────────────────────────────────────────────────────────

async def _handle_cancel(query, context) -> None:
    user = query.from_user
    download_queue.cancel_user_jobs(user.id)
    context.user_data.clear()
    try:
        await query.edit_message_text(
            "❌ *Cancelled\\.*",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except BadRequest:
        pass


async def _handle_back(query, context, parts: list) -> None:
    """Go back to format selector."""
    url_key = parts[1] if len(parts) > 1 else None
    url = _load_url(context, url_key) if url_key else None
    info = context.user_data.get("current_info")

    if not info or not url:
        await query.edit_message_text(msg_error("Session expired."), parse_mode=ParseMode.MARKDOWN_V2)
        return

    keyboard = kb_format_selector(info, context, url)
    await query.edit_message_text(
        msg_video_info(info),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=keyboard,
    )
