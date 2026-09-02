import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.deps import get_current_api_key, get_db
from app.errors import GoneError, NotFoundError, UnprocessableError
from app.models import ApiKey
from app.rate_limit import enforce_rate_limit
from app.schemas import (
    DailyClickCount,
    LinkCreateRequest,
    LinkListItem,
    LinkListResponse,
    LinkResponse,
    LinkStatsResponse,
    ReferrerCount,
)
from app.security import UnsafeUrlError, validate_public_url
from app.timeutils import utcnow

router = APIRouter(tags=["links"])

STATS_WINDOW_DAYS = 30


def _build_short_url(code: str) -> str:
    return f"{settings.base_url.rstrip('/')}/{code}"


@router.post("/links", response_model=LinkResponse, status_code=201)
def create_link(
    payload: LinkCreateRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_current_api_key),
):
    enforce_rate_limit(
        db, api_key.id, settings.rate_limit_max_requests, settings.rate_limit_window_seconds
    )

    try:
        validate_public_url(payload.target_url)
    except UnsafeUrlError as exc:
        raise UnprocessableError(str(exc)) from exc

    link = crud.create_link(
        db,
        owner_api_key_id=api_key.id,
        target_url=payload.target_url,
        custom_alias=payload.custom_alias,
        expires_at=payload.expires_at,
    )
    return LinkResponse(
        code=link.code,
        short_url=_build_short_url(link.code),
        target_url=link.target_url,
        created_at=link.created_at,
        expires_at=link.expires_at,
    )


@router.get("/links", response_model=LinkListResponse)
def list_links(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_current_api_key),
):
    rows, total = crud.list_links_for_owner(db, api_key.id, page, page_size)
    items = [
        LinkListItem(
            code=link.code,
            short_url=_build_short_url(link.code),
            target_url=link.target_url,
            created_at=link.created_at,
            expires_at=link.expires_at,
            click_count=click_count,
        )
        for link, click_count in rows
    ]
    return LinkListResponse(items=items, page=page, page_size=page_size, total=total)


@router.get("/links/{code}/stats", response_model=LinkStatsResponse)
def get_link_stats(
    code: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_current_api_key),
):
    link = crud.get_link_by_code(db, code)
    if link is None or link.owner_api_key_id != api_key.id:
        raise NotFoundError(f"No link found for code '{code}'")

    now = utcnow()
    since = now - datetime.timedelta(days=STATS_WINDOW_DAYS)
    total_clicks = crud.get_total_clicks(db, link.id)
    daily_rows = dict(crud.get_daily_clicks(db, link.id, since))

    daily_clicks = []
    for offset in range(STATS_WINDOW_DAYS - 1, -1, -1):
        day = (now - datetime.timedelta(days=offset)).date()
        daily_clicks.append(DailyClickCount(date=day, count=daily_rows.get(day, 0)))

    referrers = [
        ReferrerCount(referrer=referrer, count=count)
        for referrer, count in crud.get_referrer_breakdown(db, link.id)
    ]

    return LinkStatsResponse(
        code=link.code, total_clicks=total_clicks, daily_clicks=daily_clicks, referrers=referrers
    )


@router.delete("/links/{code}", status_code=204)
def delete_link(
    code: str,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_current_api_key),
):
    link = crud.get_link_by_code(db, code)
    if link is None or link.owner_api_key_id != api_key.id:
        raise NotFoundError(f"No link found for code '{code}'")

    if crud.link_is_unavailable(link):
        raise GoneError(f"Link '{code}' is already deleted or expired")

    crud.soft_delete_link(db, link)
