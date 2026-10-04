from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_today(timezone_name, now=None):
    instant = now or utcnow()
    return instant.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timezone_name)).date()
