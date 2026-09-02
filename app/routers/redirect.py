from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import crud
from app.database import SessionLocal
from app.deps import get_db
from app.errors import GoneError, NotFoundError

router = APIRouter(tags=["redirect"])


def _log_click(link_id: int, referrer: str | None) -> None:
    """Runs after the redirect response has been sent. Uses its own DB session
    rather than the request's, since the request-scoped session may already be
    torn down by the time this background task executes."""
    db = SessionLocal()
    try:
        crud.record_click(db, link_id, referrer)
    finally:
        db.close()


@router.get("/{code}")
def redirect_to_target(
    code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    link = crud.get_link_by_code(db, code)
    if link is None:
        raise NotFoundError(f"No link found for code '{code}'")
    if crud.link_is_unavailable(link):
        raise GoneError(f"Link '{code}' is deleted or has expired")

    referrer = request.headers.get("referer")
    background_tasks.add_task(_log_click, link.id, referrer)

    return RedirectResponse(url=link.target_url, status_code=302)
