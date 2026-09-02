# PROMPTS.md

How this project was built with AI assistance (Claude, via Claude Code):
what was asked, what was decided along the way, what broke, and what was
corrected.

## 1. Initial request

The user's prompt was the full assignment spec: build a URL Shortener with
Analytics in Python/FastAPI/MySQL/SQLAlchemy/Alembic/Pytest, with the
requirements listed in the top of this repo's README (create/redirect/list/
stats/delete, API-key auth, rate limiting, SSRF protection, concurrency-safe
duplicate handling, async click logging, indexed analytics, migrations,
structured errors, tests, docs). The user explicitly asked to see a plan and
discuss it before any code was written, and explicitly excluded a frontend,
user registration/passwords, QR codes, geolocation, and deployment config.

## 2. Planning discussion

Before writing code, the assistant inspected the (nearly empty) repo, then
proposed a project structure and a set of design decisions, flagging two as
worth confirming with the user rather than assuming:

- **Sync SQLAlchemy + PyMySQL vs. async SQLAlchemy + asyncmy.** Recommended
  sync: simpler, more stable on Windows, and FastAPI already runs sync route
  handlers in a threadpool, so there's no real throughput cost at this
  scale. **User chose sync + PyMySQL.**
- **How to provision local MySQL for dev/tests** — a MySQL-only
  docker-compose file vs. assuming MySQL is already installed. **User chose
  docker-compose.**

### Change: docker-compose was planned but not built

Immediately after that answer, the assistant checked the machine directly
(`sc query MySQL80`) and found MySQL 8.0 already installed and running as a
Windows service. Writing a docker-compose file at that point would have
added an unused, redundant way to get a database that already existed and
that the running app would not even use (a docker-compose MySQL would bind a
different container/port than the already-running local service). The
assistant flagged this and asked a follow-up question instead of silently
overriding the earlier answer:

> "MySQL is already installed and running locally. How do you want to handle
> credentials?" — options: give the assistant the root password directly, or
> write a `setup.sql` for the user to run themselves.

**User chose to share the root password directly** (`root`/`root`, local
dev machine only). The assistant used it once, non-interactively, to create
a dedicated `url_shortener_app` MySQL user scoped to only
`url_shortener`/`url_shortener_test`, rather than having the app itself run
as root — the root password was not stored anywhere in the project (`.env`
holds only the generated app-user credentials).

## 3. Implementation

Built in the order: config/database/models → security (API key hashing,
SSRF validation) → rate limiting → CRUD → routers → Alembic migration →
manual smoke test via `curl` against the running app → automated pytest
suite → README/PROMPTS.

Key decisions made (and why) are documented inline in the README rather than
duplicated here — see "Schema and index reasoning", "Security",
"Performance", and "Rate limiting" in [README.md](README.md). The short
version:

- **API key *is* the user.** No accounts/passwords were in scope, so
  `ApiKey.id` is the ownership key for links; a CLI script
  (`scripts/create_api_key.py`) mints keys out-of-band instead of exposing a
  public "create key" endpoint (which would effectively be registration).
- **Soft delete, never hard delete**, so the unique constraint on
  `links.code` can guarantee "codes are never reused" for free.
- **Insert-and-catch-IntegrityError**, not check-then-insert, for both
  duplicate aliases and the rate-limit counter (via MySQL's
  `INSERT ... ON DUPLICATE KEY UPDATE`) — the only way to be race-safe under
  concurrent requests without an explicit lock.
- **DB-backed fixed-window rate limiting** instead of an in-process counter,
  so it stays correct if the app ever runs multiple worker processes,
  without adding a Redis dependency for a take-home.

## 4. Bugs found during testing, and how they were fixed

Two real bugs were caught by testing (not just written and assumed correct):

### Bug: `/health` (and `/links`) shadowed by the redirect catch-all

`GET /{code}` is a catch-all path parameter. It was registered in
`app/main.py` *before* the `/health` route was defined, so Starlette matched
`GET /health` against `/{code}` first, treating `"health"` as a short code
and returning a 404 `not_found` instead of the health check response. This
was caught immediately by a manual `curl http://localhost:8000/health` smoke
test, which came back as
`{"error":{"code":"not_found","message":"No link found for code 'health'"}}`.

**Fix:** reordered `app/main.py` so the health check and both routers
(`links`, then `redirect`) are registered before the catch-all redirect
route, with a comment explaining why the order is load-bearing. This is
also why `RESERVED_CODES` in `app/codegen.py` exists — it stops a *user*
from creating a link whose alias is `links`, `docs`, `health`, etc., which
would be unreachable (shadowed by the real route) even after the ordering
fix.

### Bug: naive vs. aware datetime comparison, caused by MySQL's `DATETIME` type

The initial models declared timestamp columns as
`DateTime(timezone=True)`, and application code compared them against
timezone-aware `datetime.now(timezone.utc)` values. This worked when the
comparison used an object that had *just* been assigned in Python, but the
first automated test that read a value back from MySQL after a round-trip
(`test_expired_link_returns_410_and_does_not_redirect`, which force-expires
a link by updating and re-committing it, then re-fetches it via a fresh
request/session) failed with:

```
TypeError: can't compare offset-naive and offset-aware datetimes
```

**Root cause:** MySQL's `DATETIME` type has no timezone concept at all;
PyMySQL always returns naive `datetime` objects when reading a row back,
regardless of whether the SQLAlchemy column was declared with
`timezone=True`. That flag only affects some other database backends
(e.g. PostgreSQL's `TIMESTAMPTZ`); on MySQL it's silently a no-op, which is
an easy trap because the code *looks* like it's handling timezones
correctly.

**Fix:** standardized on one convention app-wide — every datetime the
application stores or compares is a **naive datetime that is implicitly
UTC** (`app/timeutils.py`, `utcnow()` and `to_utc_naive()`). All `DateTime`
columns were changed from `DateTime(timezone=True)` to plain `DateTime()`
to match what MySQL actually does, and every place that previously called
`datetime.datetime.now(datetime.timezone.utc)` directly (models, crud,
rate limiting, the stats router, the request schema's expiry validator) was
updated to go through `timeutils.utcnow()` instead, so there is exactly one
place that convention is defined. Confirmed fixed by re-running the full
suite (31 passed) and by re-verifying live against the running server with
a real short-lived `expires_at` link.

## 5. Minor corrections made during review of the assistant's own code

- `crud._insert_link` had an unused `allow_retry` parameter left over from
  an earlier draft where success/failure logging differed by call site; a
  linter warning (`Remove the unused function parameter`) caught it and it
  was deleted along with the corresponding argument at both call sites.
- An early draft of `tests/test_links.py` included a placeholder test
  (`test_list_links_returns_only_own_links_with_click_counts`) that was
  written while thinking through ownership isolation but didn't actually
  test what its name claimed — it asserted an unregistered key gets 401,
  which is just re-testing auth. It was removed once the real isolation
  test (`test_links_are_isolated_per_api_key`) was written properly, and a
  shared `other_api_key` pytest fixture was factored out of it so the same
  "second identity" setup could be reused by the rate-limit-isolation test
  too, instead of duplicating the raw-key/`ApiKey`-row creation inline in
  two different test files.
- `app/errors.py` used `status.HTTP_422_UNPROCESSABLE_ENTITY`, which the
  installed Starlette version flags as deprecated in favor of
  `HTTP_422_UNPROCESSABLE_CONTENT` (same numeric value, 422). Both usages
  were updated after the deprecation warning showed up in the first full
  test run's output.

## 6. Follow-up: Python 3.14 compatibility

**Prompt:** the user reported that `pip install -r requirements.txt` failed
while building `pydantic-core==2.23.4` from source, and asked for the pins
to be updated to Python-3.14-compatible versions, verified, with any
resulting code issues fixed.

**Investigation:** rather than guessing at version numbers, the assistant
reproduced the failure directly (`pip install --dry-run pydantic-core==2.23.4`
against a fresh 3.14.7 venv) and confirmed the actual cause: PyPI only has a
source `.tar.gz` for that release, no `cp314` wheel, so pip has to compile
the Rust extension from source — which fails on a machine without a Rust
toolchain, matching the user's report exactly. The assistant also noticed
the project's real `.venv` already had a mix of newer packages installed
(e.g. `fastapi==0.141.1`) that didn't match the old pins at all, and was
*missing* `cryptography` and the `uvicorn[standard]` extras entirely —
evidence that someone had patched the environment by hand at some point
without updating `requirements.txt`, which meant the existing `.venv`
couldn't be trusted as a clean signal and needed independent verification.

**Fix:** installed the direct dependencies into a disposable venv with
`pip install --only-binary=:all:` (a hard requirement that no source build
happen at all) and only lower-bound constraints, letting pip's resolver
pick the latest versions that actually ship `cp314` wheels. Every package
resolved to a wheel, including `cryptography` (as `cryptography-50.0.1`, a
`cp311-abi3` stable-ABI wheel — abi3 wheels work unchanged across Python
minor versions, which is why a library like `cryptography` can support a
brand-new Python release before doing a from-scratch native rebuild).
`requirements.txt` was rewritten to those exact resolved versions,
including adding `cryptography` (needed by PyMySQL for MySQL 8's default
`caching_sha2_password` auth) and the `[standard]` extra on `uvicorn`
(`--reload` depends on `watchfiles`, which was silently missing before) —
both had been dropped in whatever ad-hoc fix produced the stale `.venv`.

**Verification:** ran `pip install -r requirements.txt` against the
project's actual `.venv` (not just the throwaway one) and confirmed it only
needed to add the previously-missing `cryptography`/extras with zero source
builds; ran `pip check` (no conflicts); reran the full pytest suite
(31 passed, no code changes needed); and re-ran the manual end-to-end smoke
test (create → redirect → list → stats → delete → SSRF rejection) against a
live server plus `alembic current` / `alembic check`, to confirm the
major version jumps (FastAPI 0.115→0.141, Starlette's version scheme
change to 1.x, Pydantic 2.9→2.13, Alembic 1.13→1.19) introduced no breaking
behavior in this codebase — no application code changes were required, only
the dependency pins.

## 7. Follow-up: gap audit against a re-stated spec, then four fixes

**Prompt:** the user re-pasted the assignment's rules/edge-cases/must-include
sections and asked what the project was missing. The assistant re-read the
actual code (not just its own earlier summary of it) against each bullet and
reported four real gaps, then — on the user's confirmation — fixed exactly
those four and nothing else.

1. **No catch-all exception handler.** `app/errors.py` only handled
   `AppError`/`HTTPException`/`RequestValidationError`; a genuine bug would
   fall through to FastAPI's default `{"detail": "..."}` shape, breaking the
   "consistent error shape across all endpoints" requirement. Added an
   `@app.exception_handler(Exception)` that logs the real exception and
   returns `{"error": {"code": "internal_error", ...}}` with a 500.

   **Correction while testing this fix:** the first version of the test
   asserted on `client.post(...).status_code` using the shared `client`
   fixture and got a raw `RuntimeError` traceback instead of a response.
   Reading Starlette's own source
   (`starlette/applications.py::build_middleware_stack` and
   `starlette/middleware/errors.py::ServerErrorMiddleware`) showed why:
   Starlette special-cases a handler registered for `Exception` (or `500`)
   out of the normal per-route exception middleware and into
   `ServerErrorMiddleware`, which **always re-raises the original exception
   after sending the handler's response** — specifically so test clients can
   opt into seeing it. In production (uvicorn) the client already has the
   correct JSON response by the time that re-raise happens; it's only
   `TestClient`'s default `raise_server_exceptions=True` that surfaces it as
   a test failure. Fixed by using a dedicated
   `TestClient(app, raise_server_exceptions=False)` for that one test
   (`tests/test_errors.py`) instead of changing the shared fixture (which
   should keep failing loudly on a real unexpected exception in every other
   test).

2. **No true-concurrency test for the alias race.** The existing duplicate
   alias test was sequential (create, then create again). Added
   `tests/test_concurrency.py`: two threads, each with its own
   `TestClient(app)` instance, synchronized with a `threading.Barrier(2)` so
   both fire the same `POST /links` (same `custom_alias`) as close to
   simultaneously as possible, asserting the results are exactly
   `[201, 409]`. No production code changed here — this test exists to
   empirically back up the unique-constraint-plus-`IntegrityError` design
   already in `app/crud.py`, not to fix a bug in it.

3. **No length bound on `target_url`.** Added `min_length=1,
   max_length=2048` to the Pydantic field
   (`app/schemas.py::MAX_TARGET_URL_LENGTH`), with tests for empty, over the
   limit, and exactly at the limit. 2048 was chosen as a conventional URL
   length ceiling; no database migration was needed since `links.target_url`
   is already `TEXT` (65,535-byte capacity), comfortably larger — the limit
   is an application-level sanity check, not a storage constraint.

4. **README's SSRF explanation undercut itself.** It technically-correctly
   noted that this app's own redirect never fetches the target server-side,
   then concluded the "actual SSRF surface... doesn't exist here at all" —
   which is true narrowly but misses the real reason the check matters:
   third-party link-preview/unfurling services (Slack, Discord, Teams,
   Twitter/X, etc.) fetch a shared URL server-side on the recipient's
   behalf, so a shortener that allows internal/private targets becomes a way
   to turn *their* infrastructure into an SSRF proxy. Rewrote the
   [Security](README.md#security) section to lead with that, and updated
   the corresponding "Future improvements" bullet (periodic re-validation,
   not "only matters if we add a fetch feature").

All 36 tests pass after these changes (31 existing + 5 new); no
pre-existing test needed modification.

## 8. Follow-up: the remaining `StarletteDeprecationWarning`

**Prompt:** the user asked the assistant to investigate the one remaining
test warning (`Using httpx with starlette.testclient is deprecated; install
httpx2 instead`) and decide whether fixing it was worthwhile for this
assignment — fix it only if that could be done without changing application
behavior or adding an unnecessary dependency; otherwise leave it and explain
why.

**Investigation, not assumption:** rather than guessing whether `httpx2` was
a legitimate package worth depending on, the assistant read Starlette's own
source (`starlette/testclient.py`) to see exactly what triggers the warning
(it tries `import httpx2 as httpx` first, falls back to the older `httpx`
with a warning), confirmed via `grep` that neither `app/` nor `tests/`
imports `httpx` directly anywhere (it's a transitive need of
`fastapi.testclient.TestClient` only, which itself is a one-line re-export
of Starlette's), and downloaded `httpx2`'s wheel metadata directly rather
than trusting the package name at face value. That metadata showed it's
maintained by the original author of `httpx` (Tom Christie) and by "Pydantic
Services Inc." — the organization behind FastAPI/Pydantic — tagged
`Development Status :: 5 - Production/Stable`, with explicit Python 3.14
support. That's the evidence that made this a safe swap rather than a
speculative one.

**Fix:** since `httpx`/`httpcore` had no other reverse dependencies
(confirmed via `pip show httpx` → `Required-by:` was empty), swapped
`httpx==0.28.1` for `httpx2==2.12.0` in `requirements.txt`, uninstalled the
old `httpx`/`httpcore`, and reinstalled. This is a like-for-like swap of
test-only tooling for its designated non-deprecated successor — it doesn't
touch any application code (the production app never imports either
package) and doesn't add speculative complexity, since `httpx2` replaces
`httpx`+`httpcore` one-for-one (plus `truststore`, a small, no-build
dependency `httpx2` itself requires for OS trust-store integration).

**Verification:** `pip check` reported no conflicts; the full test suite
now reports **36 passed, 0 warnings** (previously 36 passed, 1 warning);
and the live app was restarted and re-checked (`GET /health`) to confirm
production behavior is unaffected, as expected given neither package is
ever imported by `app/`.
