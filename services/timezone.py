"""The household's time zone, decided in ONE place.

Rosie used to repeat this lookup in five files, each with a silent fallback: if
the IANA time-zone database wasn't installed, it quietly used the machine's
*current local offset* instead. That fallback is wrong twice over:

  * on a server whose clock is UTC (a container, say) every scheduled time came
    out in UTC; and
  * even on a correctly-set machine it is a FIXED offset captured at startup, so
    when clocks change (daylight saving) bookings are an hour off until Rosie is
    restarted.

The fix for both is the same - have the database. `tzdata` is in requirements.txt
(`pip install -r requirements.txt`). This module still falls back so Rosie keeps
running, but it now says so loudly, and `describe_timezone` lets the startup
banner show what is really in use.
"""

import logging
import os
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"


@lru_cache(maxsize=None)
def _resolve(name: str):
    """Return (tzinfo, warning-or-None) for an IANA zone name. Cached, so the
    warning is logged once, not once per module that imports it."""
    try:
        return ZoneInfo(name), None
    except (ZoneInfoNotFoundError, ValueError):
        fallback = datetime.now().astimezone().tzinfo
        warning = (
            f"Time zone '{name}' is not available (the tz database is missing or the name is "
            f"wrong). Falling back to a FIXED offset ({fallback}) - times will be wrong "
            "after the next daylight-saving change, or immediately if this machine runs in UTC. "
            "Fix: `pip install tzdata` (it is in requirements.txt), check HOUSEHOLD_TIMEZONE, "
            "then restart Rosie."
        )
        logger.warning(warning)
        return fallback, warning


def household_timezone():
    """The tzinfo to use for every household-local time."""
    return _resolve(os.getenv("HOUSEHOLD_TIMEZONE", DEFAULT_TIMEZONE))[0]


def timezone_warning():
    """The fallback warning text, or None if the real zone is in use."""
    return _resolve(os.getenv("HOUSEHOLD_TIMEZONE", DEFAULT_TIMEZONE))[1]


def timezone_name(tz) -> str | None:
    """The IANA name (e.g. "America/New_York") if `tz` has one, else None.
    Fixed-offset fallbacks have no name."""
    return getattr(tz, "key", None)


def describe_timezone(tz=None, now: datetime | None = None) -> str:
    """Human-readable, for logs: "America/New_York (EDT, UTC-04:00)"."""
    tz = tz or household_timezone()
    base = now or datetime.now().astimezone()
    moment = base.astimezone(tz) if base.tzinfo else base.replace(tzinfo=tz)
    offset = moment.utcoffset()
    total = int(offset.total_seconds()) if offset is not None else 0
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total) // 60, 60)
    label = timezone_name(tz) or "fixed offset (no tz database!)"
    return f"{label} ({moment.tzname()}, UTC{sign}{hours:02d}:{minutes:02d})"


def clear_cache() -> None:
    """For tests: forget the cached lookup (e.g. after changing the env var)."""
    _resolve.cache_clear()
