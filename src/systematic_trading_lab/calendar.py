"""Exchange-session expectations for normalized daily bars."""

from __future__ import annotations

from datetime import date, datetime

import exchange_calendars as xcals  # type: ignore[import-untyped]


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
