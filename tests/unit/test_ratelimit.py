"""Unit tests for swarmline.runtime.ratelimit — RateLimiter contract tests.

TDD Red phase: tests before implementation.
Covers: InMemoryRateLimiter sliding window, get_remaining is non-mutating,
keyed by generic str, key_prefix injectable, factory backend selection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

# Shared async fake-Redis harness (extracted to tests/unit/_fake_redis.py so
# future Redis-backed tests reuse it without copy-paste — OSS-BL-02).
from _fake_redis import _FakeRedis, _FakeZSet

from swarmline.runtime.ratelimit import (
    InMemoryRateLimiter,
    RateLimitResult,
    RateLimiterPort,
    RedisRateLimiter,
    create_rate_limiter,
)


# ---------------------------------------------------------------------------
# Structural / protocol
# ---------------------------------------------------------------------------


def test_ratelimitresult_is_frozen_slots_dataclass() -> None:

    r = RateLimitResult(
        allowed=True,
        limit=10,
        remaining=9,
        reset_at=datetime.now(tz=UTC),
    )
    assert r.allowed is True
    with pytest.raises((AttributeError, TypeError)):
        r.allowed = False  # type: ignore[misc]


def test_ratelimiterport_has_check_limit_and_get_remaining() -> None:
    assert hasattr(RateLimiterPort, "check_limit")
    assert hasattr(RateLimiterPort, "get_remaining")


# ---------------------------------------------------------------------------
# InMemoryRateLimiter — basic allow / deny
# ---------------------------------------------------------------------------


@pytest.fixture
def limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter(limits={"read": 5, "write": 2}, window_seconds=60)


async def test_check_limit_under_window_allowed(limiter: InMemoryRateLimiter) -> None:
    result = await limiter.check_limit("key-1", "read")
    assert result.allowed is True
    assert result.limit == 5
    assert result.remaining == 4


async def test_check_limit_at_limit_denied(limiter: InMemoryRateLimiter) -> None:
    for _ in range(5):
        await limiter.check_limit("key-1", "read")
    result = await limiter.check_limit("key-1", "read")
    assert result.allowed is False
    assert result.remaining == 0


async def test_check_limit_decrements_remaining(limiter: InMemoryRateLimiter) -> None:
    r1 = await limiter.check_limit("key-dec", "read")
    r2 = await limiter.check_limit("key-dec", "read")
    assert r1.remaining == 4
    assert r2.remaining == 3


# ---------------------------------------------------------------------------
# Keyed by generic str (key param)
# ---------------------------------------------------------------------------


async def test_check_limit_keyed_by_generic_str(limiter: InMemoryRateLimiter) -> None:
    """Different str keys have independent buckets."""
    for _ in range(5):
        await limiter.check_limit("alice", "read")
    result_alice = await limiter.check_limit("alice", "read")
    result_bob = await limiter.check_limit("bob", "read")
    assert result_alice.allowed is False
    assert result_bob.allowed is True


async def test_check_limit_different_groups_independent(
    limiter: InMemoryRateLimiter,
) -> None:
    """Same key, different groups — separate buckets."""
    for _ in range(2):
        await limiter.check_limit("k", "write")
    result_write = await limiter.check_limit("k", "write")
    result_read = await limiter.check_limit("k", "read")
    assert result_write.allowed is False
    assert result_read.allowed is True


# ---------------------------------------------------------------------------
# Prune expired entries
# ---------------------------------------------------------------------------


async def test_prune_removes_expired_entries() -> None:
    """Entries older than window_seconds are pruned on next request."""
    lim = InMemoryRateLimiter(limits={"read": 2}, window_seconds=60)
    # Inject stale entries (well past the 60 s window)
    old_ts = datetime.now(tz=UTC) - timedelta(seconds=120)
    lim._buckets[("key-stale", "read")] = [old_ts, old_ts]

    result = await lim.check_limit("key-stale", "read")
    assert result.allowed is True
    assert result.remaining == 1  # 1 used (the new request), 1 remains


# ---------------------------------------------------------------------------
# get_remaining is non-mutating
# ---------------------------------------------------------------------------


async def test_get_remaining_does_not_consume_budget(
    limiter: InMemoryRateLimiter,
) -> None:
    """Calling get_remaining repeatedly must not decrement the budget."""
    r1 = await limiter.get_remaining("key-nm", "read")
    r2 = await limiter.get_remaining("key-nm", "read")
    assert r1.remaining == 5
    assert r2.remaining == 5


async def test_get_remaining_reflects_consumed_budget(
    limiter: InMemoryRateLimiter,
) -> None:
    for _ in range(3):
        await limiter.check_limit("key-track", "read")
    r = await limiter.get_remaining("key-track", "read")
    assert r.remaining == 2
    assert r.allowed is True


async def test_get_remaining_shows_denied_when_limit_reached(
    limiter: InMemoryRateLimiter,
) -> None:
    for _ in range(5):
        await limiter.check_limit("key-full", "read")
    r = await limiter.get_remaining("key-full", "read")
    assert r.allowed is False
    assert r.remaining == 0


# ---------------------------------------------------------------------------
# Default limit fallback
# ---------------------------------------------------------------------------


async def test_default_limit_applied_for_unknown_group(
    limiter: InMemoryRateLimiter,
) -> None:
    """Unknown endpoint groups fall back to _DEFAULT_LIMIT = 100."""
    r = await limiter.get_remaining("k", "unknown-group")
    assert r.limit == 100


# ---------------------------------------------------------------------------
# Factory: backend selection and key_prefix
# ---------------------------------------------------------------------------


def test_create_rate_limiter_inmemory_returns_inmemory() -> None:
    result = create_rate_limiter(backend="inmemory")
    assert isinstance(result, InMemoryRateLimiter)


def test_create_rate_limiter_redis_without_url_raises() -> None:
    with pytest.raises(ValueError, match="redis_url"):
        create_rate_limiter(backend="redis")


def test_create_rate_limiter_key_prefix_accepted_by_factory() -> None:
    """key_prefix kwarg accepted (used by redis backend; ignored for inmemory)."""
    result = create_rate_limiter(backend="inmemory", key_prefix="custom:prefix")
    assert isinstance(result, InMemoryRateLimiter)


def test_create_rate_limiter_limits_forwarded() -> None:
    lim = create_rate_limiter(backend="inmemory", limits={"api": 42})
    assert isinstance(lim, InMemoryRateLimiter)
    assert lim._limits == {"api": 42}


# ---------------------------------------------------------------------------
# Redis: timestamp-collision regression (OSS-T3 cycle-1 fix)
# ---------------------------------------------------------------------------
#
# Bug: RedisRateLimiter.check_limit used str(now_ts) as BOTH the ZSET member
# AND the score.  When time.time() returns the same float for concurrent
# requests, every zadd overwrites the same member, zcard never reaches the
# limit, and over-limit requests are wrongly allowed.  The fix uses a
# uuid4.hex member (unique per request) with now_ts as score only.
#
# Fake Redis below uses a dict (member->score) for each ZSET key so that
# zadd overwrites are visible in zcard — a list-based fake would hide the bug.
# The harness classes (_FakeZSet, _FakePipeline, _FakeRedis) live in the shared
# tests/unit/_fake_redis.py module so future Redis-backed tests reuse them.


async def test_redis_limiter_enforces_limit_under_timestamp_collision() -> None:
    """Regression: concurrent requests sharing the same time.time() float must
    each count as a DISTINCT ZSET member so the limit is correctly enforced.

    Under the buggy str(now_ts)-as-member scheme, all requests collapse to one
    member → zcard stays at 1 → the 4th request is wrongly ALLOWED.
    With uuid4.hex members (the fix), each request is distinct → 4th is DENIED.
    """
    import swarmline.runtime.ratelimit as rl_mod  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    fake_redis = _FakeRedis()
    limiter = RedisRateLimiter(
        redis=fake_redis,  # type: ignore[arg-type]
        limits={"api": 3},
        window_seconds=60,
    )

    # Freeze time so every request has the SAME now_ts float.
    FIXED_TS = 1_700_000_000.0
    with patch.object(rl_mod.time, "time", return_value=FIXED_TS):
        r1 = await limiter.check_limit("burst-key", "api")
        r2 = await limiter.check_limit("burst-key", "api")
        r3 = await limiter.check_limit("burst-key", "api")
        r4 = await limiter.check_limit("burst-key", "api")  # must be denied

    assert r1.allowed is True, "1st request should be allowed"
    assert r2.allowed is True, "2nd request should be allowed"
    assert r3.allowed is True, "3rd request should be allowed"
    assert r4.allowed is False, "4th request must be denied (limit=3)"

    redis_key = limiter._key("burst-key", "api")
    zset = fake_redis.get_zset(redis_key)
    assert zset is not None
    assert zset.member_count() == 3, (
        f"ZSET must hold exactly 3 members (one per allowed request); "
        f"got {zset.member_count()}"
    )


# ---------------------------------------------------------------------------
# get_remaining read-only regression (OSS-T3 cycle-2 fix)
# ---------------------------------------------------------------------------
#
# Bug: both InMemoryRateLimiter.get_remaining and RedisRateLimiter.get_remaining
# mutated shared state (InMemory: _prune wrote back to self._buckets; Redis:
# pipeline issued zremrangebyscore which deleted entries from the ZSET).
# Fix: make both implementations genuinely read-only.
#
# These tests are RED before the fix (expired entries are deleted by
# get_remaining) and GREEN after (expired entries survive the call).


async def test_inmemory_get_remaining_does_not_prune_expired_entries() -> None:
    """get_remaining must NOT write to self._buckets.

    RED before fix: _prune() inside get_remaining removes the expired entry,
    shrinking the bucket from 3 to 2.  The assertion len == 3 fails.
    GREEN after fix: read-only count path leaves the bucket unchanged.
    """
    lim = InMemoryRateLimiter(limits={"read": 5}, window_seconds=60)
    bucket_key = ("k-readonly", "read")

    fresh_ts1 = datetime.now(tz=UTC) - timedelta(seconds=5)
    fresh_ts2 = datetime.now(tz=UTC) - timedelta(seconds=10)
    expired_ts = datetime.now(tz=UTC) - timedelta(seconds=120)  # beyond 60 s window

    # Pre-populate bucket with 2 fresh + 1 expired entry.
    lim._buckets[bucket_key] = [expired_ts, fresh_ts1, fresh_ts2]
    assert len(lim._buckets[bucket_key]) == 3

    # Two get_remaining calls — neither must mutate the bucket.
    r1 = await lim.get_remaining("k-readonly", "read")
    r2 = await lim.get_remaining("k-readonly", "read")

    # Expired entry must STILL be present in the bucket after get_remaining.
    assert len(lim._buckets[bucket_key]) == 3, (
        f"get_remaining must not prune self._buckets: expected 3 entries, "
        f"got {len(lim._buckets[bucket_key])}"
    )
    assert expired_ts in lim._buckets[bucket_key], (
        "Expired entry must survive get_remaining (read-only contract)"
    )

    # Remaining count must reflect only the 2 in-window entries, not the expired one.
    assert r1.remaining == 3, (
        f"expected remaining=3 (limit 5, 2 in-window), got {r1.remaining}"
    )
    assert r2.remaining == 3  # second call is identical — no budget consumed


async def test_redis_get_remaining_does_not_prune_expired_entries() -> None:
    """get_remaining must NOT issue any write to the Redis ZSET.

    RED before fix: the pipeline runs zremrangebyscore which deletes the
    expired entry, shrinking the ZSET from 4 to 3.  The assertion count == 4
    fails.
    GREEN after fix: zcount-only read leaves the ZSET unchanged.
    """
    import time as _time  # noqa: PLC0415

    fake_redis = _FakeRedis()
    limiter = RedisRateLimiter(
        redis=fake_redis,  # type: ignore[arg-type]
        limits={"api": 5},
        window_seconds=60,
    )
    redis_key = limiter._key("k-redis-ro", "api")

    now_ts = _time.time()
    expired_score = now_ts - 120.0  # beyond 60 s window
    fresh_score1 = now_ts - 5.0
    fresh_score2 = now_ts - 10.0
    fresh_score3 = now_ts - 15.0

    # Pre-populate ZSET with 1 expired + 3 fresh entries.
    fake_redis._zsets[redis_key] = _FakeZSet()
    fake_redis._zsets[redis_key].zadd(
        {
            "member-expired": expired_score,
            "member-fresh-1": fresh_score1,
            "member-fresh-2": fresh_score2,
            "member-fresh-3": fresh_score3,
        }
    )
    assert fake_redis._zsets[redis_key].member_count() == 4

    # Two get_remaining calls — neither must mutate the ZSET.
    r1 = await limiter.get_remaining("k-redis-ro", "api")
    r2 = await limiter.get_remaining("k-redis-ro", "api")

    # All 4 entries (including expired) must still be in the ZSET.
    assert fake_redis._zsets[redis_key].member_count() == 4, (
        f"get_remaining must not prune the Redis ZSET: expected 4 members, "
        f"got {fake_redis._zsets[redis_key].member_count()}"
    )
    assert "member-expired" in fake_redis._zsets[redis_key]._data, (
        "Expired entry must survive get_remaining (read-only contract)"
    )

    # Remaining count must reflect only the 3 in-window entries.
    assert r1.remaining == 2, (
        f"expected remaining=2 (limit 5, 3 in-window), got {r1.remaining}"
    )
    assert r2.remaining == 2  # second call is identical


# ---------------------------------------------------------------------------
# Redis _key injectivity regression (OSS-T3 cycle-3 fix)
# ---------------------------------------------------------------------------
#
# Bug: _key builds f"{prefix}:{key}:{group}" — a naive colon-join.
# ("a:b", "c") and ("a", "b:c") both produce "<prefix>:a:b:c" → same ZSET →
# the two windows collide and one is wrongly rate-limited by the other.
# Fix: percent-encode key and endpoint_group with urllib.parse.quote(safe="")
# so `:` inside a component becomes `%3A` and the join is unambiguous.


async def test_redis_key_injective_for_colliding_str_pairs() -> None:
    """_key must produce DISTINCT Redis keys for (key, group) pairs that contain
    the delimiter character in different positions.

    RED before fix: f"<prefix>:{key}:{group}" collapses both pairs to the
    same string, so the injectivity assertion fails AND the behavioral test
    shows the second window is wrongly denied.

    GREEN after fix: quote() encodes internal colons so both assertions pass.
    """
    fake_redis = _FakeRedis()
    limiter = RedisRateLimiter(
        redis=fake_redis,  # type: ignore[arg-type]
        limits={"c": 1, "b:c": 1},
        window_seconds=60,
        key_prefix="p",
    )

    # --- (a) Direct injectivity check ---
    k1 = limiter._key("a:b", "c")
    k2 = limiter._key("a", "b:c")
    assert k1 != k2, (
        f"_key must be injective for colliding (key, group) pairs; "
        f"got identical key {k1!r} for both ('a:b','c') and ('a','b:c')"
    )

    # --- (b) Behavioral isolation check ---
    # limit=1 for each group; a request to ("a:b","c") must NOT consume
    # the budget for ("a","b:c") — they are independent windows.
    r1 = await limiter.check_limit("a:b", "c")
    r2 = await limiter.check_limit("a", "b:c")

    assert r1.allowed is True, "1st window ('a:b','c') should be allowed"
    assert r2.allowed is True, (
        "2nd window ('a','b:c') must be allowed — it is independent of "
        "('a:b','c'); under the buggy naive join both share one ZSET and "
        "the 2nd is wrongly denied"
    )
