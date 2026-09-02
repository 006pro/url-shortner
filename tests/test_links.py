def test_create_link_auto_code(client, auth_headers):
    resp = client.post("/links", json={"target_url": "https://example.com/page"}, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["code"]) == 7
    assert body["target_url"] == "https://example.com/page"
    assert body["short_url"].endswith(body["code"])


def test_create_link_custom_alias(client, auth_headers):
    resp = client.post(
        "/links",
        json={"target_url": "https://example.com", "custom_alias": "my-page"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["code"] == "my-page"


def test_create_link_requires_api_key(client):
    resp = client.post("/links", json={"target_url": "https://example.com"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_create_link_invalid_api_key(client):
    resp = client.post(
        "/links", json={"target_url": "https://example.com"}, headers={"X-API-Key": "usk_not_a_real_key"}
    )
    assert resp.status_code == 401


def test_list_links_pagination_and_click_count(client, auth_headers):
    for i in range(3):
        client.post("/links", json={"target_url": f"https://example.com/{i}"}, headers=auth_headers)

    resp = client.get("/links?page=1&page_size=2", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert all(item["click_count"] == 0 for item in body["items"])

    resp_page_2 = client.get("/links?page=2&page_size=2", headers=auth_headers)
    assert len(resp_page_2.json()["items"]) == 1


def test_links_are_isolated_per_api_key(client, auth_headers, other_api_key):
    create_resp = client.post("/links", json={"target_url": "https://example.com"}, headers=auth_headers)
    code = create_resp.json()["code"]

    other_headers = {"X-API-Key": other_api_key}

    stats_resp = client.get(f"/links/{code}/stats", headers=other_headers)
    assert stats_resp.status_code == 404

    delete_resp = client.delete(f"/links/{code}", headers=other_headers)
    assert delete_resp.status_code == 404

    list_resp = client.get("/links", headers=other_headers)
    assert list_resp.json()["total"] == 0
