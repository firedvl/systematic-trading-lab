"""Exchange-session expectations for normalized daily and intraday bars."""

from __future__ import annotations

from datetime import UTC, date, datetime

import exchange_calendars as xcals  # type: ignore[import-untyped]

from .domain import Timeframe


def expected_sessions(
    start: datetime, end: datetime, calendar_name: str = "XNYS"
) -> tuple[date, ...]:
    """Return regular exchange sessions in the inclusive UTC date range."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("calendar range must use timezone-aware timestamps")
    if start > end:
        raise ValueError("calendar range start must not follow end")
    sessions = xcals.get_calendar(calendar_name).sessions_in_range(start.date(), end.date())
    return tuple(session.date() for session in sessions)


def expected_bar_timestamps(
    start: datetime,
    end: datetime,
    timeframe: Timeframe,
    calendar_name: str = "XNYS",
) -> tuple[datetime, ...]:
    """Return regular-session bar-open timestamps inside one inclusive UTC range."""
    if (
        start.tzinfo is None
        or start.utcoffset() != UTC.utcoffset(start)
        or end.tzinfo is None
        or end.utcoffset() != UTC.utcoffset(end)
    ):
        raise ValueError("calendar range must use UTC-aware timestamps")
    if start > end:
        raise ValueError("calendar range start must not follow end")
    if not timeframe.is_supported_intraday:
        raise ValueError("intraday bar schedule supports only 1m and 5m")

    calendar = xcals.get_calendar(calendar_name)
    intervals: list[datetime] = []
    for session in calendar.sessions_in_range(start.date(), end.date()):
        current = calendar.session_open(session).to_pydatetime()
        close = calendar.session_close(session).to_pydatetime()
        while current < close:
            if start <= current <= end:
                intervals.append(current)
            current += timeframe.duration
    return tuple(intervals)
