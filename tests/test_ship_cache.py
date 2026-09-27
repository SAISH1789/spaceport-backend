from unittest.mock import Mock

import fakeredis
import pytest
from pydantic import ValidationError
from redis.exceptions import ConnectionError
from sqlalchemy import event, text

from app import seed
from app.cache import ShipCache, get_ship_cache
from app.main import app
from app.schemas import ShipOut


@pytest.fixture()
def cache(client, monkeypatch):
    instance = ShipCache(fakeredis.FakeRedis(decode_responses=True), "test:ships", ttl=300)
    app.dependency_overrides[get_ship_cache] = lambda: instance
    monkeypatch.setattr(seed, "get_ship_cache", lambda: instance)
    yield instance
    instance.close()


def test_hit_skips_postgres_and_payload_is_unchanged(client, cache, db_engine):
    queries = []

    def record(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db_engine, "before_cursor_execute", record)
    try:
        first = client.get("/ships")
        assert first.status_code == 200
        assert first.headers["x-cache"] == "MISS"
        assert len(queries) > 0
        queries.clear()
        second = client.get("/ships")
        assert second.headers["x-cache"] == "HIT"
        assert second.json() == first.json()
        assert queries == []
        _, key = cache.read()
        assert 0 < cache.client.ttl(key) <= 300
    finally:
        event.remove(db_engine, "before_cursor_execute", record)


def test_disabled_cache_uses_postgres(client):
    assert client.get("/ships").headers["x-cache"] == "BYPASS"


def test_redis_unavailable_still_returns_fleet(client, cache, monkeypatch):
    monkeypatch.setattr(cache.client, "get", Mock(side_effect=ConnectionError("offline")))
    response = client.get("/ships")
    assert response.status_code == 200
    assert response.headers["x-cache"] == "BYPASS"
    assert len(response.json()) == 2


def test_cache_write_failure_does_not_fail_request(client, cache, monkeypatch):
    cache.read()  # initialize generation before simulating a write failure
    monkeypatch.setattr(cache.client, "set", Mock(side_effect=ConnectionError("offline")))
    assert client.get("/ships").status_code == 200


@pytest.mark.parametrize("payload", ["invalid json", '{"not":"a list"}', '[{"id":"bad"}]'])
def test_bad_payload_replaced_from_postgres(client, cache, payload):
    _, key = cache.read()
    cache.client.set(key, payload)
    response = client.get("/ships")
    assert response.headers["x-cache"] == "MISS"
    assert len(response.json()) == 2
    assert client.get("/ships").headers["x-cache"] == "HIT"


def test_empty_fleet_can_be_cached(client, cache, sessions):
    with sessions.begin() as session:
        session.execute(text("DELETE FROM ships"))
    assert client.get("/ships").json() == []
    response = client.get("/ships")
    assert response.json() == []
    assert response.headers["x-cache"] == "HIT"


def test_seed_commit_invalidates_and_old_reader_cannot_restore_stale_cache(client, cache, sessions):
    original = client.get("/ships").json()
    _, old_key = cache.read()
    with sessions() as session:
        seed.import_seed(session, {"ships": [{"id": 1, "name": "Renamed ship"}], "bookings": []})
    # Simulate a request that read the old catalogue before the seed commit.
    cache.write(old_key, [ShipOut.model_validate(item) for item in original])
    response = client.get("/ships")
    assert response.headers["x-cache"] == "MISS"
    assert response.json()[0]["name"] == "Renamed ship"
    assert client.get("/ships").headers["x-cache"] == "HIT"


def test_failed_seed_does_not_invalidate(client, cache, sessions):
    client.get("/ships")
    generation = cache.client.get(cache.generation_key)
    with sessions() as session, pytest.raises(ValidationError):
        seed.import_seed(session, {"ships": [{"id": 1, "name": "Not committed"}], "bookings": [{}]})
    assert cache.client.get(cache.generation_key) == generation
    assert client.get("/ships").json()[0]["name"] == "USS Wanderer"


def test_lost_generation_marker_never_reuses_old_data(client, cache):
    client.get("/ships")
    _, old_key = cache.read()
    cache.client.delete(cache.generation_key)
    assert client.get("/ships").headers["x-cache"] == "MISS"
    _, new_key = cache.read()
    assert old_key != new_key


def test_evicted_entry_reloads_from_postgres(client, cache):
    client.get("/ships")
    _, key = cache.read()
    cache.client.delete(key)
    assert client.get("/ships").headers["x-cache"] == "MISS"
