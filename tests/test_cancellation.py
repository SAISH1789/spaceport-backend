from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import scheduling
from app.models import Booking
from app.scheduling import cancel_booking
from app.seed import import_seed


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(scheduling, "utc_now", lambda: datetime(2030, 9, 27, 12, tzinfo=UTC))


def payload(start="10:00", end="11:00"):
    return {
        "shipId": 1,
        "pilotName": "Cancellation Test",
        "startTime": f"2030-09-28T{start}:00-05:00",
        "endTime": f"2030-09-28T{end}:00-05:00",
    }


def create(client, **kwargs):
    response = client.post("/bookings", json=payload(**kwargs))
    assert response.status_code == 201
    assert response.json()["status"] == "confirmed"
    assert response.json()["cancelledAt"] is None
    return response.json()["id"]


def test_cancel_preserves_record_and_releases_slot(client, sessions):
    booking_id = create(client)
    endpoint = "/ships/1/unavailability?date=2030-09-28"
    assert len(client.get(endpoint).json()["unavailable"]) == 1
    response = client.post(f"/bookings/{booking_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancelledAt"] is not None
    assert client.get(endpoint).json()["unavailable"] == []
    replacement_id = create(client)
    assert replacement_id != booking_id
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 2
    assert client.get("/bookings?status=cancelled").json()["items"][0]["id"] == booking_id
    assert client.get("/bookings?status=confirmed").json()["items"][0]["id"] == replacement_id
    assert client.get("/bookings?status=unknown").status_code == 422


def test_repeated_cancellation_keeps_timestamp_even_after_departure(client, monkeypatch):
    booking_id = create(client)
    first = client.post(f"/bookings/{booking_id}/cancel").json()
    monkeypatch.setattr(scheduling, "utc_now", lambda: datetime(2031, 1, 1, tzinfo=UTC))
    second = client.post(f"/bookings/{booking_id}/cancel")
    assert second.status_code == 200
    assert second.json() == first


def test_missing_booking(client):
    assert client.post("/bookings/999999/cancel").status_code == 404


@pytest.mark.parametrize("delta,status", [(-1, 200), (0, 409), (1, 409), (7200, 409)])
def test_departure_boundary(client, monkeypatch, delta, status):
    booking_id = create(client)
    now = datetime(2030, 9, 28, 15, tzinfo=UTC) + timedelta(seconds=delta)
    monkeypatch.setattr(scheduling, "utc_now", lambda: now)
    assert client.post(f"/bookings/{booking_id}/cancel").status_code == status
    assert client.get("/bookings").json()["items"][0]["status"] == (
        "cancelled" if status == 200 else "confirmed"
    )


def test_other_bookings_keep_their_buffers(client):
    first = create(client)
    create(client, start="11:30", end="12:30")
    assert client.post(f"/bookings/{first}/cancel").status_code == 200
    blocks = client.get("/ships/1/unavailability?date=2030-09-28").json()["unavailable"]
    assert blocks == [
        {"startTime": "2030-09-28T11:00:00-05:00", "endTime": "2030-09-28T13:00:00-05:00"}
    ]
    assert client.post("/bookings", json=payload("10:00", "11:01")).status_code == 409
    assert client.post("/bookings", json=payload()).status_code == 201


def test_seed_reimport_does_not_reactivate(client, sessions):
    seed = {"ships": [{"id": 1, "name": "USS Wanderer"}], "bookings": [payload()]}
    with sessions() as session:
        assert import_seed(session, seed) == 1
    booking_id = client.get("/bookings").json()["items"][0]["id"]
    assert client.post(f"/bookings/{booking_id}/cancel").status_code == 200
    with sessions() as session:
        assert import_seed(session, seed) == 0
        assert session.get(Booking, booking_id).status == "cancelled"


def test_simultaneous_cancellations_are_idempotent(client):
    booking_id = create(client)
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=5)
        return client.post(f"/bookings/{booking_id}/cancel")

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: attempt(), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()


def test_booking_waits_for_cancellation_commit(client, sessions):
    booking_id = create(client)
    started = Event()

    def attempt():
        started.set()
        return client.post("/bookings", json=payload())

    with ThreadPoolExecutor(max_workers=1) as pool:
        with sessions() as session, session.begin():
            cancel_booking(session, booking_id)
            future = pool.submit(attempt)
            assert started.wait(timeout=5)
            # The insert cannot finish while this transaction owns the ship lock.
            assert not future.done()
        response = future.result(timeout=5)
    assert response.status_code == 201
    assert client.get("/bookings?status=confirmed").json()["total"] == 1


@pytest.mark.parametrize(
    "assignment",
    [
        "status = 'unknown'",
        "status = 'cancelled'",
        "cancelled_at = CURRENT_TIMESTAMP",
    ],
)
def test_database_rejects_inconsistent_state(client, sessions, assignment):
    booking_id = create(client)
    with sessions() as session, pytest.raises(IntegrityError), session.begin():
        session.execute(
            text(f"UPDATE bookings SET {assignment} WHERE id = :id"), {"id": booking_id}
        )
