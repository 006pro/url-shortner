from fastapi.testclient import TestClient

from app.main import app


def test_unhandled_exception_returns_structured_500(auth_headers, monkeypatch):
    """A genuine bug (not one of our expected AppError types) must still come
    back in the same {"error": {...}} shape as every other endpoint, not
    FastAPI's default {"detail": "Internal Server Error"}.

    Starlette's ServerErrorMiddleware always re-raises the original exception
    after sending our handler's response, specifically so tests can opt into
    seeing it (see starlette/middleware/errors.py). A real ASGI server like
    uvicorn already has our JSON response on the wire by that point and just
    logs the re-raised exception -- but observing the *response* here requires
    a client configured not to re-raise it.
    """

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.routers.links.crud.get_link_by_code", boom)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/links/some-code/stats", headers=auth_headers)

    assert resp.status_code == 500
    assert resp.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred",
            "details": None,
        }
    }
