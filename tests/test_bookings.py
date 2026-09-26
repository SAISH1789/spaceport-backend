from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Booking
from app.scheduling import create_booking
from app.schemas import BookingCreate
from app.seed import import_seed


def payload(start="10:00", end="12:00", ship=1, day="2026-09-26", offset="-05:00"):
    return {
        "shipId": ship,
        "pilotName": " Alex ",
        "startTime": f"{day}T{start}:00{offset}",
        "endTime": f"{day}T{end}:00{offset}",
    }


def test_create_and_dashboard(client):
    assert client.get("/health").status_code == 200
    assert len(client.get("/ships").json()) == 2
    response = client.post("/bookings", json=payload())
    assert response.status_code == 201
    assert response.json()["pilotName"] == "Alex"
    assert response.json()["id"] > 0
    assert client.post("/bookings", json=payload(ship=2)).status_code == 201
    page = client.get("/bookings?shipId=1&date=2026-09-26&limit=1").json()
    assert page["total"] == 1
    assert len(page["items"]) == 1
    assert page["items"][0]["shipId"] == 1
    assert client.get("/bookings?offset=1&limit=1").json()["items"][0]["shipId"] == 2
    assert client.get("/bookings?date=2026-09-27").json()["total"] == 0


@pytest.mark.parametrize(
    "start,end,expected",
    [
        ("10:00", "12:00", 409),
        ("11:00", "13:00", 409),
        ("09:00", "13:00", 409),
        ("10:30", "11:00", 409),
        ("09:00", "09:31", 409),
        ("12:29", "13:00", 409),
        ("09:00", "09:30", 201),
        ("12:30", "13:00", 201),
    ],
)
def test_conflicts_and_exact_buffer(client, start, end, expected):
    assert client.post("/bookings", json=payload()).status_code == 201
    assert client.post("/bookings", json=payload(start, end)).status_code == expected


@pytest.mark.parametrize(
    "start,end",
    [
        ("05:59", "07:00"),
        ("21:00", "22:01"),
        ("12:00", "12:00"),
        ("13:00", "12:00"),
    ],
)
def test_invalid_times(client, start, end):
    assert client.post("/bookings", json=payload(start, end)).status_code == 422


@pytest.mark.parametrize(
    "day,offset",
    [
        ("2026-01-10", "-06:00"),
        ("2026-07-10", "-05:00"),
        ("2026-03-08", "-05:00"),
        ("2026-11-01", "-06:00"),
    ],
)
def test_open_close_and_daylight_saving(client, day, offset):
    assert (
        client.post("/bookings", json=payload("06:00", "22:00", day=day, offset=offset)).status_code
        == 201
    )
    result = client.get(f"/ships/1/unavailability?date={day}").json()
    assert result["opensAt"].endswith(offset)
    assert result["unavailable"] == [
        {
            "startTime": result["opensAt"],
            "endTime": result["closesAt"],
        }
    ]


def test_invalid_input(client):
    assert client.post("/bookings", json=payload(ship=99)).status_code == 404
    assert client.get("/ships/99/unavailability?date=2026-09-26").status_code == 404
    data = payload()
    data["pilotName"] = "   "
    assert client.post("/bookings", json=data).status_code == 422
    data = payload(offset="")
    assert client.post("/bookings", json=data).status_code == 422
    data = payload()
    data["endTime"] = "2026-09-27T07:00:00-05:00"
    assert client.post("/bookings", json=data).status_code == 422
    assert client.get("/bookings?limit=0").status_code == 422
    assert client.get("/ships/1/unavailability?date=invalid").status_code == 422


def test_utc_input(client):
    data = payload()
    data.update(startTime="2026-09-26T11:00:00Z", endTime="2026-09-26T12:00:00Z")
    assert client.post("/bookings", json=data).status_code == 201
    data.update(startTime="2026-09-26T10:59:00Z")
    assert client.post("/bookings", json=data).status_code == 422


def test_availability_merges_buffers_and_isolates_ships(client):
    assert client.post("/bookings", json=payload()).status_code == 201
    assert client.post("/bookings", json=payload("12:30", "14:00")).status_code == 201
    result = client.get("/ships/1/unavailability?date=2026-09-26").json()
    assert result["unavailable"] == [
        {
            "startTime": "2026-09-26T09:30:00-05:00",
            "endTime": "2026-09-26T14:30:00-05:00",
        }
    ]
    assert client.get("/ships/2/unavailability?date=2026-09-26").json()["unavailable"] == []
    assert client.get("/ships/1/unavailability?date=2026-09-27").json()["unavailable"] == []


def test_simultaneous_requests(client, sessions):
    barrier = Barrier(2)

    def attempt():
        barrier.wait(timeout=5)
        return client.post("/bookings", json=payload()).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == [201, 409]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 1


def test_import_is_idempotent_and_atomic(sessions):
    seed = {"ships": [{"id": 1, "name": "USS Wanderer"}], "bookings": [payload()]}
    with sessions() as session:
        assert import_seed(session, seed) == 1
        assert import_seed(session, seed) == 0
    seed["bookings"] = [payload("14:00", "15:00"), payload("11:00", "13:00")]
    with sessions() as session:
        with pytest.raises(HTTPException):
            import_seed(session, seed)
        assert session.scalar(select(func.count()).select_from(Booking)) == 1


def test_failed_booking_rolls_back(sessions):
    with sessions() as session:
        with session.begin():
            create_booking(session, BookingCreate.model_validate(payload()))
        with pytest.raises(HTTPException), session.begin():
            create_booking(session, BookingCreate.model_validate(payload()))
        with session.begin():
            create_booking(session, BookingCreate.model_validate(payload("12:30", "13:30")))
