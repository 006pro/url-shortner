def test_delete_is_soft_and_idempotent_410(client, auth_headers):
    create_resp = client.post(
        "/links", json={"target_url": "https://example.com", "custom_alias": "to-delete"}, headers=auth_headers
    )
    code = create_resp.json()["code"]

    delete_resp = client.delete(f"/links/{code}", headers=auth_headers)
    assert delete_resp.status_code == 204

    redirect_resp = client.get(f"/{code}", follow_redirects=False)
    assert redirect_resp.status_code == 410

    second_delete_resp = client.delete(f"/links/{code}", headers=auth_headers)
    assert second_delete_resp.status_code == 410


def test_deleted_code_cannot_be_reused(client, auth_headers):
    client.post(
        "/links", json={"target_url": "https://example.com", "custom_alias": "reused-code"}, headers=auth_headers
    )
    client.delete("/links/reused-code", headers=auth_headers)

    retry_resp = client.post(
        "/links", json={"target_url": "https://example.com/new", "custom_alias": "reused-code"}, headers=auth_headers
    )
    assert retry_resp.status_code == 409
    assert retry_resp.json()["error"]["code"] == "conflict"


def test_delete_nonexistent_code_is_404(client, auth_headers):
    resp = client.delete("/links/never-existed", headers=auth_headers)
    assert resp.status_code == 404
