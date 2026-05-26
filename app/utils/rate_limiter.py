"""
Token-bucket rate limiter with per-user tracking.
"""
import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Tuple

from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class UserBucket:
    tokens: float = field(default_factory=lambda: float(settings.RATE_LIMIT_CALLS))
    last_refill: float = field(default_factory=time.monotonic)
    blocked_until: float = 0.0
    total_requests: int = 0
    violations: int = 0


class RateLimiter:
    """
    Per-user token bucket rate limiter.
    Allows RATE_LIMIT_CALLS requests per RATE_LIMIT_PERIOD seconds.
    On violation, user is blocked for RATE_LIMIT_COOLDOWN seconds.
    """

    def __init__(self):
        self._buckets: Dict[int, UserBucket] = defaultdict(UserBucket)
        self._lock = asyncio.Lock()

    def _refill(self, bucket: UserBucket) -> None:
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        refill_rate = settings.RATE_LIMIT_CALLS / settings.RATE_LIMIT_PERIOD
        bucket.tokens = min(
            float(settings.RATE_LIMIT_CALLS),
            bucket.tokens + elapsed * refill_rate,
        )
        bucket.last_refill = now

    async def check(self, user_id: int) -> Tuple[bool, float]:
        """
        Returns (allowed: bool, retry_after: float).
        retry_after is seconds to wait if not allowed.
        """
        async with self._lock:
            bucket = self._buckets[user_id]
            now = time.monotonic()

            # Check hard block
            if bucket.blocked_until > now:
                return False, bucket.blocked_until - now

            self._refill(bucket)

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                bucket.total_requests += 1
                return True, 0.0
            else:
                bucket.violations += 1
                bucket.blocked_until = now + settings.RATE_LIMIT_COOLDOWN
                logger.warning(
                    f"Rate limit violated by user {user_id} "
                    f"(violations: {bucket.violations})"
                )
                return False, float(settings.RATE_LIMIT_COOLDOWN)

    async def get_stats(self, user_id: int) -> dict:
        async with self._lock:
            bucket = self._buckets[user_id]
            self._refill(bucket)
            return {
                "tokens": bucket.tokens,
                "total_requests": bucket.total_requests,
                "violations": bucket.violations,
            }

    async def reset(self, user_id: int) -> None:
        async with self._lock:
            self._buckets[user_id] = UserBucket()


# Global singleton
rate_limiter = RateLimiter()
