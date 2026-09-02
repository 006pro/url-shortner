from fastapi import FastAPI

from app.errors import register_exception_handlers
from app.routers import links, redirect

app = FastAPI(
    title="URL Shortener with Analytics",
    description="Create short links, redirect through them, and inspect click analytics.",
    version="1.0.0",
)

register_exception_handlers(app)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}


# Registration order matters: every other route must be registered before the
# catch-all GET /{code} redirect route, otherwise Starlette would match e.g.
# "/links" or "/health" against {code} instead of the intended handler.
app.include_router(links.router)
app.include_router(redirect.router)
