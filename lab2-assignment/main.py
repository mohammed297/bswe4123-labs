"""Campus Room Booking Service (FastAPI).

Run:  uvicorn main:app --port 8000
Docs: http://127.0.0.1:8000/docs
"""
import threading
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator

app = FastAPI(title="Campus Room Booking Service")

OPEN_HOUR = 8
CLOSE_HOUR = 20


# ---------------------------------------------------------------- models
class RoomIn(BaseModel):
    id: str = Field(pattern=r"^[A-Z]\d{3}$", examples=["B205"])
    building: str = Field(min_length=1, max_length=50)
    capacity: int = Field(gt=0, le=1000)


class BookingIn(BaseModel):
    room_id: str
    day: date
    start_hour: int = Field(ge=OPEN_HOUR, le=CLOSE_HOUR)
    end_hour: int = Field(ge=OPEN_HOUR, le=CLOSE_HOUR)
    purpose: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be greater than start_hour")
        return self


class Booking(BookingIn):
    id: str


# ---------------------------------------------------------------- storage
rooms: dict[str, RoomIn] = {}
bookings: dict[str, Booking] = {}

# Handlers are plain `def`, so FastAPI runs them in a thread pool. The lock
# makes "check for overlap, then insert" one atomic step; without it two
# simultaneous requests could both pass the check and double-book the room.
lock = threading.Lock()


def overlaps(a: BookingIn, b: BookingIn) -> bool:
    """Same room, same day, and time ranges intersect.

    Ranges are half-open [start, end), so 10-12 and 12-13 do NOT overlap.
    """
    return (
        a.room_id == b.room_id
        and a.day == b.day
        and a.start_hour < b.end_hour
        and b.start_hour < a.end_hour
    )


# ---------------------------------------------------------------- rooms
@app.post("/rooms", response_model=RoomIn, status_code=status.HTTP_201_CREATED)
def create_room(room: RoomIn):
    with lock:
        if room.id in rooms:
            raise HTTPException(409, f"Room {room.id} already exists")
        rooms[room.id] = room
    return room


@app.get("/rooms", response_model=list[RoomIn])
def list_rooms():
    return list(rooms.values())


@app.get("/rooms/{room_id}", response_model=RoomIn)
def get_room(room_id: str):
    if room_id not in rooms:
        raise HTTPException(404, f"Room {room_id} not found")
    return rooms[room_id]


# ---------------------------------------------------------------- bookings
@app.put("/bookings/{booking_id}", response_model=Booking)
def put_booking(booking_id: str, body: BookingIn, response: Response):
    """Create a booking with a client-chosen id (idempotent create).

    201 first time, 200 if the exact same request is repeated,
    409 if the id is reused with different data or the slot overlaps.
    """
    with lock:
        if body.room_id not in rooms:
            raise HTTPException(404, f"Room {body.room_id} not found")

        existing = bookings.get(booking_id)
        if existing is not None:
            # Retry check comes BEFORE the overlap check, otherwise a retry
            # would collide with the booking it created the first time.
            if BookingIn(**existing.model_dump(exclude={"id"})) == body:
                response.status_code = status.HTTP_200_OK
                return existing
            raise HTTPException(
                409, f"Booking id {booking_id} already used with different data"
            )

        for other in bookings.values():
            if overlaps(body, other):
                raise HTTPException(
                    409,
                    f"Overlaps booking {other.id} "
                    f"({other.start_hour}:00-{other.end_hour}:00)",
                )

        booking = Booking(id=booking_id, **body.model_dump())
        bookings[booking_id] = booking
        response.status_code = status.HTTP_201_CREATED
        return booking


@app.get("/bookings/{booking_id}", response_model=Booking)
def get_booking(booking_id: str):
    if booking_id not in bookings:
        raise HTTPException(404, f"Booking {booking_id} not found")
    return bookings[booking_id]


@app.get("/bookings", response_model=list[Booking])
def list_bookings(room_id: Optional[str] = None, day: Optional[date] = None):
    result = list(bookings.values())
    if room_id is not None:
        result = [b for b in result if b.room_id == room_id]
    if day is not None:
        result = [b for b in result if b.day == day]
    return result


@app.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: str):
    with lock:
        if booking_id not in bookings:
            raise HTTPException(404, f"Booking {booking_id} not found")
        del bookings[booking_id]
