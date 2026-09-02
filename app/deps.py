from collections.abc import Generator

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import UnauthorizedError
from app.models import ApiKey
from app.security import hash_api_key


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not x_api_key:
        raise UnauthorizedError("Missing X-API-Key header")

    key_hash = hash_api_key(x_api_key)
    api_key = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        .first()
    )
    if api_key is None:
        raise UnauthorizedError("Invalid or inactive API key")
    return api_key
