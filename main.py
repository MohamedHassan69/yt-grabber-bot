"""
YTGrabBot - Professional Telegram YouTube Downloader
Main entry point
"""
import asyncio
import logging
import os
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    PicklePersistence,
)

from app.config import settings
from app.handlers.command_handlers import start_command, help_command, cancel_command, stats_command
from app.handlers.message_handlers import handle_message
from app.handlers.callback_handlers import handle_callback
from app.services.cleanup_service import CleanupService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def post_init(application: Application) -> None:
    """Called after application initializes."""
    cleanup = CleanupService()
    await cleanup.clean_on_startup()
    logger.info("🤖 YTGrabBot is online and ready!")


async def post_shutdown(application: Application) -> None:
    """Called before application shuts down."""
    cleanup = CleanupService()
    await cleanup.clean_all()
    logger.info("🛑 YTGrabBot is shutting down. Cleaned up temporary files.")


def build_application() -> Application:
    """Build and configure the Telegram application."""
    persistence = PicklePersistence(filepath=settings.PERSISTENCE_FILE)

    app = (
        Application.builder()
        .token(settings.BOT_TOKEN)
        .persistence(persistence)
        .concurrent_updates(True)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(60)
        .pool_timeout(60)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("stats", stats_command))

    # Message handler for URLs
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Callback query handler for inline buttons
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app


def main() -> None:
    """Start the bot."""
    logger.info("=" * 60)
    logger.info("  YTGrabBot - Professional YouTube Downloader Bot")
    logger.info("=" * 60)
    logger.info(f"  Environment: {settings.ENVIRONMENT}")
    logger.info(f"  Max file size: {settings.MAX_FILE_SIZE_MB}MB")
    logger.info(f"  Rate limit: {settings.RATE_LIMIT_CALLS} calls / {settings.RATE_LIMIT_PERIOD}s")
    logger.info("=" * 60)

    application = build_application()

    if settings.WEBHOOK_URL:
        logger.info(f"🌐 Starting in webhook mode: {settings.WEBHOOK_URL}")
        application.run_webhook(
            listen="0.0.0.0",
            port=settings.PORT,
            secret_token=settings.WEBHOOK_SECRET,
            webhook_url=f"{settings.WEBHOOK_URL}/webhook/{settings.BOT_TOKEN}",
            url_path=f"/webhook/{settings.BOT_TOKEN}",
            drop_pending_updates=True,
        )
    else:
        logger.info("📡 Starting in polling mode...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


if __name__ == "__main__":
    main()
