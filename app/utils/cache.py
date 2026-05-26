"""
TTL-based in-memory cache for video metadata.
Prevents redundant yt-dlp info fetches for the same URL.
"""
import asyncio
import time
from typing import Any, Optional

from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class TTLCache:
    """
    Thread-safe async TTL cache.
    Automatically evicts stale entries.
    """

    def __init__(self, ttl: int = None, max_size: int = None):
        self._ttl = ttl or settings.CACHE_TTL_SECONDS
        self._max_size = max_size or settings.CACHE_MAX_ENTRIES
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            if len(self._store) >= self._max_size:
                await self._evict_oldest()
            self._store[key] = (value, time.monotonic() + self._ttl)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def _evict_oldest(self) -> None:
        """Remove the oldest 10% of entries."""
        now = time.monotonic()
        # First remove expired
        expired = [k for k, (_, exp) in self._store.items() if exp < now]
        for k in expired:
            del self._store[k]
        # If still too large, remove oldest by expiry
        if len(self._store) >= self._max_size:
            count = max(1, self._max_size // 10)
            oldest = sorted(self._store.items(), key=lambda x: x[1][1])[:count]
            for k, _ in oldest:
                del self._store[k]

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total else 0
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate_pct": round(hit_rate, 1),
        }


# Global cache instance
video_cache = TTLCache()
