"""Rate limiter unit tests.

The limiter is arithmetic over a clock, so these tests drive the clock rather
than sleeping: a test that waits a real minute to watch a bucket refill is a
test nobody runs.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.security.ratelimit import InMemoryRateLimiter, Limits, NullRateLimiter


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    """A monotonic clock this test controls. ``clock[0]`` is "now", in seconds."""
    now = [1_000.0]
    monkeypatch.setattr("app.security.ratelimit.time.monotonic", lambda: now[0])
    yield now


class TestBucket:
    def test_a_full_window_of_requests_is_allowed(self, clock: list[float]) -> None:
        limiter = InMemoryRateLimiter()
        allowed = [
            limiter.check("k", limit=5, window_seconds=60).allowed for _ in range(5)
        ]
        assert allowed == [True] * 5

    def test_the_next_request_is_refused(self, clock: list[float]) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.check("k", limit=5, window_seconds=60)

        decision = limiter.check("k", limit=5, window_seconds=60)
        assert decision.allowed is False
        assert decision.remaining == 0
        # A whole token takes one twelfth of the window; the caller is told to
        # wait, and told a duration that is actually long enough.
        assert decision.retry_after >= 1
        clock[0] += decision.retry_after
        assert limiter.check("k", limit=5, window_seconds=60).allowed is True

    def test_tokens_refill_gradually(self, clock: list[float]) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.check("k", limit=5, window_seconds=60)
        assert limiter.check("k", limit=5, window_seconds=60).allowed is False

        # 5 per 60s is one token every 12s: 11 buys nothing, 12 buys one.
        clock[0] += 11
        assert limiter.check("k", limit=5, window_seconds=60).allowed is False
        clock[0] += 1
        assert limiter.check("k", limit=5, window_seconds=60).allowed is True
        assert limiter.check("k", limit=5, window_seconds=60).allowed is False

    def test_a_bucket_never_fills_beyond_its_limit(self, clock: list[float]) -> None:
        limiter = InMemoryRateLimiter()
        limiter.check("k", limit=5, window_seconds=60)
        # Idle for an hour. Without a cap this would bank 300 requests and the
        # first burst after a quiet night would sail straight through.
        clock[0] += 3_600
        allowed = sum(
            limiter.check("k", limit=5, window_seconds=60).allowed for _ in range(10)
        )
        assert allowed == 5

    def test_keys_are_independent(self, clock: list[float]) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(5):
            limiter.check("alice", limit=5, window_seconds=60)
        assert limiter.check("alice", limit=5, window_seconds=60).allowed is False
        assert limiter.check("bob", limit=5, window_seconds=60).allowed is True

    def test_a_disabled_limit_allows_everything(self, clock: list[float]) -> None:
        limiter = InMemoryRateLimiter()
        assert all(
            limiter.check("k", limit=0, window_seconds=60).allowed for _ in range(100)
        )
        assert all(
            limiter.check("k", limit=5, window_seconds=0).allowed for _ in range(100)
        )


class TestPruning:
    def test_refilled_buckets_are_dropped(self, clock: list[float]) -> None:
        """A key per user per route, kept forever, is a slow leak."""
        limiter = InMemoryRateLimiter()
        for i in range(InMemoryRateLimiter._PRUNE_AT):
            limiter.check(f"user-{i}", limit=5, window_seconds=60)
        assert len(limiter._buckets) == InMemoryRateLimiter._PRUNE_AT

        clock[0] += 3_600  # every existing bucket is now fully refilled
        limiter.check("someone-new", limit=5, window_seconds=60)
        assert len(limiter._buckets) == 1

    def test_active_buckets_survive_a_prune(self, clock: list[float]) -> None:
        limiter = InMemoryRateLimiter()
        for i in range(InMemoryRateLimiter._PRUNE_AT - 1):
            limiter.check(f"user-{i}", limit=5, window_seconds=60)

        clock[0] += 3_600
        # Spend a bucket right now: it holds real state and must not be swept.
        for _ in range(5):
            limiter.check("busy", limit=5, window_seconds=60)

        limiter.check("someone-new", limit=5, window_seconds=60)
        assert limiter.check("busy", limit=5, window_seconds=60).allowed is False


class TestNullRateLimiter:
    def test_it_allows_everything(self) -> None:
        limiter = NullRateLimiter()
        assert all(
            limiter.check("k", limit=1, window_seconds=60).allowed for _ in range(50)
        )


class TestLimits:
    def test_the_progress_limit_clears_a_realistic_heartbeat(self) -> None:
        """A 10s heartbeat in two open tabs is 12/min. If the ceiling were near
        that, ordinary viewing would trip it and the limiter would be switched
        off in anger."""
        limits = Limits()
        assert limits.window_seconds == 60
        assert limits.progress >= 24
