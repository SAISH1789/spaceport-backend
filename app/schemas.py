from datetime import UTC, date, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic.alias_generators import to_camel

from app.status import BookingStatus


class APIModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ShipOut(APIModel):
    id: int
    name: str


class BookingCreate(APIModel):
    ship_id: int = Field(gt=0)
    pilot_name: str = Field(min_length=1, max_length=200)
    start_time: AwareDatetime
    end_time: AwareDatetime

    @field_validator("pilot_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Pilot name cannot be blank")
        return value


class BookingOut(APIModel):
    id: int
    ship_id: int
    pilot_name: str
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    cancelled_at: datetime | None

    @field_serializer("start_time", "end_time", "cancelled_at", when_used="json")
    def utc_timestamp(self, value: datetime | None) -> str | None:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


class BookingPage(APIModel):
    items: list[BookingOut]
    total: int
    limit: int
    offset: int


class Interval(APIModel):
    start_time: datetime
    end_time: datetime


class Unavailability(APIModel):
    ship_id: int
    date: date
    timezone: str = "America/Chicago"
    opens_at: datetime
    closes_at: datetime
    unavailable: list[Interval]
