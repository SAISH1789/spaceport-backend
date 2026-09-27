"""Import a generated seed JSON atomically; exact repeats are skipped."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.cache import get_ship_cache
from app.database import SessionLocal
from app.models import Booking, Ship
from app.scheduling import create_booking
from app.schemas import BookingCreate


def import_seed(session: Session, payload: dict, *, only_if_empty: bool = False) -> int:
    inserted = 0
    with session.begin():
        # Serializes seed runs. Runtime booking requests use the same per-ship lock.
        session.execute(text("SELECT pg_advisory_xact_lock(7312026)"))
        if only_if_empty and (
            session.scalar(select(Ship.id).limit(1)) is not None
            or session.scalar(select(Booking.id).limit(1)) is not None
        ):
            return 0
        for item in sorted(payload["ships"], key=lambda item: item["id"]):
            ship = session.scalar(select(Ship).where(Ship.id == item["id"]).with_for_update())
            if ship is None:
                session.add(Ship(id=item["id"], name=item["name"]))
                session.flush()
            else:
                ship.name = item["name"]
        for item in payload["bookings"]:
            data = BookingCreate.model_validate(item)
            # Take the lock before checking duplicates, just as for normal inserts.
            session.scalar(select(Ship).where(Ship.id == data.ship_id).with_for_update())
            exists = session.scalar(
                select(Booking.id)
                .where(
                    Booking.ship_id == data.ship_id,
                    Booking.pilot_name == data.pilot_name,
                    Booking.start_time == data.start_time,
                    Booking.end_time == data.end_time,
                )
                .limit(1)
            )
            if exists is None:
                create_booking(session, data)
                inserted += 1
        session.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('ships', 'id'), "
                "COALESCE((SELECT MAX(id) FROM ships), 1), EXISTS(SELECT 1 FROM ships))"
            )
        )
    # Invalidate only after the complete seed transaction commits.
    get_ship_cache().invalidate()
    return inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.path.read_text())
    with SessionLocal() as session:
        inserted = import_seed(session, payload)
    print(f"Imported {inserted} bookings; exact duplicates skipped.")


if __name__ == "__main__":
    main()
