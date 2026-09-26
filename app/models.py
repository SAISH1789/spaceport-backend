from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Ship(Base):
    __tablename__ = "ships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="positive_duration"),
        CheckConstraint("length(trim(pilot_name)) > 0", name="nonempty_pilot"),
        Index("ix_bookings_ship_start", "ship_id", "start_time"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ship_id: Mapped[int] = mapped_column(ForeignKey("ships.id"), nullable=False)
    pilot_name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
