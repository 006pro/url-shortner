from app.config import settings


def test_rate_limit_blocks_after_max_requests(client, auth_headers):
    limit = settings.rate_limit_max_requests

    for i in range(limit):
        resp = client.post("/links", json={"target_url": f"https://example.com/{i}"}, headers=auth_headers)
        assert resp.status_code == 201

    blocked_resp = client.post(
        "/links", json={"target_url": "https://example.com/over-limit"}, headers=auth_headers
    )
    assert blocked_resp.status_code == 429
    assert blocked_resp.json()["error"]["code"] == "rate_limited"
    assert "retry_after_seconds" in blocked_resp.json()["error"]["details"]


def test_rate_limit_is_scoped_per_api_key(client, auth_headers, other_api_key):
    limit = settings.rate_limit_max_requests

    for i in range(limit):
        resp = client.post("/links", json={"target_url": f"https://example.com/{i}"}, headers=auth_headers)
        assert resp.status_code == 201

    # First key is now rate-limited...
    assert client.post(
        "/links", json={"target_url": "https://example.com/blocked"}, headers=auth_headers
    ).status_code == 429

    # ...but a different API key has its own independent quota.
    other_resp = client.post(
        "/links", json={"target_url": "https://example.com/other"}, headers={"X-API-Key": other_api_key}
    )
    assert other_resp.status_code == 201
