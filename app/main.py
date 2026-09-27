from contextlib import asynccontextmanager
from datetime import date as Date
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.cache import ShipCache, get_ship_cache
from app.config import settings
from app.database import get_session
from app.models import Booking, Ship
from app.scheduling import cancel_booking, create_booking, operating_hours, unavailable_intervals
from app.schemas import BookingCreate, BookingOut, BookingPage, ShipOut, Unavailability
from app.status import BookingStatus


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    get_ship_cache().close()


app = FastAPI(title="Spaceport Charter API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
DB = Annotated[Session, Depends(get_session)]


@app.get("/health", tags=["health"])
def health(session: DB):
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ok"}


@app.get("/ships", response_model=list[ShipOut], tags=["ships"])
def list_ships(
    session: DB, response: Response, cache: Annotated[ShipCache, Depends(get_ship_cache)]
):
    cached, key = cache.read()
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return cached
    ships = [
        ShipOut.model_validate(ship) for ship in session.scalars(select(Ship).order_by(Ship.id))
    ]
    cache.write(key, ships)
    response.headers["X-Cache"] = "MISS" if key is not None else "BYPASS"
    return ships


@app.get("/ships/{ship_id}/unavailability", response_model=Unavailability, tags=["availability"])
def get_unavailability(ship_id: int, date: Date, session: DB):
    if session.get(Ship, ship_id) is None:
        raise HTTPException(404, "Ship not found")
    opens, closes = operating_hours(date)
    return Unavailability(
        ship_id=ship_id,
        date=date,
        opens_at=opens,
        closes_at=closes,
        unavailable=unavailable_intervals(session, ship_id, date),
    )


@app.post("/bookings", response_model=BookingOut, status_code=201, tags=["bookings"])
def book(data: BookingCreate, session: DB):
    with session.begin():
        booking = create_booking(session, data)
    return booking


@app.post("/bookings/{booking_id}/cancel", response_model=BookingOut, tags=["bookings"])
def cancel(booking_id: int, session: DB):
    with session.begin():
        booking = cancel_booking(session, booking_id)
    return booking


@app.get("/bookings", response_model=BookingPage, tags=["bookings"])
def list_bookings(
    session: DB,
    ship_id: Annotated[int | None, Query(alias="shipId", gt=0)] = None,
    date: Date | None = None,
    status: BookingStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    filters = []
    if status is not None:
        filters.append(Booking.status == status)
    if ship_id is not None:
        filters.append(Booking.ship_id == ship_id)
    if date is not None:
        opens, closes = operating_hours(date)
        filters.extend([Booking.start_time < closes, Booking.end_time > opens])
    total = session.scalar(select(func.count()).select_from(Booking).where(*filters))
    items = session.scalars(
        select(Booking)
        .where(*filters)
        .order_by(Booking.ship_id, Booking.start_time, Booking.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return BookingPage(items=items, total=total, limit=limit, offset=offset)
