"""
Automatic cleanup of temporary download files.
"""
import asyncio
import time
from pathlib import Path

from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class CleanupService:
    async def clean_on_startup(self):
        """Remove all leftover tmp files from previous sessions."""
        count = 0
        for f in settings.TMP_DIR.iterdir():
            if f.is_file():
                try:
                    f.unlink()
                    count += 1
                except Exception:
                    pass
        if count:
            logger.info(f"Cleaned {count} leftover tmp files on startup.")

    async def clean_all(self):
        """Remove all tmp files (on shutdown)."""
        await self.clean_on_startup()

    async def clean_file(self, path: Path, delay: int = 0):
        """Delete a single file, optionally after a delay."""
        if delay:
            await asyncio.sleep(delay)
        try:
            if path.exists():
                path.unlink()
                logger.debug(f"Deleted tmp file: {path.name}")
        except Exception as e:
            logger.warning(f"Could not delete {path}: {e}")

    async def clean_old_files(self):
        """Remove tmp files older than TMP_FILE_MAX_AGE_MINUTES."""
        cutoff = time.time() - settings.TMP_FILE_MAX_AGE_MINUTES * 60
        count = 0
        for f in settings.TMP_DIR.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    count += 1
                except Exception:
                    pass
        if count:
            logger.info(f"Cleaned {count} aged tmp files.")

    async def schedule_delete(self, path: Path, after_seconds: int = 120):
        """Schedule a file for deletion in the background."""
        asyncio.create_task(self.clean_file(path, delay=after_seconds))


cleanup_service = CleanupService()
