# Spaceport backend

A single FastAPI service backed by PostgreSQL. Ships, booking validation, and availability
live together so booking checks and inserts can share one database transaction.
This repository includes the original seed generator and runs independently of the frontend.

## Run locally (without Docker)

Python 3.11 or newer is required. Run these commands from this `backend` directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python seed.py > seed.json
python -m app.dev --seed seed.json
```

Open http://127.0.0.1:8000/docs for interactive API documentation.
The development runner uses `pgserver` to start a real local PostgreSQL server,
applies migrations, imports the JSON, and starts FastAPI. Data persists in `~/.spaceport/<project-path-hash>/`, outside paths containing spaces.
Stop with Ctrl+C. Later starts can omit `--seed`. Keep and reuse the generated seed file:
regenerating it on another day changes the dates and is a different dataset.
This runner is for development; the Docker setup uses the official PostgreSQL image.

## Run with Docker Compose

From this repository root:

```sh
docker compose up --build -d
python3 seed.py > seed.json
docker compose cp seed.json api:/tmp/seed.json
docker compose exec api python -m app.seed /tmp/seed.json
```

API docs: http://127.0.0.1:8000/docs. PostgreSQL: localhost:5432.
The Compose database/user/password are all `spaceport`, for local development only.
Database data persists in the named volume. `docker compose down` stops the services.

## Use an existing PostgreSQL server

From `backend`, activate the virtual environment, install `requirements.txt`, copy
`.env.example` to `.env`, and set `DATABASE_URL` to your PostgreSQL connection URL.
The URL must start with `postgresql+psycopg://`. Then run:

```sh
alembic upgrade head
python -m app.seed seed.json
uvicorn app.main:app --reload
```

## API contract

JSON uses camelCase. Request timestamps must contain a UTC offset or `Z`.
Operating-hour decisions and date filters use `America/Chicago`, including DST.
PostgreSQL stores timezone-aware instants; booking responses may be expressed in UTC.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/ships` | All ships ordered by ID |
| GET | `/ships/{shipId}/unavailability?date=2026-09-26` | Opening/closing times and merged blocked intervals |
| POST | `/bookings` | Create a booking; returns 201 |
| GET | `/bookings?shipId=1&date=2026-09-26&limit=50&offset=0` | Paginated bookings, total, limit, offset |
| GET | `/health` | Database connectivity check; 503 when unavailable |

The dashboard endpoint's filters are optional. Results are sorted by ship, start time,
and booking ID. Page size is 1–200. Use `/ships` to map ship IDs to display names and
show ships with no bookings. There is no authentication, as requested.

Example booking:

```sh
curl -X POST http://127.0.0.1:8000/bookings \
  -H 'Content-Type: application/json' \
  -d '{"shipId":1,"pilotName":"Alex","startTime":"2026-09-26T10:00:00-05:00","endTime":"2026-09-26T12:00:00-05:00"}'
```

Validation failures return 422; missing ships return 404; booking conflicts return 409.
Errors use FastAPI's `detail` field (a string for business errors or a list for input errors).

## Scheduling decisions

- Bookings must have positive duration and a nonblank pilot name (up to 200 characters).
- They must fit within one Central calendar day's 06:00–22:00 operating hours.
  Starting at 06:00 or ending at 22:00 is valid. Refueling may extend outside these hours.
- A gap of exactly 30 minutes is valid. Overlaps or shorter gaps are rejected.
- Availability expands existing bookings by 30 minutes on each side, clips them to
  operating hours, and merges touching/overlapping intervals. The client must treat times
  outside the returned opening/closing boundaries as unavailable too.
- Intervals use half-open boundaries: a booking may end exactly where a blocked interval
  begins, or start exactly where one ends. The entire requested duration must be free.
- Availability is advisory; booking creation always revalidates against current data.
- No fixed slot length, booking-duration maximum, or prohibition on past dates is added,
  because the assignment specifies none. Seed history uses the same validation rules.

## Concurrency and persistence

Booking creation locks the selected ship row using `SELECT ... FOR UPDATE`, checks
conflicts, and inserts in the same transaction at READ COMMITTED isolation. A competing
request waits, then its conflict query sees the first committed booking. Different ships
can proceed independently. All application writers, including seed import, follow this
protocol. Direct SQL writers must follow it too; there is no database exclusion constraint
for overlaps. The database enforces foreign keys, positive duration, and nonblank names.

Seed import is atomic and skips exact duplicates (ship, pilot, start, end). Invalid or
conflicting input rolls back the entire import. Concurrent seed runs are serialized.
Schema changes use Alembic; application startup does not silently create tables.

## Tests and checks

```sh
pip install -r requirements-dev.txt
pytest -q
ruff check app tests migrations
ruff format --check app tests migrations
```

Tests start an isolated real PostgreSQL instance using `pgserver` by default. To use an
existing test server, set `TEST_DATABASE_URL=postgresql+psycopg://...` instead. The test
role needs permission to create/drop schemas. Each run creates a uniquely named schema,
applies the real migration, and removes only that schema when done.

Coverage includes overlapping and nested intervals, exact refueling boundaries,
operating-hour boundaries, UTC inputs, daylight-saving dates, invalid input, availability
merging, ship isolation, pagination/filtering, simultaneous HTTP booking requests,
transaction rollback, and importing/reimporting the supplied dataset.

## Layout

- `app/main.py`: routes and HTTP responses.
- `app/scheduling.py`: booking rules, locking, unavailable interval calculation.
- `app/models.py`, `app/schemas.py`: database tables and API contracts.
- `app/database.py`, `app/config.py`: sessions and environment configuration.
- `app/seed.py`: seed import; `app/dev.py`: local development runner.
- `migrations/`: versioned schema; `tests/`: PostgreSQL integration tests.

Companion frontend: https://github.com/SAISH1789/spaceport-frontend
The React frontend runs separately and calls this API over HTTP. PostgreSQL is accessed only by this backend.

Technical references: [PostgreSQL row locking](https://www.postgresql.org/docs/17/explicit-locking.html),
[transaction isolation](https://www.postgresql.org/docs/18/transaction-iso.html),
and [FastAPI testing](https://fastapi.tiangolo.com/reference/testclient/).
