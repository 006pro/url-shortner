import datetime


def utcnow() -> datetime.datetime:
    """Naive UTC datetime, by convention used everywhere in this app.

    MySQL's DATETIME type has no timezone concept, so PyMySQL always returns
    naive datetimes when reading a row back -- even from a column declared
    DateTime(timezone=True). Rather than fight that, every datetime the app
    stores or compares is a naive datetime that is *implicitly* UTC.
    """
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def to_utc_naive(value: datetime.datetime) -> datetime.datetime:
    """Normalize a possibly tz-aware datetime (e.g. from a client-supplied
    ISO 8601 string with an offset) to the naive-UTC convention above."""
    if value.tzinfo is not None:
        return value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value
