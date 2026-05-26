"""
Userbot command handlers: /start, /help, /cancel, /stats
Adapted for Pyrogram.
"""
from pyrogram import Client, types
from pyrogram.enums import ParseMode

from app.config import settings
from app.services.ui_builder import msg_welcome, msg_help
from app.services.queue_service import download_queue
from app.utils.cache import video_cache
from app.utils.rate_limiter import rate_limiter
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def start_command(client: Client, message: types.Message) -> None:
    user = message.from_user
    logger.info(f"User {user.id} ({user.username}) started bot")
    await message.reply_text(
        msg_welcome(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(client: Client, message: types.Message) -> None:
    await message.reply_text(
        msg_help(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cancel_command(client: Client, message: types.Message) -> None:
    user = message.from_user
    download_queue.cancel_user_jobs(user.id)
    
    await message.reply_text(
        "✅ **Cancelled!** All your pending downloads have been stopped.",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info(f"User {user.id} cancelled jobs.")


async def stats_command(client: Client, message: types.Message) -> None:
    user = message.from_user
    user_id = user.id if user else message.chat.id
    
    rl_stats = await rate_limiter.get_stats(user_id)
    cache_stats = video_cache.stats
    queue_size = download_queue.queue_size
    active = download_queue.user_active_count(user_id)

    is_admin = user_id in settings.ADMIN_USER_IDS
    admin_section = ""
    if is_admin:
        admin_section = (
            f"\n\n**🔧 Admin Info:**\n"
            f"Queue size: `{queue_size}`\n"
            f"Cache: `{cache_stats.get('size', 0)}` entries ({cache_stats.get('hit_rate_pct', 0)}% hit rate)"
        )

    text = (
        f"📊 **Your Stats**\n\n"
        f"Total requests: `{rl_stats.get('total_requests', 0)}`\n"
        f"Rate violations: `{rl_stats.get('violations', 0)}`\n"
        f"Active downloads: `{active}`\n"
        f"Queue position: `{queue_size}`"
        f"{admin_section}"
    )
    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
