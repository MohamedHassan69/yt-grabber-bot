"""
Bot command handlers: /start, /help, /cancel, /stats
"""
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from app.config import settings
from app.services.ui_builder import msg_welcome, msg_help
from app.services.queue_service import download_queue
from app.utils.cache import video_cache
from app.utils.rate_limiter import rate_limiter
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started bot")
    await update.message.reply_text(
        msg_welcome(),
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        msg_help(),
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    download_queue.cancel_user_jobs(user.id)
    # Clear any active state
    context.user_data.clear()
    await update.message.reply_text(
        "✅ *Cancelled\\!* All your pending downloads have been stopped\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    logger.info(f"User {user.id} cancelled jobs.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    rl_stats = await rate_limiter.get_stats(user.id)
    cache_stats = video_cache.stats
    queue_size = download_queue.queue_size
    active = download_queue.user_active_count(user.id)

    is_admin = user.id in settings.ADMIN_USER_IDS
    admin_section = ""
    if is_admin:
        admin_section = (
            f"\n\n*🔧 Admin Info:*\n"
            f"Queue size: `{queue_size}`\n"
            f"Cache: `{cache_stats['size']}` entries \\({cache_stats['hit_rate_pct']}% hit rate\\)"
        )

    text = (
        f"📊 *Your Stats*\n\n"
        f"Total requests: `{rl_stats['total_requests']}`\n"
        f"Rate violations: `{rl_stats['violations']}`\n"
        f"Active downloads: `{active}`\n"
        f"Queue position: `{queue_size}`"
        f"{admin_section}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
