"""
YTGrabBot - Professional Pyrogram Userbot Downloader (2GB Limit)
Main entry point with Dummy Web Server for Koyeb
"""
import asyncio
import logging
import os
from aiohttp import web
from pyrogram import Client, idle
from pyrogram.handlers import MessageHandler
from pyrogram import filters

from app.config import settings
from app.handlers.command_handlers import start_command, help_command, cancel_command, stats_command
from app.handlers.message_handlers import handle_message
from app.services.cleanup_service import CleanupService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# ─── Dummy Web Server (For Koyeb Health Checks) ──────────────────────────────
async def health_check(request):
    return web.Response(text="Pyrogram Userbot is Healthy & Running! (2GB Limit Unlocked)")

async def start_dummy_server():
    app = web.Application()
    app.add_routes([web.get('/', health_check)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', settings.PORT)
    await site.start()
    logger.info(f"🌐 Dummy web server started on port {settings.PORT}")


# ─── Main Bot Logic ──────────────────────────────────────────────────────────
async def main():
    logger.info("=" * 60)
    logger.info("  YTGrabBot - Pyrogram Userbot Mode (2GB Limit)")
    logger.info("=" * 60)
    logger.info(f"  Environment: {settings.ENVIRONMENT}")
    logger.info(f"  Max file size: {settings.MAX_FILE_SIZE_MB}MB")
    logger.info("=" * 60)

    # 1. تشغيل السيرفر الوهمي عشان Koyeb
    await start_dummy_server()

    # 2. تنظيف الملفات المؤقتة عند التشغيل
    cleanup = CleanupService()
    await cleanup.clean_on_startup()
    
    # 3. تهيئة حسابك (Userbot)
    app = Client(
        "YTGrabBot",
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        session_string=settings.SESSION_STRING,
        in_memory=True  # عشان ميحصلش مشاكل في ملفات الجلسة على السيرفر
    )

    # 4. ربط الأوامر (هتشتغل على رسايلك إنت بس بفضل filters.me)
    app.add_handler(MessageHandler(start_command, filters.command("start") & filters.me))
    app.add_handler(MessageHandler(help_command, filters.command("help") & filters.me))
    app.add_handler(MessageHandler(cancel_command, filters.command("cancel") & filters.me))
    app.add_handler(MessageHandler(stats_command, filters.command("stats") & filters.me))
    
    # معالج الروابط
    app.add_handler(MessageHandler(handle_message, filters.text & filters.regex(r"http") & filters.me))

    # 5. تشغيل البوت
    await app.start()
    logger.info("🤖 Pyrogram Userbot is online and ready!")
    
    # 6. إبقاء البوت قيد التشغيل
    await idle()
    
    # 7. التنظيف والإغلاق
    await app.stop()
    await cleanup.clean_all()
    logger.info("🛑 YTGrabBot is shutting down. Cleaned up temporary files.")


if __name__ == "__main__":
    asyncio.run(main())
