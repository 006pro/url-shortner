import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.timeutils import utcnow


class ApiKey(Base):
    """An API key is the only notion of "user" this app has: no accounts,
    no passwords. Links are owned by the key that created them."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=utcnow)

    links: Mapped[list["Link"]] = relationship(back_populates="owner")


class Link(Base):
    __tablename__ = "links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Unique and indexed: this is the lookup key for every redirect. The row is
    # never physically deleted (see is_deleted), so a code is never reused.
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    owner_api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    target_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=utcnow)
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    owner: Mapped["ApiKey"] = relationship(back_populates="links")
    clicks: Mapped[list["Click"]] = relationship(back_populates="link")


class Click(Base):
    __tablename__ = "clicks"
    __table_args__ = (
        # Every analytics query filters by link_id and a clicked_at range
        # (total count, 30-day daily buckets), so this composite index lets
        # MySQL satisfy those with an index range scan instead of a table scan.
        Index("ix_clicks_link_id_clicked_at", "link_id", "clicked_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("links.id"), index=True)
    clicked_at: Mapped[datetime.datetime] = mapped_column(DateTime(), default=utcnow)
    referrer: Mapped[str | None] = mapped_column(String(512), nullable=True)

    link: Mapped["Link"] = relationship(back_populates="clicks")


class RateLimitWindow(Base):
    """A fixed-window counter per API key. Storing this in the database (rather
    than an in-process dict) keeps rate limiting correct across process restarts
    and multiple app workers, without needing Redis."""

    __tablename__ = "rate_limit_windows"
    __table_args__ = (UniqueConstraint("api_key_id", "window_start", name="uq_rate_limit_key_window"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), index=True)
    window_start: Mapped[datetime.datetime] = mapped_column(DateTime())
    count: Mapped[int] = mapped_column(Integer, default=0)
