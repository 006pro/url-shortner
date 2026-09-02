import pytest

UNSAFE_URLS = [
    "http://localhost:8000/admin",
    "http://127.0.0.1/admin",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
    "http://10.0.0.5/internal",
    "http://192.168.1.1/router",
    "ftp://example.com/file",
    "not-a-url",
]


@pytest.mark.parametrize("target_url", UNSAFE_URLS)
def test_unsafe_urls_are_rejected(client, auth_headers, target_url):
    resp = client.post("/links", json={"target_url": target_url}, headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unprocessable"


def test_public_https_url_is_accepted(client, auth_headers):
    resp = client.post("/links", json={"target_url": "https://example.com/page"}, headers=auth_headers)
    assert resp.status_code == 201
