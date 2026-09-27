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

## Run everything with Docker (recommended)

Install and open Docker Desktop first. No local Python, Node, Redis, or PostgreSQL
installation is needed. Stop the local FastAPI/Vite processes on ports 8000/5173.

From this backend repository:

```sh
docker compose up --build -d --wait
```

This starts PostgreSQL, Redis, and FastAPI. It installs Python dependencies inside
the image, applies all Alembic migrations, and seeds the supplied fleet/history only
when both tables are empty. An existing database is left intact. Failed seed imports
roll back and can retry on restart. Rebuilding never resets bookings or cancellations.

Once the backend command succeeds, run from the frontend repository:

```sh
docker compose up --build -d --wait
```

Open http://127.0.0.1:5173 for the UI and http://127.0.0.1:8000/docs for Swagger.
The backend creates `spaceport-network`; the frontend joins it and reaches the API by
its network alias `spaceport-api`. PostgreSQL and Redis are internal services without
host ports. The frontend does not need host.docker.internal or a local backend process.

Useful backend commands:

```sh
docker compose ps
docker compose logs -f api
docker compose exec db psql -U spaceport -d spaceport
docker compose exec redis redis-cli ping
```

The default database/user/password are `spaceport`, for local development only.
The named volume persists the Docker database across restarts and normal shutdowns.
This is separate from the existing pgserver database: locally created bookings are
not automatically copied into Docker. Do not use `down -v` unless you intend to delete
Docker's database. Stop the frontend project first with `docker compose down`, then
run the same command in the backend project so the shared network can be removed.

Docker configuration was checked, but full container execution requires Docker Desktop.

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
PostgreSQL stores timezone-aware instants; booking responses use UTC (`Z`).
Availability responses use Central Time offsets.

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/ships` | All ships ordered by ID |
| GET | `/ships/{shipId}/unavailability?date=2026-09-26` | Opening/closing times and merged blocked intervals |
| POST | `/bookings` | Create a booking; returns 201 |
| POST | `/bookings/{id}/cancel` | Cancel before departure; returns 200, including repeat requests |
| GET | `/bookings?shipId=1&date=2026-09-26&limit=50&offset=0` | Paginated bookings, total, limit, offset |
| GET | `/health` | Database connectivity check; 503 when unavailable |

The dashboard endpoint's filters are optional, including `status=confirmed` or `status=cancelled`.
Without a status filter it includes both confirmed and cancelled records. Results are sorted by ship, start time,
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

## Cancellation

`POST /bookings/{id}/cancel` requires no request body. It returns the booking with
`status: "cancelled"` and `cancelledAt` in UTC. Confirmed bookings have `cancelledAt: null`.
Only confirmed bookings whose start is strictly after the server's current time can
be cancelled. A first request at/after departure returns 409; a missing ID returns 404.
Repeating a successful cancellation returns 200 and preserves the original timestamp,
even if departure has since passed.

Cancelled rows remain in the database but are excluded from availability and booking
conflict checks. Other confirmed bookings still impose their own refueling buffers.
Seed reimport does not reactivate cancelled records. Cancellation and creation use
the same ship-row lock within transactions. Database constraints restrict status to
confirmed/cancelled and require cancellation timestamps to agree with status.
There is no authentication; the original assignment does not define booking ownership.

Upgrade an existing database with `alembic upgrade head`, then restart FastAPI.
For the bundled local database, stopping and rerunning `python -m app.dev` applies
the migration automatically. Migration 0002 preserves all existing records as
confirmed. Downgrade refuses to remove status fields if any cancelled bookings exist,
because that would reactivate their reserved times.

## Redis ship catalogue cache

`GET /ships` uses Redis first; on a miss it queries PostgreSQL and caches the ordered
JSON list for 300 seconds. The response body is unchanged. The `X-Cache` header shows
`HIT` (no PostgreSQL query), `MISS` (database read), or `BYPASS` (disabled/unavailable).
An empty fleet is cacheable. Invalid cached JSON is replaced from PostgreSQL.

Bookings, cancellation, and unavailability are never cached. Redis is optional:
connection/command timeouts are 200 ms with automatic retries disabled; failures
fall back to PostgreSQL. `/health` checks PostgreSQL, not the optional cache.
A miss can still fail if PostgreSQL itself is unavailable.

Configuration (`.env` or environment variables):

- `REDIS_URL=redis://127.0.0.1:6379/0` (default); set to an empty string to disable.
- `SHIPS_CACHE_TTL_SECONDS=300` (1–86400).
- `REDIS_KEY_PREFIX=spaceport`; use a different prefix for independent environments.

Cache keys include a hash of the database connection URL and a schema version. Keep
connection settings consistent between the API and seed importer. After seed import
commits, the cache generation rotates. A reader that started before that commit can
only populate the previous generation, not the new one. Generation keys persist;
catalogue entries expire. The local Redis configuration uses 64 MB with volatile-LRU
eviction and no persistence, because it is a disposable cache.

Direct SQL changes bypass invalidation and may remain invisible for up to the TTL.
If Redis is down during seed invalidation, its old entries may likewise remain until
expiry if Redis recovers before they expire. Multiple simultaneous cold requests may
query PostgreSQL; no distributed fill lock is needed for this small fleet catalogue.

### Local Mac setup

Install the updated dependencies in your active virtual environment:

```sh
python -m pip install -r requirements-dev.txt
```

In a separate Terminal tab, from this backend directory:

```sh
./scripts/redis-dev.sh
```

On the original development Mac, Redis 7.4.7 binaries are installed under
`~/.local/share/spaceport-redis/bin`. The script uses these when Redis is absent from
PATH. On other machines, install Redis first, or use `docker compose up -d redis`.
Restart `python -m app.dev` after updating dependencies. Docker Compose already sets
`REDIS_URL=redis://redis:6379/0` and starts the Redis service alongside the backend.

Check headers twice (normally first MISS, then HIT unless already cached):

```sh
curl -i http://127.0.0.1:8000/ships
curl -i http://127.0.0.1:8000/ships
```

To inspect Redis on this Mac:

```sh
~/.local/share/spaceport-redis/bin/redis-cli ping
~/.local/share/spaceport-redis/bin/redis-cli --scan --pattern 'spaceport:*:ships:v1:*'
```

Then use `GET <key>` and `TTL <key>` on a returned catalogue key. A generation key
contains only the current generation identifier. No frontend changes are required.

Automated cache tests use fakeredis and count real PostgreSQL queries; they cover
hits, misses, cache corruption, eviction, empty results, failed reads/writes, and
seed invalidation races. Design reference: [Redis cache-aside](https://redis.io/docs/latest/develop/use-cases/cache-aside/redis-py/).
