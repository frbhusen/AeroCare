"""Time handling. Storage is UTC (timestamptz); business dates use the global Asia/Damascus zone."""
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Damascus")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    return datetime.now(TZ)


def local_today() -> date:
    return local_now().date()


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def iso(dt):
    """Serialize for JSON. Datetimes are emitted in UTC ISO-8601 with offset; dates as YYYY-MM-DD."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return dt.isoformat()


def local_day_bounds(d: date):
    """UTC [start, end) of a local calendar day."""
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    from datetime import timedelta
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
