import datetime

from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from app.errors import RateLimitedError
from app.models import RateLimitWindow
from app.timeutils import utcnow


def enforce_rate_limit(db: Session, api_key_id: int, max_requests: int, window_seconds: int) -> None:
    """Fixed-window rate limiting backed by a DB row per (api_key, window).

    The increment uses MySQL's INSERT ... ON DUPLICATE KEY UPDATE so that two
    concurrent requests in the same window both land correctly (one INSERTs,
    the other UPDATEs) with no read-check-write race -- the same reasoning as
    the unique-constraint approach used for link codes.
    """
    now = utcnow()
    window_start_epoch = (int(now.timestamp()) // window_seconds) * window_seconds
    window_start = datetime.datetime.fromtimestamp(window_start_epoch, tz=datetime.timezone.utc).replace(
        tzinfo=None
    )

    stmt = mysql_insert(RateLimitWindow).values(
        api_key_id=api_key_id, window_start=window_start, count=1
    )
    stmt = stmt.on_duplicate_key_update(count=RateLimitWindow.count + 1)
    db.execute(stmt)
    db.commit()

    row = (
        db.query(RateLimitWindow)
        .filter_by(api_key_id=api_key_id, window_start=window_start)
        .one()
    )
    if row.count > max_requests:
        retry_after = window_seconds - (int(now.timestamp()) - window_start_epoch)
        raise RateLimitedError(
            "Rate limit exceeded for link creation",
            details={"retry_after_seconds": retry_after},
        )
