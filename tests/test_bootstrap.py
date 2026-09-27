import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.models import Booking, Ship
from app.seed import import_seed


def seed_payload(name="Initial pilot"):
    return {
        "ships": [{"id": 1, "name": "Serenity"}],
        "bookings": [
            {
                "shipId": 1,
                "pilotName": name,
                "startTime": "2030-09-28T10:00:00-05:00",
                "endTime": "2030-09-28T11:00:00-05:00",
            }
        ],
    }


def test_first_start_seeds_and_restart_preserves_records(sessions):
    with sessions() as session:
        with session.begin():
            session.execute(text("TRUNCATE bookings, ships RESTART IDENTITY CASCADE"))
        assert import_seed(session, seed_payload(), only_if_empty=True) == 1
        # A later generated dataset must not change existing user records.
        assert import_seed(session, seed_payload("Different pilot"), only_if_empty=True) == 0
        assert session.scalar(select(Booking.pilot_name)) == "Initial pilot"


def test_failed_first_seed_can_be_retried(sessions):
    with sessions() as session:
        with session.begin():
            session.execute(text("TRUNCATE bookings, ships RESTART IDENTITY CASCADE"))
        bad = seed_payload()
        bad["bookings"].append({})
        with pytest.raises(ValidationError):
            import_seed(session, bad, only_if_empty=True)
        assert import_seed(session, seed_payload(), only_if_empty=True) == 1


def test_preexisting_fleet_not_overwritten(sessions):
    with sessions() as session:
        assert import_seed(session, seed_payload(), only_if_empty=True) == 0
        assert session.scalar(select(Ship.name).where(Ship.id == 1)) == "USS Wanderer"
