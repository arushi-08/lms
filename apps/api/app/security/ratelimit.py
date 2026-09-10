"""Rate limiting.

In-process on purpose. This service runs as a single instance at the load it
serves (see docs/AUTH_AND_SCALE.md), so a shared store would add a dependency, a
failure mode and a monthly bill to solve a problem that does not exist yet. The
``RateLimiter`` protocol is the seam: the day a second instance exists, a
Redis-backed implementation drops in and nothing above this file changes.

A token bucket rather than a request log: it costs one small record per key
instead of a list of timestamps, and it allows a short burst — which matters,
because a heartbeat every ten seconds is bursty by nature when a page reloads.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    remaining: int
    retry_after: int


class RateLimiter(Protocol):
    def check(self, key: str, *, limit: int, window_seconds: int) -> Decision: ...


@dataclass
class _Bucket:
    tokens: float
    updated: float


class InMemoryRateLimiter:
    """Token bucket keyed by caller and route.

    Buckets are pruned lazily. Without that, a service running for weeks
    accumulates one record per user per route forever, which is a slow leak
    rather than a limiter.
    """

    #: Prune when the table grows past this. Well above any real user count, so
    #: the sweep effectively never runs in normal operation.
    _PRUNE_AT = 10_000

    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str, *, limit: int, window_seconds: int) -> Decision:
        if limit <= 0 or window_seconds <= 0:
            return Decision(allowed=True, remaining=limit, retry_after=0)

        # Monotonic: a clock adjustment must not hand out free requests or lock
        # someone out until the wall clock catches up.
        now = time.monotonic()
        rate = limit / window_seconds

        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._PRUNE_AT:
                self._prune(now, window_seconds)
            bucket = _Bucket(tokens=float(limit), updated=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(float(limit), bucket.tokens + elapsed * rate)
            bucket.updated = now

        if bucket.tokens < 1.0:
            # Seconds until one whole token exists again.
            retry_after = max(1, int((1.0 - bucket.tokens) / rate) + 1)
            return Decision(allowed=False, remaining=0, retry_after=retry_after)

        bucket.tokens -= 1.0
        return Decision(allowed=True, remaining=int(bucket.tokens), retry_after=0)

    def _prune(self, now: float, window_seconds: int) -> None:
        """Drop buckets that have refilled completely and so hold no state."""
        cutoff = now - window_seconds * 2
        stale = [key for key, b in self._buckets.items() if b.updated < cutoff]
        for key in stale:
            del self._buckets[key]

    def reset(self) -> None:
        self._buckets.clear()


class NullRateLimiter:
    """Allows everything. For tests that deliberately hammer an endpoint."""

    def check(self, key: str, *, limit: int, window_seconds: int) -> Decision:
        return Decision(allowed=True, remaining=limit, retry_after=0)


@dataclass(frozen=True, slots=True)
class Limits:
    """Per-route ceilings, in requests per minute per user.

    Set well above honest use. A limiter that trips on ordinary behaviour gets
    switched off, which is worse than not having one.
    """

    #: A heartbeat every 10s is 6/min; a reload or a second tab doubles it.
    progress: int = 40
    #: One per lesson start. Generous, since a flaky network retries.
    playback: int = 30
    #: Enough to answer thoughtfully, few enough to make brute force useless.
    quiz_attempts: int = 10
    assignment_submissions: int = 10
    enrollment: int = 10
    #: Everything an admin does, together.
    admin_writes: int = 120

    window_seconds: int = field(default=60)
