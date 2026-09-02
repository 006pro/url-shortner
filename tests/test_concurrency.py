import threading

from fastapi.testclient import TestClient

from app.main import app


def test_two_simultaneous_requests_for_the_same_alias_only_one_succeeds(auth_headers):
    """Two requests race to claim the same custom_alias at (as close to)
    the same instant as possible. Exactly one must succeed (201) and the
    other must fail cleanly (409) -- this is what the unique constraint on
    links.code plus catching IntegrityError in app/crud.py is for (see
    _insert_link): a check-then-insert approach would have a race window
    where both requests could pass the "is it taken" check before either
    commits. Each thread gets its own TestClient/app instance so the two
    requests genuinely run through separate DB sessions/connections
    concurrently, rather than being serialized by a shared test client.
    """
    barrier = threading.Barrier(2)
    results: list[int] = []
    results_lock = threading.Lock()

    def create_link():
        with TestClient(app) as client:
            barrier.wait()  # line both threads up to fire as close together as possible
            resp = client.post(
                "/links",
                json={"target_url": "https://example.com/race", "custom_alias": "race-alias"},
                headers=auth_headers,
            )
        with results_lock:
            results.append(resp.status_code)

    threads = [threading.Thread(target=create_link) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(results) == [201, 409]
