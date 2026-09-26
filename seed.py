"""
Generates seed data for the Spaceport Charter System as a single JSON file.

    python seed.py > seed.json

Output is a JSON object with `ships` and `bookings`. Load it however you like.
"""

import json
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
OPERATING_START_HOUR = 6
OPERATING_END_HOUR = 22
REFUEL_BUFFER = timedelta(minutes=30)

DAYS_OF_HISTORY = 365
BOOKINGS_PER_SHIP = 600

SHIPS = [
    {"id": 1, "name": "USS Wanderer"},
    {"id": 2, "name": "Nostromo"},
    {"id": 3, "name": "Serenity"},
    {"id": 4, "name": "Rocinante"},
    {"id": 5, "name": "Millennium Falcon"},
]

PILOTS = [
    "Ellen Ripley", "Han Solo", "Malcolm Reynolds", "Kathryn Janeway",
    "James Holden", "Naomi Nagata", "Jean-Luc Picard", "Nyota Uhura",
    "Poe Dameron", "Rey Skywalker", "Chrisjen Avasarala", "Bobbie Draper",
    "Leia Organa", "Wedge Antilles", "Hikaru Sulu", "Beverly Crusher",
    "Cara Dune", "Din Djarin", "Carol Danvers", "Peter Quill",
]


def generate_bookings(ship_id, rng):
    bookings = []
    today = datetime.now(CENTRAL).date()
    cursor = None
    day = today - timedelta(days=DAYS_OF_HISTORY)

    while len(bookings) < BOOKINGS_PER_SHIP and day <= today + timedelta(days=30):
        day_open = datetime(day.year, day.month, day.day, OPERATING_START_HOUR, tzinfo=CENTRAL)
        day_close = datetime(day.year, day.month, day.day, OPERATING_END_HOUR, tzinfo=CENTRAL)

        if cursor is None or cursor < day_open:
            cursor = day_open
        cursor += timedelta(minutes=rng.choice([30, 60, 90, 120, 240, 480]))

        if cursor >= day_close:
            day += timedelta(days=1)
            cursor = None
            continue

        end = cursor + timedelta(minutes=rng.choice([60, 90, 120, 150, 180, 240]))
        if end > day_close:
            day += timedelta(days=1)
            cursor = None
            continue

        bookings.append({
            "shipId": ship_id,
            "pilotName": rng.choice(PILOTS),
            "startTime": cursor.isoformat(),
            "endTime": end.isoformat(),
        })
        cursor = end + REFUEL_BUFFER

    return bookings


def main():
    rng = random.Random(42)
    bookings = []
    for ship in SHIPS:
        bookings.extend(generate_bookings(ship["id"], rng))
    print(json.dumps({"ships": SHIPS, "bookings": bookings}, indent=2))


if __name__ == "__main__":
    main()
