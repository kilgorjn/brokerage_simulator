"""US equity market hours (NYSE/NASDAQ schedule).

Note: holiday detection is not implemented. If you need to close the market
on holidays, maintain a holiday set and check it in is_market_open().
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import MARKET_CLOSE_PROCESSING_DELAY_MINUTES, MARKET_OPEN_PROCESSING_DELAY_MINUTES

EASTERN = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)


def is_market_open(at: datetime | None = None) -> bool:
    """Return True if the US equity market is open at the given UTC time (default: now)."""
    utc = (at or datetime.now(timezone.utc))
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)
    et = utc.astimezone(EASTERN)
    if et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return _OPEN <= et.time() < _CLOSE


def next_market_open(at: datetime | None = None) -> datetime:
    """Return the UTC datetime of the next market open after the given time."""
    utc = (at or datetime.now(timezone.utc))
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)
    et = utc.astimezone(EASTERN)

    # Start from today's open; if we're already past it, move to tomorrow
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et >= candidate:
        candidate += timedelta(days=1)

    # Skip weekends
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    return candidate.astimezone(timezone.utc)


def next_market_close(at: datetime | None = None) -> datetime:
    """Return the UTC datetime of the next market close (16:00 ET) after the given time."""
    utc = (at or datetime.now(timezone.utc))
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)
    et = utc.astimezone(EASTERN)

    # Start from today's close; if we're already past it, move to tomorrow
    candidate = et.replace(hour=16, minute=0, second=0, microsecond=0)
    if et >= candidate:
        candidate += timedelta(days=1)

    # Skip weekends
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    return candidate.astimezone(timezone.utc)


def earliest_order_processing_time(at: datetime | None = None) -> datetime:
    """Return the UTC datetime when order processing begins after market opens.

    Orders are delayed by MARKET_OPEN_PROCESSING_DELAY_MINUTES to allow quotes to stabilize.
    If not currently in market hours, returns the next market open + delay.
    """
    utc = (at or datetime.now(timezone.utc))
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)

    # Get today's market open in ET
    et = utc.astimezone(EASTERN)
    market_open = et.replace(hour=9, minute=30, second=0, microsecond=0)

    # If we're before today's open, use today's; otherwise use tomorrow's
    if et < market_open:
        pass  # use today's
    elif et.weekday() < 5:  # weekday and after today's open
        market_open += timedelta(days=1)
    else:
        market_open += timedelta(days=1)

    # Skip weekends
    while market_open.weekday() >= 5:
        market_open += timedelta(days=1)

    # Add the processing delay
    earliest = market_open + timedelta(minutes=MARKET_OPEN_PROCESSING_DELAY_MINUTES)
    return earliest.astimezone(timezone.utc)


def latest_order_processing_time(at: datetime | None = None) -> datetime:
    """Return the UTC datetime when order processing stops after market close.

    Orders can continue to fill for MARKET_CLOSE_PROCESSING_DELAY_MINUTES after close
    to allow traders to capitalize on end-of-day volatility.
    """
    utc = (at or datetime.now(timezone.utc))
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)

    # Get today's market close in ET
    et = utc.astimezone(EASTERN)
    market_close = et.replace(hour=16, minute=0, second=0, microsecond=0)

    # If we're before today's close, use today's; otherwise use tomorrow's
    if et < market_close:
        pass  # use today's
    elif et.weekday() < 5:  # weekday and after today's close
        market_close += timedelta(days=1)
    else:
        market_close += timedelta(days=1)

    # Skip weekends
    while market_close.weekday() >= 5:
        market_close += timedelta(days=1)

    # Add the post-close processing delay
    latest = market_close + timedelta(minutes=MARKET_CLOSE_PROCESSING_DELAY_MINUTES)
    return latest.astimezone(timezone.utc)
