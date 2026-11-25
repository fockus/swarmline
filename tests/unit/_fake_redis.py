"""Shared async fake-Redis harness for ratelimit / Redis-backed tests.

A minimal in-process double of the subset of async Redis used by
``swarmline.runtime.ratelimit.RedisRateLimiter`` (and reusable by any future
Redis-backed test). Mirrors Redis ZSET semantics closely enough to expose the
bugs the rate-limiter tests guard against:

* ``_FakeZSet`` stores a ``member -> score`` dict so that ``zadd`` overwrites of
  the same member are visible in ``zcard`` (a list-based fake would hide the
  timestamp-collision bug).
* ``_FakePipeline`` queues ZSET ops and replays them in ``execute()``.
* ``_FakeRedis`` exposes ``pipeline()``, ``zrem`` and a read-only ``zcount``.

This module is intentionally prefixed with ``_`` so pytest does not collect it
as a test module; it lives in ``tests/unit/`` (which is on ``sys.path`` under
pytest's default prepend import mode) and is imported directly by test modules.
"""

from __future__ import annotations


class _FakeZSet:
    """A minimal in-process sorted-set that mirrors Redis ZSET semantics."""

    def __init__(self) -> None:
        self._data: dict[str, float] = {}  # member -> score

    def zadd(self, mapping: dict[str, float]) -> None:
        self._data.update(mapping)  # overwrites existing member, same as Redis

    def zcard(self) -> int:
        return len(self._data)

    def zremrangebyscore(self, min_score: float | str, max_score: float | str) -> None:
        lo = float("-inf") if min_score == "-inf" else float(min_score)
        hi = float("inf") if max_score == "+inf" else float(max_score)
        remove = [m for m, s in self._data.items() if lo <= s <= hi]
        for m in remove:
            del self._data[m]

    def zrem(self, *members: str) -> None:
        for m in members:
            self._data.pop(m, None)

    def member_count(self) -> int:
        return len(self._data)


class _FakePipeline:
    """Queues operations on a shared _FakeZSet; execute() returns results."""

    def __init__(self, zsets: dict[str, _FakeZSet]) -> None:
        self._zsets = zsets
        self._ops: list[tuple] = []

    def _get(self, key: str) -> _FakeZSet:
        if key not in self._zsets:
            self._zsets[key] = _FakeZSet()
        return self._zsets[key]

    def zremrangebyscore(self, key: str, lo: float | str, hi: float | str) -> None:
        self._ops.append(("zremrangebyscore", key, lo, hi))

    def zcard(self, key: str) -> None:
        self._ops.append(("zcard", key))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self._ops.append(("zadd", key, mapping))

    def expire(self, key: str, ttl: int) -> None:  # no-op
        self._ops.append(("expire", key, ttl))

    async def execute(self) -> list:
        results = []
        for op in self._ops:
            match op[0]:
                case "zremrangebyscore":
                    self._get(op[1]).zremrangebyscore(op[2], op[3])
                    results.append(None)
                case "zcard":
                    results.append(self._get(op[1]).zcard())
                case "zadd":
                    self._get(op[1]).zadd(op[2])
                    results.append(1)
                case "expire":
                    results.append(True)
                case _:
                    results.append(None)
        return results


class _FakeRedis:
    """Minimal async Redis double with ZSET semantics for rate-limit tests."""

    def __init__(self) -> None:
        self._zsets: dict[str, _FakeZSet] = {}

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self._zsets)

    async def zrem(self, key: str, *members: str) -> None:
        if key in self._zsets:
            self._zsets[key].zrem(*members)

    async def zcount(
        self, key: str, min_score: str | float, max_score: str | float
    ) -> int:
        """Read-only count of members with score in [min_score, max_score].

        Supports ``(X`` exclusive-min prefix and ``"+inf"``/``"-inf"`` sentinels.
        Does NOT mutate the ZSET.
        """
        if key not in self._zsets:
            return 0

        def _parse(s: str | float) -> tuple[float, bool]:
            """Return (value, exclusive)."""
            if isinstance(s, (int, float)):
                return float(s), False
            if s == "-inf":
                return float("-inf"), False
            if s == "+inf":
                return float("inf"), False
            if s.startswith("("):
                return float(s[1:]), True
            return float(s), False

        lo, lo_excl = _parse(min_score)
        hi, hi_excl = _parse(max_score)
        count = 0
        for score in self._zsets[key]._data.values():
            lo_ok = score > lo if lo_excl else score >= lo
            hi_ok = score < hi if hi_excl else score <= hi
            if lo_ok and hi_ok:
                count += 1
        return count

    def get_zset(self, key: str) -> _FakeZSet | None:
        return self._zsets.get(key)
