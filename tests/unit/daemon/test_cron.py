"""Unit tests for swarmline.daemon.cron — cron parser + next-fire calculator.

Covers:
- Field parsing: wildcards, steps (*/N), ranges (a-b), range+step (a-b/N), plain int
- Sunday alias: both 0 and 7 map to Sunday (day-of-week only)
- Validation: wrong field count, step ≤ 0, end < start, non-integer tokens → ValueError
- _matches_cron_fields: OR semantics when both dom and dow are non-wildcard
- next_schedule_due_at: tz-aware, correct UTC output, DST boundary, bad tz → ValueError
- Daemon cron_at: registers task, first next_run matches cron, cron_expr in ScheduledTaskInfo
- Daemon _tick cron branch: reschedules to NEXT fire after triggering
- DaemonRunner.schedule_cron: delegates to scheduler.cron_at
- Byte-identical default regression: existing interval/once paths unchanged when no cron tasks
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest

from swarmline.daemon.cron import (
    _CronField,
    _expand_cron_token,
    _matches_cron_fields,
    _parse_cron_fields,
    next_schedule_due_at,
    validate_cron_expression,
)
from swarmline.daemon.scheduler import Scheduler


# ---------------------------------------------------------------------------
# validate_cron_expression
# ---------------------------------------------------------------------------


class TestValidateCronExpression:
    def test_valid_wildcard_all_passes(self) -> None:
        validate_cron_expression("* * * * *")  # must not raise

    def test_valid_specific_passes(self) -> None:
        validate_cron_expression("0 9 * * 1")

    def test_wrong_field_count_4_raises(self) -> None:
        with pytest.raises(ValueError, match="5 fields"):
            validate_cron_expression("* * * *")

    def test_wrong_field_count_6_raises(self) -> None:
        with pytest.raises(ValueError, match="5 fields"):
            validate_cron_expression("0 0 * * * *")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_cron_expression("")


# ---------------------------------------------------------------------------
# _expand_cron_token
# ---------------------------------------------------------------------------


class TestExpandCronToken:
    def test_wildcard_returns_full_range(self) -> None:
        result = _expand_cron_token("*", 0, 59)
        assert result == set(range(0, 60))

    def test_step_every_15_minutes(self) -> None:
        result = _expand_cron_token("*/15", 0, 59)
        assert result == {0, 15, 30, 45}

    def test_range_1_to_5(self) -> None:
        result = _expand_cron_token("1-5", 0, 59)
        assert result == {1, 2, 3, 4, 5}

    def test_range_with_step(self) -> None:
        result = _expand_cron_token("0-30/10", 0, 59)
        assert result == {0, 10, 20, 30}

    def test_plain_int(self) -> None:
        result = _expand_cron_token("30", 0, 59)
        assert result == {30}

    def test_step_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            _expand_cron_token("*/0", 0, 59)

    def test_step_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            _expand_cron_token("*/-1", 0, 59)

    def test_range_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match=">="):
            _expand_cron_token("5-3", 0, 59)

    def test_non_integer_step_raises(self) -> None:
        with pytest.raises(ValueError):
            _expand_cron_token("*/foo", 0, 59)

    def test_non_integer_plain_raises(self) -> None:
        with pytest.raises(ValueError):
            _expand_cron_token("foo", 0, 59)

    def test_sunday_alias_7_maps_to_0(self) -> None:
        result = _expand_cron_token("7", 0, 6, sunday_alias=True)
        assert result == {0}

    def test_sunday_alias_0_works_too(self) -> None:
        result = _expand_cron_token("0", 0, 6, sunday_alias=True)
        assert result == {0}

    def test_sunday_alias_7_not_applied_without_flag(self) -> None:
        # Without sunday_alias flag, 7 is out of range [0,6]
        with pytest.raises(ValueError):
            _expand_cron_token("7", 0, 6, sunday_alias=False)

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError):
            _expand_cron_token("60", 0, 59)


# ---------------------------------------------------------------------------
# _parse_cron_fields — field order
# ---------------------------------------------------------------------------


class TestParseCronFields:
    def test_field_order_minute_first(self) -> None:
        # "15 * * * *" → minute field has allowed={15}
        minute, hour, dom, month, dow = _parse_cron_fields("15 * * * *")
        assert 15 in minute.allowed
        assert minute.wildcard is False

    def test_wildcard_field_is_marked(self) -> None:
        minute, hour, dom, month, dow = _parse_cron_fields("* * * * *")
        assert minute.wildcard is True
        assert hour.wildcard is True
        assert dom.wildcard is True
        assert month.wildcard is True
        assert dow.wildcard is True

    def test_day_of_week_sunday_alias_in_fields(self) -> None:
        # "* * * * 7" should map to sunday (0)
        _, _, _, _, dow = _parse_cron_fields("* * * * 7")
        assert 0 in dow.allowed
        assert dow.wildcard is False

    def test_comma_separated_values(self) -> None:
        minute, _, _, _, _ = _parse_cron_fields("0,15,30,45 * * * *")
        assert minute.allowed == frozenset({0, 15, 30, 45})
        assert minute.wildcard is False


# ---------------------------------------------------------------------------
# _matches_cron_fields
# ---------------------------------------------------------------------------


def _field(allowed: set[int], wildcard: bool = False) -> _CronField:
    return _CronField(allowed=frozenset(allowed), wildcard=wildcard)


def _wildcard_field(min_v: int, max_v: int) -> _CronField:
    return _CronField(allowed=frozenset(range(min_v, max_v + 1)), wildcard=True)


class TestMatchesCronFields:
    def _candidate(
        self, year: int, month: int, day: int, hour: int, minute: int
    ) -> datetime:
        return datetime(year, month, day, hour, minute, tzinfo=UTC)

    def test_all_wildcards_always_true(self) -> None:
        dt = self._candidate(2024, 6, 15, 12, 30)
        assert _matches_cron_fields(
            dt,
            minute=_wildcard_field(0, 59),
            hour=_wildcard_field(0, 23),
            day_of_month=_wildcard_field(1, 31),
            month=_wildcard_field(1, 12),
            day_of_week=_wildcard_field(0, 6),
        )

    def test_minute_mismatch_returns_false(self) -> None:
        dt = self._candidate(2024, 6, 15, 12, 30)
        assert not _matches_cron_fields(
            dt,
            minute=_field({15}),
            hour=_wildcard_field(0, 23),
            day_of_month=_wildcard_field(1, 31),
            month=_wildcard_field(1, 12),
            day_of_week=_wildcard_field(0, 6),
        )

    def test_dom_wildcard_only_uses_dow(self) -> None:
        # 2024-06-15 is a Saturday (dow=6 in 0=Sun convention)
        dt = self._candidate(2024, 6, 15, 12, 0)
        # dom wildcard, dow non-wildcard set to Saturday (6)
        assert _matches_cron_fields(
            dt,
            minute=_wildcard_field(0, 59),
            hour=_wildcard_field(0, 23),
            day_of_month=_wildcard_field(1, 31),
            month=_wildcard_field(1, 12),
            day_of_week=_field({6}),  # wildcard=False
        )

    def test_dow_wildcard_only_uses_dom(self) -> None:
        dt = self._candidate(2024, 6, 15, 12, 0)
        assert _matches_cron_fields(
            dt,
            minute=_wildcard_field(0, 59),
            hour=_wildcard_field(0, 23),
            day_of_month=_field({15}),
            month=_wildcard_field(1, 12),
            day_of_week=_wildcard_field(0, 6),
        )

    def test_neither_wildcard_or_semantics_dom_matches(self) -> None:
        # 2024-06-15 is day 15 of month (dom matches), dow=6 (Saturday); dow set to Monday (1) only
        dt = self._candidate(2024, 6, 15, 12, 0)
        assert _matches_cron_fields(
            dt,
            minute=_wildcard_field(0, 59),
            hour=_wildcard_field(0, 23),
            day_of_month=_field({15}),  # non-wildcard, dom matches
            month=_wildcard_field(1, 12),
            day_of_week=_field({1}),  # non-wildcard, dow doesn't match
        )

    def test_neither_wildcard_or_semantics_dow_matches(self) -> None:
        # 2024-06-15 is Saturday (dow=6), dom set to 20 only → dow match suffices
        dt = self._candidate(2024, 6, 15, 12, 0)
        assert _matches_cron_fields(
            dt,
            minute=_wildcard_field(0, 59),
            hour=_wildcard_field(0, 23),
            day_of_month=_field({20}),  # non-wildcard, dom doesn't match
            month=_wildcard_field(1, 12),
            day_of_week=_field({6}),  # non-wildcard, Saturday matches
        )

    def test_neither_wildcard_neither_matches_false(self) -> None:
        # dom=20 doesn't match day 15, dow=1 (Monday) doesn't match Saturday
        dt = self._candidate(2024, 6, 15, 12, 0)
        assert not _matches_cron_fields(
            dt,
            minute=_wildcard_field(0, 59),
            hour=_wildcard_field(0, 23),
            day_of_month=_field({20}),
            month=_wildcard_field(1, 12),
            day_of_week=_field({1}),
        )


# ---------------------------------------------------------------------------
# next_schedule_due_at
# ---------------------------------------------------------------------------


class TestNextScheduleDueAt:
    def test_every_minute_returns_next_minute(self) -> None:
        after = datetime(2024, 1, 15, 10, 0, 30, tzinfo=UTC)
        result = next_schedule_due_at("* * * * *", "UTC", after)
        # After 10:00:30, the next minute-boundary is 10:01:00
        assert result == datetime(2024, 1, 15, 10, 1, 0, tzinfo=UTC)

    def test_specific_daily_time(self) -> None:
        # Every day at 09:30 UTC; after 2024-01-15 09:00:00 → 09:30 same day
        after = datetime(2024, 1, 15, 9, 0, 0, tzinfo=UTC)
        result = next_schedule_due_at("30 9 * * *", "UTC", after)
        assert result == datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)

    def test_specific_daily_time_past_fires_next_day(self) -> None:
        # after is already past 09:30 → next fire is next day
        after = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        result = next_schedule_due_at("30 9 * * *", "UTC", after)
        assert result == datetime(2024, 1, 16, 9, 30, 0, tzinfo=UTC)

    def test_timezone_aware_new_york(self) -> None:
        # "0 9 * * *" daily at 09:00 New York
        # After 2024-01-15 14:01 UTC (= 09:01 EST = UTC-5)
        # Next fire: 2024-01-16 09:00 EST = 2024-01-16 14:00 UTC
        after = datetime(2024, 1, 15, 14, 1, 0, tzinfo=UTC)
        result = next_schedule_due_at("0 9 * * *", "America/New_York", after)
        assert result == datetime(2024, 1, 16, 14, 0, 0, tzinfo=UTC)

    def test_step_every_15_minutes(self) -> None:
        # */15 * * * *; after 10:07 → next is 10:15
        after = datetime(2024, 1, 15, 10, 7, 0, tzinfo=UTC)
        result = next_schedule_due_at("*/15 * * * *", "UTC", after)
        assert result == datetime(2024, 1, 15, 10, 15, 0, tzinfo=UTC)

    def test_hour_crossing(self) -> None:
        # 0 * * * * → every hour on the hour; after 10:30 → 11:00
        after = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = next_schedule_due_at("0 * * * *", "UTC", after)
        assert result == datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC)

    def test_result_is_utc(self) -> None:
        after = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        result = next_schedule_due_at("* * * * *", "UTC", after)
        assert result.tzinfo is UTC

    def test_bad_timezone_raises_value_error(self) -> None:
        after = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="[Uu]nknown|[Tt]imezone|not found"):
            next_schedule_due_at("* * * * *", "Not/AReal/Timezone", after)

    def test_bad_expression_raises_value_error(self) -> None:
        after = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError):
            next_schedule_due_at("* * * *", "UTC", after)

    def test_impossible_expression_feb_31_raises(self) -> None:
        # Feb 31 never exists → no valid occurrence in scan window
        after = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError):
            next_schedule_due_at("0 0 31 2 *", "UTC", after)


# ---------------------------------------------------------------------------
# next_schedule_due_at — DST correctness (CONVENTIONAL Vixie/systemd semantics)
#
# America/New_York 2026 transitions:
#   spring-forward 2026-03-08 02:00 EST → 03:00 EDT (wall 02:00-02:59 does NOT exist)
#   fall-back      2026-11-01 02:00 EDT → 01:00 EST (wall 01:00-01:59 occurs TWICE)
# ---------------------------------------------------------------------------


class TestNextScheduleDueAtDST:
    def test_spring_forward_gap_fires_at_boundary(self) -> None:
        """A wall time in the skipped spring-forward hour fires once at the
        gap boundary (first existent wall minute = start of the new offset hour)."""
        # 06:00Z = 01:00 EST (just before the gap); 02:30 wall does not exist.
        # Conventional fix: fire at 03:00 EDT = 07:00Z (the gap boundary).
        after = datetime(2026, 3, 8, 6, 0, tzinfo=UTC)
        result = next_schedule_due_at("30 2 * * *", "America/New_York", after)
        assert result == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)

    def test_fall_back_fold_fires_once_first_occurrence(self) -> None:
        """An ambiguous fall-back wall time fires once, at the FIRST occurrence."""
        # 05:00Z = 01:00 EDT (first 01:00 occurrence). Next match 01:30 EDT = 05:30Z.
        after = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
        result = next_schedule_due_at("30 1 * * *", "America/New_York", after)
        assert result == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)

    def test_fall_back_fold_does_not_double_fire(self) -> None:
        """A follow-up call from the first 01:30 must NOT return the second 01:30
        (06:30Z) — it jumps to the next day's 01:30 (no duplicate firing)."""
        after = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
        result = next_schedule_due_at("30 1 * * *", "America/New_York", after)
        # Skips the duplicate fold occurrence; lands on the next day (EST = 06:30Z).
        assert result == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
        assert result > datetime(2026, 11, 1, 6, 30, tzinfo=UTC)

    def test_normal_day_unchanged(self) -> None:
        """Existent, unambiguous wall times convert directly (common-path regression)."""
        # 2026-01-15 is a plain EST day; noon EST = 17:00Z.
        after = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
        result = next_schedule_due_at("0 12 * * *", "America/New_York", after)
        assert result == datetime(2026, 1, 15, 17, 0, tzinfo=UTC)

    def test_fold_start_inside_second_hour_returns_next_day(self) -> None:
        """When ``after`` is inside the SECOND (fold=1) fall-back hour, the next
        occurrence must be STRICTLY AFTER ``after`` in UTC.

        06:00Z = the second 01:00 (EST, fold=1). The conventional fire-once first
        01:30 (05:30Z) already passed, so the next fire is the next-day 01:30 EST
        (2026-11-02 06:30Z) — never the past 05:30Z instant.
        """
        after = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
        result = next_schedule_due_at("30 1 * * *", "America/New_York", after)
        assert result == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
        assert result > after

    def test_fold_start_between_occurrences_returns_next_day(self) -> None:
        """``after`` just after the first 01:30 (05:45Z = 01:45 EDT): the first
        01:30 already fired, so the next fire is the next-day 01:30 EST (06:30Z),
        firing once (no duplicate at the second 01:30)."""
        after = datetime(2026, 11, 1, 5, 45, tzinfo=UTC)
        result = next_schedule_due_at("30 1 * * *", "America/New_York", after)
        assert result == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
        assert result > after


# ---------------------------------------------------------------------------
# Daemon: Scheduler.cron_at
# ---------------------------------------------------------------------------


class TestSchedulerCronAt:
    def test_cron_at_returns_name(self) -> None:
        sched = Scheduler()
        name = sched.cron_at("*/15 * * * *", "UTC", _noop, name="cron-test")
        assert name == "cron-test"

    def test_cron_at_auto_name_prefix(self) -> None:
        sched = Scheduler()
        name = sched.cron_at("*/15 * * * *", "UTC", _noop)
        assert name.startswith("cron-")

    def test_cron_at_bad_expr_raises(self) -> None:
        sched = Scheduler()
        with pytest.raises(ValueError):
            sched.cron_at("bad expr", "UTC", _noop)

    def test_cron_at_bad_tz_raises(self) -> None:
        sched = Scheduler()
        with pytest.raises(ValueError):
            sched.cron_at("* * * * *", "Not/Valid", _noop)

    def test_cron_at_first_next_run_is_in_future(self) -> None:
        sched = Scheduler()
        sched.cron_at("*/15 * * * *", "UTC", _noop, name="c1")

        tasks = sched.list_tasks()
        task = next(t for t in tasks if t.name == "c1")
        # next_run_at is a wall-clock float; it should be > now and < 15 min from now
        assert task.next_run_at > time.time()
        assert task.next_run_at < time.time() + 15 * 60

    def test_cron_at_task_info_has_cron_expr(self) -> None:
        sched = Scheduler()
        sched.cron_at("30 9 * * *", "UTC", _noop, name="daily")
        tasks = sched.list_tasks()
        task = next(t for t in tasks if t.name == "daily")
        assert task.cron_expr == "30 9 * * *"

    def test_cron_at_interval_seconds_is_none(self) -> None:
        sched = Scheduler()
        sched.cron_at("* * * * *", "UTC", _noop, name="c")
        tasks = sched.list_tasks()
        task = next(t for t in tasks if t.name == "c")
        assert task.interval_seconds is None


# ---------------------------------------------------------------------------
# Daemon: _tick cron reschedule
# ---------------------------------------------------------------------------


class TestTickCronReschedule:
    async def test_cron_task_fires_and_reschedules_not_same_minute(self) -> None:
        """After a cron task fires, next_run must advance to the NEXT occurrence."""
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)
        # Schedule task to fire every minute; we'll force next_run in the past
        sched.cron_at("* * * * *", "UTC", counter.increment, name="c")

        # Force the task's next_run to "now" so it fires immediately
        task_internal = sched._tasks["c"]
        task_internal.next_run = time.monotonic() - 0.1

        # Run one tick then yield to let fire-and-forget asyncio tasks complete
        await sched._tick()
        await asyncio.sleep(0)

        assert counter.value == 1
        # After firing, the cron task should still be present and rescheduled
        assert "c" in sched._tasks
        # next_run must be strictly in the future (rescheduled, not immediate)
        # and within 60 s (next minute boundary for "* * * * *")
        now = time.monotonic()
        assert sched._tasks["c"].next_run > now
        assert sched._tasks["c"].next_run <= now + 60

    async def test_cron_task_not_removed_after_fire(self) -> None:
        """Cron tasks must remain active after firing (unlike one-shot tasks)."""
        sched = Scheduler(tick_interval=0.05)
        sched.cron_at("* * * * *", "UTC", _noop, name="c")
        sched._tasks["c"].next_run = time.monotonic() - 0.1

        await sched._tick()

        assert "c" in sched._tasks
        assert sched._tasks["c"].active is True


# ---------------------------------------------------------------------------
# Byte-identical default regression: interval/once unchanged
# ---------------------------------------------------------------------------


class TestByteIdenticalDefault:
    def test_interval_task_info_no_cron_expr(self) -> None:
        sched = Scheduler()
        sched.every(60, _noop, name="periodic")
        tasks = sched.list_tasks()
        t = next(x for x in tasks if x.name == "periodic")
        assert t.cron_expr is None
        assert t.interval_seconds == 60.0

    def test_once_at_task_info_no_cron_expr(self) -> None:
        sched = Scheduler()
        sched.once_at(time.time() + 100, _noop, name="once")
        tasks = sched.list_tasks()
        t = next(x for x in tasks if x.name == "once")
        assert t.cron_expr is None
        assert t.interval_seconds is None

    async def test_interval_task_still_fires(self) -> None:
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)
        sched.every(0.05, counter.increment, name="cnt")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.3, stop.set)
        await sched.run_until(stop)

        assert counter.value >= 2

    async def test_once_task_still_fires_once(self) -> None:
        counter = _Counter()
        sched = Scheduler(tick_interval=0.05)
        sched.once_at(time.time() + 0.01, counter.increment, name="once")

        stop = asyncio.Event()
        asyncio.get_event_loop().call_later(0.3, stop.set)
        await sched.run_until(stop)

        assert counter.value == 1


# ---------------------------------------------------------------------------
# DaemonRunner.schedule_cron
# ---------------------------------------------------------------------------


class TestDaemonRunnerScheduleCron:
    def test_schedule_cron_returns_name(self) -> None:
        from swarmline.daemon.runner import DaemonRunner
        from swarmline.daemon.types import DaemonConfig

        runner = DaemonRunner(
            config=DaemonConfig(name="test-daemon", allow_unauthenticated_local=True)
        )
        name = runner.schedule_cron("*/15 * * * *", "UTC", _noop, name="cron-task")
        assert name == "cron-task"

    def test_schedule_cron_registers_on_scheduler(self) -> None:
        from swarmline.daemon.runner import DaemonRunner
        from swarmline.daemon.types import DaemonConfig

        runner = DaemonRunner(
            config=DaemonConfig(name="test-daemon", allow_unauthenticated_local=True)
        )
        runner.schedule_cron("0 9 * * *", "UTC", _noop, name="daily")
        tasks = runner.scheduler.list_tasks()
        names = {t.name for t in tasks}
        assert "daily" in names


# ---------------------------------------------------------------------------
# Protocol: RunnableScheduler.cron_at
# ---------------------------------------------------------------------------


class TestRunnableSchedulerProtocol:
    def test_scheduler_implements_runnable_scheduler_with_cron_at(self) -> None:
        from swarmline.daemon.protocols import RunnableScheduler

        sched = Scheduler()
        assert isinstance(sched, RunnableScheduler)
        assert hasattr(sched, "cron_at")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _noop() -> None:
    pass


class _Counter:
    def __init__(self) -> None:
        self.value = 0

    async def increment(self) -> None:
        self.value += 1
