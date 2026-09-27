from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, Ship
from app.schemas import BookingCreate, Interval
from app.status import BookingStatus

CENTRAL = ZoneInfo("America/Chicago")
BUFFER = timedelta(minutes=30)


def operating_hours(day: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(day, time(6), CENTRAL),
        datetime.combine(day, time(22), CENTRAL),
    )


def validate_times(start: datetime, end: datetime) -> None:
    if start >= end:
        raise HTTPException(422, "End time must be after start time")
    local_start, local_end = start.astimezone(CENTRAL), end.astimezone(CENTRAL)
    opens, closes = operating_hours(local_start.date())
    if local_start < opens or local_end > closes or local_start.date() != local_end.date():
        raise HTTPException(422, "Booking must fit within 06:00–22:00 America/Chicago")


def create_booking(session: Session, data: BookingCreate) -> Booking:
    start = data.start_time.astimezone(UTC)
    end = data.end_time.astimezone(UTC)
    validate_times(start, end)
    # Every writer locks the ship BEFORE checking bookings. Under READ COMMITTED,
    # a waiting request's next query sees the preceding request's committed booking.
    ship = session.scalar(select(Ship).where(Ship.id == data.ship_id).with_for_update())
    if ship is None:
        raise HTTPException(404, "Ship not found")
    conflict = session.scalar(
        select(Booking.id)
        .where(
            Booking.ship_id == data.ship_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_time < end + BUFFER,
            Booking.end_time > start - BUFFER,
        )
        .limit(1)
    )
    if conflict is not None:
        raise HTTPException(409, "Ship is unavailable; allow 30 minutes between bookings")
    booking = Booking(
        ship_id=data.ship_id, pilot_name=data.pilot_name, start_time=start, end_time=end
    )
    session.add(booking)
    session.flush()
    return booking


def unavailable_intervals(session: Session, ship_id: int, day: date) -> list[Interval]:
    opens, closes = operating_hours(day)
    bookings = session.scalars(
        select(Booking)
        .where(
            Booking.ship_id == ship_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_time < closes + BUFFER,
            Booking.end_time > opens - BUFFER,
        )
        .order_by(Booking.start_time)
    )
    merged: list[Interval] = []
    for booking in bookings:
        start = max(opens, (booking.start_time - BUFFER).astimezone(CENTRAL))
        end = min(closes, (booking.end_time + BUFFER).astimezone(CENTRAL))
        if merged and start <= merged[-1].end_time:
            merged[-1].end_time = max(merged[-1].end_time, end)
        else:
            merged.append(Interval(start_time=start, end_time=end))
    return merged


def utc_now() -> datetime:
    return datetime.now(UTC)


def cancel_booking(session: Session, booking_id: int) -> Booking:
    # Resolve the ship without caching a Booking object before taking the lock.
    ship_id = session.scalar(select(Booking.ship_id).where(Booking.id == booking_id))
    if ship_id is None:
        raise HTTPException(404, "Booking not found")
    # Use the same lock order as creation/seed import. Read status AFTER waiting,
    # so simultaneous cancellations preserve the first cancellation timestamp.
    session.scalar(select(Ship).where(Ship.id == ship_id).with_for_update())
    booking = session.scalar(
        select(Booking).where(Booking.id == booking_id).execution_options(populate_existing=True)
    )
    if booking is None:
        raise HTTPException(404, "Booking not found")
    if booking.status == BookingStatus.CANCELLED:
        return booking
    now = utc_now()
    if booking.start_time <= now:
        raise HTTPException(409, "Bookings can only be cancelled before departure")
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    session.flush()
    return booking
