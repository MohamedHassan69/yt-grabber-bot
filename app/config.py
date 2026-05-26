"""
Centralized configuration management via environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings:
    # ── Core ─────────────────────────────────────────────────────────────────
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    PORT: int = int(os.getenv("PORT", "8080"))

    # ── Webhook (leave empty to use polling) ─────────────────────────────────
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    # ── Paths ─────────────────────────────────────────────────────────────────
    TMP_DIR: Path = BASE_DIR / "tmp"
    LOG_DIR: Path = BASE_DIR / "logs"
    PERSISTENCE_FILE: str = str(BASE_DIR / "bot_persistence.pkl")

    # ── Download limits ───────────────────────────────────────────────────────
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "45"))   # Telegram bot limit is 50 MB
    MAX_DURATION_SECONDS: int = int(os.getenv("MAX_DURATION_SECONDS", "1800"))  # 30 min
    MAX_PLAYLIST_ITEMS: int = int(os.getenv("MAX_PLAYLIST_ITEMS", "50"))
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_CALLS: int = int(os.getenv("RATE_LIMIT_CALLS", "5"))
    RATE_LIMIT_PERIOD: int = int(os.getenv("RATE_LIMIT_PERIOD", "60"))  # seconds
    RATE_LIMIT_COOLDOWN: int = int(os.getenv("RATE_LIMIT_COOLDOWN", "30"))

    # ── Cache ─────────────────────────────────────────────────────────────────
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))   # 1 hour
    CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "200"))

    # ── Cleanup ───────────────────────────────────────────────────────────────
    TMP_FILE_MAX_AGE_MINUTES: int = int(os.getenv("TMP_FILE_MAX_AGE_MINUTES", "30"))

    # ── Admin ─────────────────────────────────────────────────────────────────
    ADMIN_USER_IDS: list[int] = [
        int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
    ]

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    def __post_init__(self):
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required.")
        self.TMP_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def validate(self):
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is not set. Please check your .env file.")
        self.TMP_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        return self


settings = Settings()
settings.validate()
