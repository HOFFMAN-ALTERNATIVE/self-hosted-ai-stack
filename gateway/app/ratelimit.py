import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    updated: float = field(default_factory=time.monotonic)


class TokenBucketLimiter:
    """In-process token bucket per identity. Refill = rpm/60 tokens per second, capacity = burst.

    Suitable for a single gateway replica; use Redis for horizontal scaling.
    """

    def __init__(self, rpm: int, burst: int, clock: Callable[[], float] | None = None) -> None:
        self.rate = rpm / 60.0
        self.capacity = float(burst)
        self._clock = clock or time.monotonic
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> tuple[bool, float]:
        """Take one token. Returns (allowed, retry_after_seconds)."""
        async with self._lock:
            now = self._clock()
            b = self._buckets.get(key)
            if b is None:
                b = self._buckets[key] = _Bucket(tokens=self.capacity, updated=now)
            b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.rate)
            b.updated = now
            if b.tokens >= 1:
                b.tokens -= 1
                return True, 0.0
            return False, (1 - b.tokens) / self.rate
