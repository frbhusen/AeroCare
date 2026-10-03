"""Pure recurrence expansion (no DB). Dates are local (Asia/Damascus) calendar dates."""
import calendar
from datetime import date, datetime, timedelta

from backend.app.core.errors import ValidationError
from backend.app.core.timeutil import TZ

MAX_OCCURRENCES = 200
MAX_SPAN_DAYS = 3 * 366  # hard stop for `until`-based rules


def _add_months(d: date, months: int, day: int):
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    if day > calendar.monthrange(y, m)[1]:
        return None  # month has no such day (e.g. 31st) -> skipped
    return date(y, m, day)


def expand(start: date, freq: str, interval: int = 1, weekdays=None, count=None, until=None):
    """Return the list of local dates. Exactly one of count/until is normally given; both
    are allowed (whichever ends first). More than MAX_OCCURRENCES -> ValidationError."""
    if not count and not until:
        raise ValidationError("A recurrence needs an occurrence count or an end date.",
                              details={"rule": "count or until is required"})
    if until and until < start:
        raise ValidationError("The end date is before the first appointment.", details={"until": "is before start"})
    limit = min(count, MAX_OCCURRENCES + 1) if count else MAX_OCCURRENCES + 1
    hard_end = start + timedelta(days=MAX_SPAN_DAYS)
    last = min(until, hard_end) if until else hard_end
    out = []

    if freq == "daily":
        d = start
        while d <= last and len(out) < limit:
            out.append(d)
            d += timedelta(days=interval)
    elif freq == "weekly":
        days = sorted(set(weekdays or [start.isoweekday()]))
        week0 = start - timedelta(days=start.isoweekday() - 1)  # Monday of the first week
        w = 0
        while len(out) < limit:
            monday = week0 + timedelta(weeks=w * interval)
            if monday > last:
                break
            for wd in days:
                d = monday + timedelta(days=wd - 1)
                if d < start or d > last or len(out) >= limit:
                    continue
                out.append(d)
            w += 1
    elif freq == "monthly":
        k = 0
        while len(out) < limit:
            d = _add_months(start, k * interval, start.day)
            k += 1
            if d is None:
                if k * interval > MAX_SPAN_DAYS // 28:
                    break
                continue
            if d > last:
                break
            out.append(d)
    else:
        raise ValidationError("Unknown frequency", details={"freq": "must be daily, weekly or monthly"})

    if len(out) > MAX_OCCURRENCES:
        raise ValidationError(f"A recurring series can have at most {MAX_OCCURRENCES} appointments.",
                              code="too_many_occurrences", details={"max": MAX_OCCURRENCES})
    if not out:
        raise ValidationError("The recurrence produces no appointments.", details={"rule": "produces no dates"})
    return out


def local_dt(d: date, t):
    """Aware datetime for a local date + wall-clock time."""
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=TZ)
