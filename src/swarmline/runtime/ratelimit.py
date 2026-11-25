"""Rate limiter — sliding-window per-key request throttle.

No attribution header: this is a taskloom-ORIGINAL implementation ported to
swarmline as a generic, product-free rate limiting layer (REQ-OSS-051).
No tenant/workspace/AccessContext/AuditEvent/FastAPI/ORM coupling — plain
``str`` keys, stdlib datetime only, lazy optional ``redis.asyncio`` import.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from redis.asyncio import Redis  # ty: ignore[unresolved-import]  # optional dep

_DEFAULT_LIMIT = 100

__all__ = [
    "RateLimitResult",
    "RateLimiterPort",
    "InMemoryRateLimiter",
    "RedisRateLimiter",
    "create_rate_limiter",
]


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime


# ---------------------------------------------------------------------------
# Protocol (ISP: exactly 2 methods)
# ---------------------------------------------------------------------------


class RateLimiterPort(Protocol):
    """Generic sliding-window rate limiter. Keyed by a plain ``str`` (key)."""

    async def check_limit(self, key: str, endpoint_group: str) -> RateLimitResult:
        """Check and record one request.  Returns allowed + headers data."""
        ...

    async def get_remaining(self, key: str, endpoint_group: str) -> RateLimitResult:
        """Check without recording (preflight / read-only)."""
        ...


# ---------------------------------------------------------------------------
# In-process sliding window (stdlib only)
# ---------------------------------------------------------------------------


class InMemoryRateLimiter:
    """Sliding-window rate limiter — single-process / test deployments."""

    def __init__(
        self,
        limits: dict[str, int] | None = None,
        window_seconds: int = 60,
    ) -> None:
        self._limits = limits or {}
        self._window_seconds = window_seconds
        # {(key, group): [timestamp, ...]}
        self._buckets: dict[tuple[str, str], list[datetime]] = {}

    def _get_limit(self, endpoint_group: str) -> int:
        return self._limits.get(endpoint_group, _DEFAULT_LIMIT)

    def _prune(self, bucket_key: tuple[str, str], now: datetime) -> list[datetime]:
        cutoff = now - timedelta(seconds=self._window_seconds)
        entries = self._buckets.get(bucket_key, [])
        pruned = [ts for ts in entries if ts > cutoff]
        self._buckets[bucket_key] = pruned
        return pruned

    def _build_result(
        self, allowed: bool, limit: int, count: int, now: datetime
    ) -> RateLimitResult:
        remaining = max(0, limit - count)
        reset_at = now + timedelta(seconds=self._window_seconds)
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
        )

    async def check_limit(self, key: str, endpoint_group: str) -> RateLimitResult:
        now = datetime.now(tz=UTC)
        bucket_key = (key, endpoint_group)
        entries = self._prune(bucket_key, now)
        limit = self._get_limit(endpoint_group)

        if len(entries) >= limit:
            return self._build_result(
                allowed=False, limit=limit, count=len(entries), now=now
            )

        entries.append(now)
        self._buckets[bucket_key] = entries
        return self._build_result(
            allowed=True, limit=limit, count=len(entries), now=now
        )

    async def get_remaining(self, key: str, endpoint_group: str) -> RateLimitResult:
        # Read-only: count in-window entries without writing to self._buckets.
        # Expired entries are pruned lazily on the next check_limit call.
        now = datetime.now(tz=UTC)
        bucket_key = (key, endpoint_group)
        limit = self._get_limit(endpoint_group)
        cutoff = now - timedelta(seconds=self._window_seconds)
        entries = self._buckets.get(bucket_key, [])
        count = sum(1 for ts in entries if ts > cutoff)
        allowed = count < limit
        return self._build_result(allowed=allowed, limit=limit, count=count, now=now)


# ---------------------------------------------------------------------------
# Redis sliding window (ZSET; lazy redis.asyncio import)
# ---------------------------------------------------------------------------


class RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(
        self,
        redis: Redis,  # type: ignore[type-arg]
        limits: dict[str, int] | None = None,
        window_seconds: int = 60,
        key_prefix: str = "swarmline:ratelimit",
    ) -> None:
        self._redis = redis
        self._limits = limits or {}
        self._window_seconds = window_seconds
        self._key_prefix = key_prefix

    def _get_limit(self, endpoint_group: str) -> int:
        return self._limits.get(endpoint_group, _DEFAULT_LIMIT)

    def _key(self, key: str, endpoint_group: str) -> str:
        from urllib.parse import quote as _q  # injective join; safe='' encodes ':'

        return f"{self._key_prefix}:{_q(key, safe='')}:{_q(endpoint_group, safe='')}"

    async def check_limit(self, key: str, endpoint_group: str) -> RateLimitResult:
        now = datetime.now(tz=UTC)
        now_ts = time.time()
        cutoff = now_ts - self._window_seconds
        redis_key = self._key(key, endpoint_group)
        limit = self._get_limit(endpoint_group)

        # Use a UUID hex as the ZSET member so concurrent requests that share
        # the same time.time() float each create a DISTINCT entry.  The score
        # stays now_ts so zremrangebyscore time-window pruning is unchanged.
        member = uuid.uuid4().hex

        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, "-inf", cutoff)
        pipe.zcard(redis_key)
        pipe.zadd(redis_key, {member: now_ts})
        pipe.expire(redis_key, self._window_seconds + 1)
        results = await pipe.execute()

        count_before_add = results[1]
        if count_before_add >= limit:
            # Remove exactly the entry we just added — never a legitimate prior one.
            await self._redis.zrem(redis_key, member)
            remaining = 0
            allowed = False
        else:
            remaining = max(0, limit - count_before_add - 1)
            allowed = True

        reset_at = now + timedelta(seconds=self._window_seconds)
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
        )

    async def get_remaining(self, key: str, endpoint_group: str) -> RateLimitResult:
        # Read-only: zcount with exclusive-min counts only in-window members.
        # No zremrangebyscore — expired entries are pruned lazily by check_limit.
        now = datetime.now(tz=UTC)
        now_ts = time.time()
        cutoff = now_ts - self._window_seconds
        redis_key = self._key(key, endpoint_group)
        limit = self._get_limit(endpoint_group)

        # Exclusive lower bound "(cutoff" mirrors the check_limit window exactly
        # (check_limit prunes scores <= cutoff, so in-window = score > cutoff).
        count = await self._redis.zcount(redis_key, f"({cutoff}", "+inf")

        remaining = max(0, limit - count)
        reset_at = now + timedelta(seconds=self._window_seconds)
        return RateLimitResult(
            allowed=count < limit,
            limit=limit,
            remaining=remaining,
            reset_at=reset_at,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_rate_limiter(
    backend: str = "inmemory",
    *,
    redis_url: str | None = None,
    limits: dict[str, int] | None = None,
    window_seconds: int = 60,
    key_prefix: str = "swarmline:ratelimit",
) -> RateLimiterPort:
    """Create a rate limiter for the given backend.

    Args:
        backend: ``"inmemory"`` or ``"redis"``.
        redis_url: Required when ``backend="redis"``.
        limits: Per-endpoint-group request limits.
        window_seconds: Sliding window duration in seconds.
        key_prefix: Redis key prefix (ignored for inmemory).
            Callers should pass ``key_prefix="taskloom:ratelimit"`` to
            preserve an existing Redis key namespace.
    """
    if backend == "redis":
        # Validate BEFORE importing the optional dep: a missing redis_url must
        # raise ValueError even in environments without redis installed (I-160).
        if redis_url is None:
            raise ValueError("redis_url is required when backend='redis'")
        import redis.asyncio as aioredis  # ty: ignore[unresolved-import]  # noqa: PLC0415  # optional dep

        client = aioredis.from_url(redis_url)
        return RedisRateLimiter(
            redis=client,
            limits=limits,
            window_seconds=window_seconds,
            key_prefix=key_prefix,
        )
    return InMemoryRateLimiter(limits=limits, window_seconds=window_seconds)
