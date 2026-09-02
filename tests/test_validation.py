import pytest

from app.schemas import MAX_TARGET_URL_LENGTH


@pytest.mark.parametrize("alias", ["ab", "a" * 33, "has space", "has/slash", "has?query"])
def test_invalid_alias_shapes_are_rejected(client, auth_headers, alias):
    resp = client.post(
        "/links", json={"target_url": "https://example.com", "custom_alias": alias}, headers=auth_headers
    )
    assert resp.status_code == 422


def test_reserved_alias_is_rejected(client, auth_headers):
    resp = client.post(
        "/links", json={"target_url": "https://example.com", "custom_alias": "links"}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable"


def test_duplicate_custom_alias_returns_409(client, auth_headers):
    client.post(
        "/links", json={"target_url": "https://example.com", "custom_alias": "taken"}, headers=auth_headers
    )
    resp = client.post(
        "/links", json={"target_url": "https://example.com/other", "custom_alias": "taken"}, headers=auth_headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_missing_target_url_is_422(client, auth_headers):
    resp = client.post("/links", json={}, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_empty_target_url_is_422(client, auth_headers):
    resp = client.post("/links", json={"target_url": ""}, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_oversized_target_url_is_rejected(client, auth_headers):
    overlong_url = "https://example.com/" + ("a" * MAX_TARGET_URL_LENGTH)
    resp = client.post("/links", json={"target_url": overlong_url}, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_target_url_at_max_length_is_accepted(client, auth_headers):
    prefix = "https://example.com/"
    max_length_url = prefix + ("a" * (MAX_TARGET_URL_LENGTH - len(prefix)))
    assert len(max_length_url) == MAX_TARGET_URL_LENGTH

    resp = client.post("/links", json={"target_url": max_length_url}, headers=auth_headers)
    assert resp.status_code == 201
