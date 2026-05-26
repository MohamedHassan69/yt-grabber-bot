"""
Structured logging setup for production use.
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from app.config import settings


def setup_logger(name: str) -> logging.Logger:
    """
    Configure and return a logger with both console and rotating file handlers.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # Already configured

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(level)
    logger.addHandler(console)

    # Rotating file handler
    try:
        log_file = settings.LOG_DIR / "ytgrabbot.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,   # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)
    except Exception:
        pass  # File logging optional; console is enough on container envs

    logger.propagate = False
    return logger
