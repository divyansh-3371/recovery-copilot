"""
Minimal in-memory sliding-window rate limiter for the FastAPI service.

Hand-rolled rather than pulling in a third-party dependency (e.g. slowapi)
so the entire mechanism is auditable in ~30 lines and testable with no
extra infrastructure. Appropriate for a single-process demo/service; a
multi-instance production deployment would swap the in-memory dict for a
shared store (Redis) behind the same `allow()` interface.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque:
        q = self._hits[key]
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        return q

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) >= self.max_requests:
                return False
            q.append(now)
            return True

    def retry_after(self, key: str) -> float:
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if not q:
                return 0.0
            return max(0.0, self.window_seconds - (now - q[0]))
