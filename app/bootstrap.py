"""Load the provided fleet and history on the first container start only."""

from random import Random

import seed as seed_data
from app.database import SessionLocal
from app.seed import import_seed


def initial_payload() -> dict:
    rng = Random(42)
    bookings = []
    for ship in seed_data.SHIPS:
        bookings.extend(seed_data.generate_bookings(ship["id"], rng))
    return {"ships": seed_data.SHIPS, "bookings": bookings}


def main():
    with SessionLocal() as session:
        inserted = import_seed(session, initial_payload(), only_if_empty=True)
    print(f"Database ready: {inserted} seed bookings added; existing data retained.", flush=True)


if __name__ == "__main__":
    main()
