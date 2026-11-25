"""Cron expression parser and next-fire calculator for swarmline daemon.

This module is a generic, stdlib-only copy of the cron logic originally
authored for the taskloom product (not derived from hermes or any other
third-party project). It provides timezone-aware next-fire computation
compatible with standard Unix cron semantics.

Key semantics:
- Five-field format: minute hour day-of-month month day-of-week
- Field ranges: minute 0-59, hour 0-23, dom 1-31, month 1-12, dow 0-6 (0=Sunday)
- Sunday alias: 7 is accepted as Sunday in the day-of-week field
- OR semantics for dom/dow: when both are non-wildcard, a time slot matches
  if EITHER dom OR dow matches (Unix cron standard)
- next_schedule_due_at always returns a UTC-aware datetime

Public API:
    validate_cron_expression(cron_expr: str) -> None
    next_schedule_due_at(cron_expr: str, timezone: str, after: datetime) -> datetime
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_cron_expression(cron_expr: str) -> None:
    """Validate a cron expression string.

    Raises ValueError for:
    - Wrong number of fields (must be exactly 5)
    - Invalid field values (out-of-range, non-integer, bad step/range)
    """
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(
            f"Cron expression must contain exactly 5 fields, got {len(parts)}: {cron_expr!r}"
        )
    _parse_cron_fields(cron_expr)


def _parse_cron_fields(
    cron_expr: str,
) -> tuple[_CronField, _CronField, _CronField, _CronField, _CronField]:
    """Parse a 5-field cron expression into typed field descriptors."""
    minute, hour, day_of_month, month, day_of_week = cron_expr.split()
    return (
        _parse_cron_field(minute, 0, 59),
        _parse_cron_field(hour, 0, 23),
        _parse_cron_field(day_of_month, 1, 31),
        _parse_cron_field(month, 1, 12),
        _parse_cron_field(day_of_week, 0, 6, sunday_alias=True),
    )


@dataclass(slots=True, frozen=True)
class _CronField:
    """Parsed representation of one cron field.

    Attributes:
        allowed: The set of integer values that match this field.
        wildcard: True when the raw field expression is exactly ``*``.
            Used for dom/dow OR-semantics detection.
    """

    allowed: frozenset[int]
    wildcard: bool


def _parse_cron_field(
    expression: str,
    min_value: int,
    max_value: int,
    *,
    sunday_alias: bool = False,
) -> _CronField:
    """Parse a single cron field expression (may contain commas for lists)."""
    if not expression:
        raise ValueError("Cron field must not be blank")
    wildcard = expression == "*"
    values: set[int] = set()
    for token in expression.split(","):
        values.update(
            _expand_cron_token(
                token,
                min_value,
                max_value,
                sunday_alias=sunday_alias,
            )
        )
    return _CronField(allowed=frozenset(values), wildcard=wildcard)


def _expand_cron_token(
    token: str,
    min_value: int,
    max_value: int,
    *,
    sunday_alias: bool = False,
) -> set[int]:
    """Expand a single cron token to a set of matching integers.

    Handles:
    - ``*``            → full range [min_value, max_value]
    - ``*/N``          → every Nth value starting from min_value
    - ``a-b``          → inclusive range a to b
    - ``a-b/N``        → every Nth value within range a to b
    - ``N``            → single value
    """
    base = token
    step = 1
    if "/" in token:
        base, step_expr = token.split("/", 1)
        try:
            step = int(step_expr)
        except ValueError as error:
            raise ValueError(
                f"Cron step must be an integer, got {step_expr!r}"
            ) from error
        if step <= 0:
            raise ValueError(f"Cron step must be positive, got {step}")

    if base == "*":
        start, end = min_value, max_value
    elif "-" in base:
        start_expr, end_expr = base.split("-", 1)
        start = _parse_cron_value(
            start_expr,
            min_value,
            max_value,
            sunday_alias=sunday_alias,
        )
        end = _parse_cron_value(
            end_expr,
            min_value,
            max_value,
            sunday_alias=sunday_alias,
        )
        if end < start:
            raise ValueError(f"Cron range end must be >= start, got {start}-{end}")
    else:
        value = _parse_cron_value(
            base,
            min_value,
            max_value,
            sunday_alias=sunday_alias,
        )
        start, end = value, value

    return set(range(start, end + 1, step))


def _parse_cron_value(
    value_expr: str,
    min_value: int,
    max_value: int,
    *,
    sunday_alias: bool = False,
) -> int:
    """Parse and validate a single integer cron value."""
    try:
        value = int(value_expr)
    except ValueError as error:
        raise ValueError(
            f"Cron field must be an integer, got {value_expr!r}"
        ) from error
    if sunday_alias and value == 7:
        value = 0
    if value < min_value or value > max_value:
        raise ValueError(
            f"Cron field value {value} is out of range [{min_value}, {max_value}]"
        )
    return value


def _cron_weekday(dt: datetime) -> int:
    """Convert Python weekday (Mon=0) to cron weekday (Sun=0)."""
    return (dt.weekday() + 1) % 7


def _matches_cron_fields(
    candidate: datetime,
    minute: _CronField,
    hour: _CronField,
    day_of_month: _CronField,
    month: _CronField,
    day_of_week: _CronField,
) -> bool:
    """Return True if ``candidate`` matches all five cron fields.

    Unix cron OR semantics for dom/dow:
    - Both wildcard: always match the day.
    - Only dom wildcard: match by day-of-week.
    - Only dow wildcard: match by day-of-month.
    - Neither wildcard: match if EITHER dom OR dow matches.
    """
    if candidate.minute not in minute.allowed:
        return False
    if candidate.hour not in hour.allowed:
        return False
    if candidate.month not in month.allowed:
        return False

    day_match = candidate.day in day_of_month.allowed
    weekday_match = _cron_weekday(candidate) in day_of_week.allowed

    if day_of_month.wildcard and day_of_week.wildcard:
        return True
    if day_of_month.wildcard:
        return weekday_match
    if day_of_week.wildcard:
        return day_match
    return day_match or weekday_match


def _resolve_candidate_to_utc(candidate: datetime) -> datetime:
    """Convert a matched local candidate to UTC with conventional DST handling.

    Existent wall times (normal or fold-ambiguous) convert directly — fold=0
    yields the first occurrence (fire once). A non-existent (spring-forward gap)
    wall time fires at the gap boundary: advance to the first existent wall
    minute and fire there (Vixie/systemd convention).
    """
    tz = candidate.tzinfo
    naive = candidate.replace(tzinfo=None)
    if candidate.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == naive:
        return candidate.astimezone(UTC)  # existent — unchanged
    probe = candidate
    for _ in range(180):  # a DST gap never exceeds a couple of hours
        probe = probe + timedelta(minutes=1)
        round_trip = probe.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
        if round_trip == probe.replace(tzinfo=None):
            return probe.astimezone(UTC)
    return candidate.astimezone(UTC)  # defensive fallback (unreachable in practice)


def next_schedule_due_at(cron_expr: str, timezone: str, after: datetime) -> datetime:
    """Compute the next UTC datetime when ``cron_expr`` fires after ``after``.

    Args:
        cron_expr: Five-field cron expression string.
        timezone: IANA timezone name (e.g. ``"UTC"``, ``"America/New_York"``).
        after: Reference datetime (tz-aware or naive UTC). The first candidate
            is one minute after ``after`` rounded down to the minute.

    Returns:
        A UTC-aware datetime of the next scheduled occurrence.

    Raises:
        ValueError: If ``cron_expr`` is invalid, ``timezone`` is unknown, or
            the expression has no valid occurrence within the next 366 days.
    """
    minute, hour, day_of_month, month, day_of_week = _parse_cron_fields(cron_expr)
    try:
        local_timezone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown timezone: {timezone!r}") from error

    after_utc = after.astimezone(UTC)
    localized_after = after.astimezone(local_timezone)
    candidate = localized_after.replace(second=0, microsecond=0) + timedelta(minutes=1)

    for _ in range(366 * 24 * 60):
        if _matches_cron_fields(
            candidate,
            minute,
            hour,
            day_of_month,
            month,
            day_of_week,
        ):
            resolved = _resolve_candidate_to_utc(candidate)
            if resolved > after_utc:
                return resolved
        candidate += timedelta(minutes=1)

    raise ValueError(
        f"Cron expression {cron_expr!r} has no valid future occurrence "
        f"within the next 366 days"
    )
