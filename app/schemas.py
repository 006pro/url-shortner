import datetime
import re

from pydantic import BaseModel, Field, field_validator

from app.timeutils import to_utc_naive, utcnow

ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")

# 2048 matches the practical length ceiling most browsers and other URL
# shorteners settle on (historically Internet Explorer's own limit, and still
# a sane upper bound today). The `links.target_url` column is MySQL TEXT,
# which holds up to 65,535 bytes, so this is purely an application-level
# sanity limit -- it exists to reject obvious garbage/abuse before it's ever
# stored or sent through URL parsing and a DNS lookup, not a storage
# constraint.
MAX_TARGET_URL_LENGTH = 2048


class LinkCreateRequest(BaseModel):
    target_url: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TARGET_URL_LENGTH,
        description="The URL to redirect to.",
    )
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
