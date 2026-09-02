import datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.codegen import RESERVED_CODES, generate_code
from app.config import settings
from app.errors import ConflictError, UnprocessableError
from app.models import Click, Link
from app.timeutils import utcnow

MAX_CODE_GENERATION_ATTEMPTS = 5


def create_link(
    db: Session,
    owner_api_key_id: int,
    target_url: str,
    custom_alias: str | None,
    expires_at: datetime.datetime | None,
) -> Link:
    if custom_alias is not None:
        if custom_alias in RESERVED_CODES:
            raise UnprocessableError(f"'{custom_alias}' is a reserved word and cannot be used as an alias")
        return _insert_link(db, owner_api_key_id, custom_alias, target_url, expires_at)

    last_error: Exception | None = None
    for _ in range(MAX_CODE_GENERATION_ATTEMPTS):
        code = generate_code(settings.short_code_length)
        try:
            return _insert_link(db, owner_api_key_id, code, target_url, expires_at)
        except ConflictError as exc:  # extremely unlikely collision, retry with a new random code
            last_error = exc
            continue
    raise last_error or ConflictError("Could not generate a unique short code, please retry")


def _insert_link(
    db: Session,
    owner_api_key_id: int,
    code: str,
    target_url: str,
    expires_at: datetime.datetime | None,
) -> Link:
    link = Link(
        code=code,
        owner_api_key_id=owner_api_key_id,
        target_url=target_url,
        expires_at=expires_at,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        # Relies on the unique constraint on links.code as the single source of
        # truth for "is this code taken" -- safe under concurrent requests,
        # unlike a check-then-insert (SELECT then INSERT) which would race.
        db.rollback()
        raise ConflictError(f"Short code '{code}' is already in use")
    db.refresh(link)
    return link


def get_link_by_code(db: Session, code: str) -> Link | None:
    return db.query(Link).filter(Link.code == code).first()


def link_is_unavailable(link: Link) -> bool:
    if link.is_deleted:
        return True
    if link.expires_at is not None and link.expires_at <= utcnow():
        return True
    return False


def list_links_for_owner(
    db: Session, owner_api_key_id: int, page: int, page_size: int
) -> tuple[list[tuple[Link, int]], int]:
    click_counts = (
        db.query(Click.link_id, func.count(Click.id).label("click_count"))
        .group_by(Click.link_id)
        .subquery()
    )

    base_query = (
        db.query(Link, func.coalesce(click_counts.c.click_count, 0))
        .outerjoin(click_counts, Link.id == click_counts.c.link_id)
        .filter(Link.owner_api_key_id == owner_api_key_id)
    )

    total = base_query.count()
    rows = (
        base_query.order_by(Link.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def soft_delete_link(db: Session, link: Link) -> None:
    link.is_deleted = True
    db.commit()


def record_click(db: Session, link_id: int, referrer: str | None) -> None:
    db.add(Click(link_id=link_id, referrer=referrer))
    db.commit()


def get_total_clicks(db: Session, link_id: int) -> int:
    return db.query(func.count(Click.id)).filter(Click.link_id == link_id).scalar() or 0


def get_daily_clicks(db: Session, link_id: int, since: datetime.datetime) -> list[tuple[datetime.date, int]]:
    day = func.date(Click.clicked_at)
    rows = (
        db.query(day.label("day"), func.count(Click.id))
        .filter(Click.link_id == link_id, Click.clicked_at >= since)
        .group_by(day)
        .order_by(day)
        .all()
    )
    return [(row[0], row[1]) for row in rows]


def get_referrer_breakdown(db: Session, link_id: int) -> list[tuple[str, int]]:
    referrer_expr = func.coalesce(Click.referrer, "direct")
    rows = (
        db.query(referrer_expr.label("referrer"), func.count(Click.id))
        .filter(Click.link_id == link_id)
        .group_by(referrer_expr)
        .order_by(func.count(Click.id).desc())
        .all()
    )
    return [(row[0], row[1]) for row in rows]
