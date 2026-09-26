import importlib.util
from pathlib import Path
from random import Random

from sqlalchemy import func, select

from app.models import Booking, Ship
from app.seed import import_seed


def test_complete_supplied_seed(sessions):
    path = Path(__file__).resolve().parents[1] / "seed.py"
    spec = importlib.util.spec_from_file_location("assignment_seed", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rng = Random(42)
    bookings = []
    for ship in module.SHIPS:
        bookings.extend(module.generate_bookings(ship["id"], rng))
    payload = {"ships": module.SHIPS, "bookings": bookings}
    with sessions() as session:
        assert import_seed(session, payload) == len(bookings)
        assert import_seed(session, payload) == 0
        assert session.scalar(select(func.count()).select_from(Ship)) == 5
        assert session.scalar(select(func.count()).select_from(Booking)) == len(bookings)
