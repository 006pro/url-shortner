import datetime
import re

from pydantic import BaseModel, Field, field_validator

from app.timeutils import to_utc_naive, utcnow

ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


class LinkCreateRequest(BaseModel):
    target_url: str = Field(..., description="The URL to redirect to.")
    custom_alias: str | None = Field(
        default=None, description="Optional custom short code, 3-32 chars: letters, digits, - and _."
    )
    expires_at: datetime.datetime | None = Field(
        default=None, description="Optional expiry timestamp (UTC). Must be in the future."
    )

    @field_validator("custom_alias")
    @classmethod
    def validate_alias(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not ALIAS_PATTERN.match(value):
            raise ValueError("custom_alias must be 3-32 characters: letters, digits, - and _ only")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime.datetime | None) -> datetime.datetime | None:
        if value is None:
            return value
        # Normalize to the app's naive-UTC convention (see app/timeutils.py)
        # before it's ever compared against, or stored alongside, other times.
        value = to_utc_naive(value)
        if value <= utcnow():
            raise ValueError("expires_at must be in the future")
        return value


class LinkResponse(BaseModel):
    code: str
    short_url: str
    target_url: str
    created_at: datetime.datetime
    expires_at: datetime.datetime | None


class LinkListItem(LinkResponse):
    click_count: int


class LinkListResponse(BaseModel):
    items: list[LinkListItem]
    page: int
    page_size: int
    total: int


class DailyClickCount(BaseModel):
    date: datetime.date
    count: int


class ReferrerCount(BaseModel):
    referrer: str
    count: int


class LinkStatsResponse(BaseModel):
    code: str
    total_clicks: int
    daily_clicks: list[DailyClickCount]
    referrers: list[ReferrerCount]
