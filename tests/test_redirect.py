import datetime


def _create_link(client, auth_headers, **overrides):
    payload = {"target_url": "https://example.com/target"}
    payload.update(overrides)
    resp = client.post("/links", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["code"]


def test_redirect_returns_302_and_logs_click(client, auth_headers):
    code = _create_link(client, auth_headers)

    resp = client.get(f"/{code}", headers={"referer": "https://google.com"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://example.com/target"

    stats = client.get(f"/links/{code}/stats", headers=auth_headers).json()
    assert stats["total_clicks"] == 1
    assert stats["referrers"] == [{"referrer": "https://google.com", "count": 1}]


def test_redirect_unknown_code_is_404(client):
    resp = client.get("/does-not-exist", follow_redirects=False)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_expired_link_returns_410_and_does_not_redirect(client, auth_headers):
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2)).isoformat()
    code = _create_link(client, auth_headers, expires_at=future)

    # Not expired yet.
    resp = client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 302

    # Force it into the past directly in the DB rather than sleeping in the test.
    from app.database import SessionLocal
    from app.models import Link

    db = SessionLocal()
    link = db.query(Link).filter(Link.code == code).first()
    link.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
    db.commit()
    db.close()

    resp = client.get(f"/{code}", follow_redirects=False)
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "gone"


def test_creating_link_with_past_expiry_is_rejected(client, auth_headers):
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
    resp = client.post(
        "/links",
        json={"target_url": "https://example.com", "expires_at": past},
        headers=auth_headers,
    )
    assert resp.status_code == 422
