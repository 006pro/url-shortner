# URL Shortener with Analytics

A small, production-shaped URL shortener: create short links, redirect through
them, and see click analytics (totals, a 30-day daily breakdown, referrers).
Built with FastAPI, SQLAlchemy, MySQL, and Alembic.

There is no frontend, no user registration/passwords, no QR codes, no
geolocation, and no deployment config — this is intentionally scoped as a
take-home backend service.

## Contents

- [Setup](#setup)
- [Authentication](#authentication)
- [API overview](#api-overview)
- [Schema and index reasoning](#schema-and-index-reasoning)
- [Security](#security)
- [Performance](#performance)
- [Rate limiting](#rate-limiting)
- [Error format](#error-format)
- [Testing](#testing)
- [Future improvements](#future-improvements)

## Setup

### Prerequisites

- Python 3.11+
- A running MySQL 8 server (local install or any reachable instance)

### 1. Install dependencies

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

This dependency set has been verified with `pip check` (no conflicts) on
Python 3.14.

### 2. Create the database and a dedicated app user

Don't run the app as `root`. Connect as an admin user and run:

```sql
CREATE DATABASE url_shortener CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE url_shortener_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'url_shortener_app'@'localhost' IDENTIFIED BY 'change-me';
GRANT ALL PRIVILEGES ON url_shortener.* TO 'url_shortener_app'@'localhost';
GRANT ALL PRIVILEGES ON url_shortener_test.* TO 'url_shortener_app'@'localhost';
FLUSH PRIVILEGES;
```

The `_test` database is only used by the pytest suite so it can freely
truncate tables between tests without touching real data.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in the values from step 2:

```
DATABASE_URL=mysql+pymysql://url_shortener_app:change-me@127.0.0.1:3306/url_shortener
TEST_DATABASE_URL=mysql+pymysql://url_shortener_app:change-me@127.0.0.1:3306/url_shortener_test
BASE_URL=http://localhost:8000
SHORT_CODE_LENGTH=7
RATE_LIMIT_MAX_REQUESTS=10
RATE_LIMIT_WINDOW_SECONDS=60
```

These examples assume a local MySQL 8 instance on `127.0.0.1:3306`. If MySQL
runs elsewhere (a remote host, a different port, a container), just point
`DATABASE_URL`/`TEST_DATABASE_URL` at it — nothing else in the app assumes a
local connection.

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Create an API key

There's no signup endpoint (no user accounts by design). Mint a key with the
provided script:

```bash
python -m scripts.create_api_key "my first key"
```

This prints the raw key once. Only its SHA-256 hash is stored, so save it —
it can't be recovered later, only reissued.

### 6. Run the app

```bash
uvicorn main:app --reload
```

Interactive API docs: http://localhost:8000/docs (Swagger UI) and
http://localhost:8000/redoc.

## Authentication

Every endpoint under `/links` requires an `X-API-Key` header:

```bash
curl -H "X-API-Key: usk_..." http://localhost:8000/links
```

An API key is the only notion of "user" in this system — links are owned by
whichever key created them, and `GET /links` / stats / delete are all scoped
to the caller's own key. `GET /{code}` (the redirect itself) is public, as
it has to be for a short link to work for anyone who clicks it.

## API overview

| Method | Path                    | Auth | Description                                   |
|--------|-------------------------|------|------------------------------------------------|
| POST   | `/links`                | yes  | Create a short link                            |
| GET    | `/links`                | yes  | List the caller's links, paginated, with click counts |
| GET    | `/links/{code}/stats`   | yes  | Total clicks, 30-day daily series, referrer breakdown |
| DELETE | `/links/{code}`         | yes  | Soft-delete a link (code is never reused)      |
| GET    | `/{code}`               | no   | 302 redirect + async click logging             |
| GET    | `/health`               | no   | Liveness check                                 |

**`GET /{code}` status codes** (see [app/routers/redirect.py](app/routers/redirect.py)):

- `302 Found` — the link is active: redirects to the stored `target_url`.
- `410 Gone` — the code exists but the link has been soft-deleted or has
  expired.
- `404 Not Found` — the code has never existed.

`POST /links` body:

```json
{
  "target_url": "https://example.com/some/page",
  "custom_alias": "my-page",
  "expires_at": "2026-12-31T00:00:00Z"
}
```

`custom_alias` and `expires_at` are optional. `custom_alias` must be 3-32
characters of letters/digits/`-`/`_`, and can't collide with reserved paths
(`links`, `docs`, `health`, etc.) or an existing/previously-used code.
`target_url` must be 1-2048 characters.

Example — creating a short link:

```bash
curl -X POST http://localhost:8000/links -H "X-API-Key: YOUR_API_KEY" -H "Content-Type: application/json" -d "{\"target_url\": \"https://example.com/some/very/long/page\"}"
```

Response (`201 Created`) — `code` is randomly generated, so yours will differ:

```json
{
  "code": "aZ3kQ9x",
  "short_url": "http://localhost:8000/aZ3kQ9x",
  "target_url": "https://example.com/some/very/long/page",
  "created_at": "2026-01-01T12:00:00",
  "expires_at": null
}
```

## Schema and index reasoning

Four tables (see [app/models.py](app/models.py), migration in
[alembic/versions](alembic/versions)):

- **api_keys** — `key_hash` (unique, indexed) is looked up on every
  authenticated request, so it needs to be an index hit, not a scan.
- **links** — `code` (unique, indexed) is the lookup key for every redirect,
  the single highest-traffic query in the system. `owner_api_key_id` is
  indexed since `GET /links` filters by it.
- **clicks** — one row per click. This is the table that grows unbounded, so
  it's the one place indexing actually matters for correctness at scale:
  `ix_clicks_link_id_clicked_at` is a **composite index on
  `(link_id, clicked_at)`**, because every analytics query
  (`get_total_clicks`, `get_daily_clicks`, `get_referrer_breakdown`) filters
  by `link_id` and (for the daily breakdown) an additional `clicked_at`
  range. Without this, `GET /links/{code}/stats` would degrade into a full
  table scan of `clicks` as the table grows — the exact failure mode the
  requirement to "not scan all clicks" is about.
- **rate_limit_windows** — one row per `(api_key_id, window_start)`, enforced
  by a unique constraint (see [Rate limiting](#rate-limiting)).

**Soft delete, not hard delete:** `links.is_deleted` is a boolean flag; rows
are never removed. This is what makes "codes cannot be reused" trivial to
guarantee — the unique constraint on `code` stays in force forever, so a
deleted code can never collide with a new one. The tradeoff is the table
grows monotonically, which is an accepted cost at this scale (see
[Future improvements](#future-improvements)).

## Security

- **API keys are stored as SHA-256 hashes.** The raw key is generated with
  `secrets.token_urlsafe(32)` (256 bits of randomness) and shown only once,
  at creation time, by `scripts/create_api_key.py`; only its hash
  (`hash_api_key()`, [app/security.py](app/security.py)) is ever persisted,
  so a stolen database dump doesn't hand out usable credentials. This is
  deliberately plain SHA-256, not a password-hashing algorithm like
  bcrypt/argon2/scrypt — those exist to slow down brute-forcing a
  low-entropy, human-chosen password, which doesn't apply here since the
  input being hashed is already a high-entropy random token. API keys
  should be treated as high-entropy bearer credentials, not passwords.
- **Rejecting localhost/private-IP targets matters because of who else
  fetches a short link, not just who clicks it.** A URL shortener's job is
  to hand out URLs that get *distributed* — pasted into Slack, tweeted,
  emailed. Most of those surfaces run a **link-preview/unfurling bot**
  (Slack, Discord, Microsoft Teams, Twitter/X, iMessage, and plenty of
  internal corporate scanners all do this) that fetches the target URL
  **server-side**, from *their* infrastructure, to build a preview card —
  with no user in the loop and often with elevated network access. If this
  service accepted `http://169.254.169.254/latest/meta-data/` (a cloud
  provider's instance-metadata endpoint, which can leak IAM credentials) or
  `http://127.0.0.1:6379` (an internal Redis instance) as a valid target,
  sharing that short link anywhere with an unfurler present turns *their*
  trusted infrastructure into an SSRF proxy on the attacker's behalf. Our
  own redirect endpoint (`GET /{code}`) never fetches the target itself —
  it just returns a client-side 302 — but that's exactly why this
  validation has to live at creation time: minting the link is the one
  point where this service can refuse to vouch for a URL as safe to
  distribute at all. [`validate_public_url`](app/security.py) enforces this
  by rejecting non-`http(s)` schemes, `localhost`/`*.localhost`, and any
  hostname that resolves to a private, loopback, link-local, reserved, or
  multicast IP (via `ipaddress` on the result of `socket.getaddrinfo`).
  **Known limitation:** this check runs once, at creation time. A hostname
  that resolves safely then but is later repointed at a private IP (DNS
  rebinding) wouldn't be re-checked before some future fetch of it — a real
  residual risk for any consumer of the link that re-resolves it later, so
  it's worth periodic re-validation in a production deployment (see
  [Future improvements](#future-improvements)).
- **No plaintext secrets in git.** `.env` is gitignored; `.env.example`
  documents required variables without real values.
- **Ownership checks everywhere.** Stats and delete both 404 (not 403) for a
  link that exists but isn't owned by the caller's key, to avoid confirming
  a code's existence to someone who doesn't own it.
- **Structured, non-leaky errors, even for genuine bugs.** A catch-all
  handler for any unanticipated exception ([app/errors.py](app/errors.py))
  guarantees every response — expected errors *and* unexpected 500s — uses
  the same `{"error": {...}}` shape and never leaks a stack trace or
  internal detail to the client; the real exception is only logged
  server-side. See [Error format](#error-format).

## Performance

- **Click logging is non-blocking.** `GET /{code}` returns the 302 redirect
  immediately; the `Click` row is inserted afterwards via FastAPI's
  `BackgroundTasks` ([app/routers/redirect.py](app/routers/redirect.py)), so
  a slow or contended write to the `clicks` table never adds latency to the
  redirect itself, which is the one endpoint end users actually wait on.
  The background task opens its **own** DB session rather than reusing the
  request's, since the request's session may already be closing by the time
  the task runs.
- **Analytics queries are index-backed**, not full scans — see
  [Schema and index reasoning](#schema-and-index-reasoning).
- **`GET /links` avoids N+1 queries.** Click counts are computed with a
  single `GROUP BY` subquery joined against `links`, not one query per link.
- **Concurrency-safe writes rely on DB constraints, not locks.** Both
  duplicate-alias handling and rate limiting are implemented as "try the
  write, let the unique constraint decide" rather than "check, then write" —
  see the next two sections. This is what actually makes them safe under
  concurrent requests; a `SELECT` followed by an `INSERT` has a race window
  no amount of application-level care closes.

### Duplicate aliases and concurrency

`POST /links` inserts directly and lets the unique constraint on `links.code`
be the single source of truth for "is this code taken"
([app/crud.py](app/crud.py)). If two requests race for the same custom alias,
exactly one `INSERT` succeeds; the other hits `IntegrityError` and is turned
into a `409 Conflict`. For auto-generated codes, the same path is used, with
a small retry loop (new random code, try again) in the vanishingly unlikely
event of a random collision — a check-then-insert approach could not
guarantee this without a database-level lock.

## Rate limiting

`POST /links` is rate-limited per API key using a **fixed-window counter
stored in the database** (`rate_limit_windows`, one row per
`(api_key_id, window_start)`), rather than an in-process counter.
The increment is done with MySQL's `INSERT ... ON DUPLICATE KEY UPDATE`, so
concurrent requests in the same window can't race each other into
undercounting. This means the limit is correctly enforced even if the app
runs with multiple worker processes, without needing Redis or another
external store. Defaults to 10 requests / 60 seconds per key
(`RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`); exceeding it
returns `429` with a `retry_after_seconds` hint.

Note: a request still counts against the quota even if it's later rejected
for another reason (bad URL, duplicate alias) — the thing being rate-limited
is calls to the endpoint, not just successful ones.

## Error format

Every error response — ours or FastAPI's — has the same shape:

```json
{"error": {"code": "not_found", "message": "No link found for code 'abc123'", "details": null}}
```

`code` is a stable machine-readable string (`unauthorized`, `not_found`,
`conflict`, `gone`, `unprocessable`, `rate_limited`, `validation_error`,
`http_error`, `internal_error`); `details` carries extra structured context
where relevant (e.g. `retry_after_seconds` on a 429, or the raw Pydantic
errors on a 422). This includes genuinely unexpected failures: a catch-all
handler ensures even a bug or an infrastructure error still returns
`{"error": {"code": "internal_error", ...}}` with a `500`, rather than
FastAPI's default `{"detail": "Internal Server Error"}` — the shape is
guaranteed across every endpoint, not just the errors we anticipated.

## Testing

```bash
pytest
```

The suite passes cleanly: `36 passed, 0 warnings`.

Tests run against the real `url_shortener_test` MySQL database (see Setup),
not SQLite or mocks — the app is small enough that this is simpler than
maintaining two DB code paths, and it means the tests actually exercise
MySQL-specific behavior (like the `ON DUPLICATE KEY UPDATE` rate limiter).
Tables are truncated before every test for isolation.

36 tests cover the main flows (create/list/stats/delete, redirect + click
logging) plus edge cases: SSRF rejection (localhost, private/link-local/
metadata IPs, bad schemes), expired-link 410, deleted-code-cannot-be-reused,
per-key rate limiting and quota isolation, ownership isolation between
different API keys, alias validation (reserved words, shape, duplicates,
`target_url` length bounds), a genuinely concurrent race for the same
custom alias (two threads, same instant — see
[tests/test_concurrency.py](tests/test_concurrency.py)), and an unhandled
exception still returning the standard structured error shape.

## Future improvements

Given more time or a real production deployment, in priority order:

1. **Queue-based click logging** (e.g. a proper task queue) instead of
   `BackgroundTasks`, so click ingestion survives a process crash between
   the redirect being sent and the write completing, and so it doesn't
   compete with request-handling threads under heavy load.
2. **Redis-backed rate limiting** if the app ever runs across many workers
   at high request volume — the DB-backed approach here is correct but adds
   one extra write per creation request, which Redis would make cheaper.
3. **Click table partitioning/archival** — since clicks are never deleted,
   a high-traffic deployment would eventually want to partition `clicks` by
   month or archive old rows out of the hot table.
4. **Per-key custom rate limits** instead of one global default, and a
   `Retry-After` HTTP header in addition to the JSON field.
5. **Periodic re-validation of stored target URLs** against the SSRF rules,
   not just a one-time check at creation — closing the DNS-rebinding gap
   described in [Security](#security), where a hostname could resolve
   safely at creation time but be repointed at a private IP later. This
   matters most if a future feature has our own server fetch the target
   (e.g. link previews), but is worth doing regardless given how many
   third-party unfurlers may fetch a distributed link later.
6. **API key rotation/revocation endpoint** (authenticated by the *old* key)
   instead of only the create-key CLI script.
