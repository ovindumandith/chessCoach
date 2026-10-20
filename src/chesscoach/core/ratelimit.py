"""In-memory sliding-window rate limiter for expensive operations and login attempts.

Process-local by design for the pilot (one backend process). Running several backend
processes would need a shared store (e.g. Redis); see docs/IMPLEMENTATION_PLAN.md.
"""

import threading
import time
from collections import defaultdict, deque

from chesscoach.core.errors import DomainError


class RateLimitedError(DomainError):
    status_code = 429
    code = "rate_limited"


class SlidingWindowLimiter:
    def __init__(self):
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, *, limit: int, window_seconds: float) -> None:
        """Record one event for `key`, or raise RateLimitedError if over the limit."""
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window_seconds:
                events.popleft()
            if len(events) >= limit:
                retry_after = int(events[0] + window_seconds - now) + 1
                raise RateLimitedError(
                    "Too many requests; try again later",
                    details={"retry_after_seconds": retry_after},
                )
            events.append(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


limiter = SlidingWindowLimiter()
