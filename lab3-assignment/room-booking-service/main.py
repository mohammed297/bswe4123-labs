"""Room Booking Service used by Lab Assignment 3.

Run from this directory:
    python -m pip install -r requirements.txt
    uvicorn main:app --host 127.0.0.1 --port 8000

The service keeps its data in SQLite so bookings survive a service restart.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("ROOM_DB_PATH", str(APP_DIR / "room_booking.db")))
OPEN_HOUR = 8
CLOSE_HOUR = 20

app = FastAPI(title="Campus Room Booking Service", version="1.0.0")


class ConfigurableDelayMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        delay = max(0.0, float(os.getenv("ROOM_SERVICE_DELAY_SECONDS", "0")))
        if delay:
            await asyncio.sleep(delay)
        return await call_next(request)


app.add_middleware(ConfigurableDelayMiddleware)


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
    def validate_time_range(self):
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be greater than start_hour")
        return self


class Booking(BookingIn):
    id: str


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS rooms (
            id TEXT PRIMARY KEY, building TEXT NOT NULL, capacity INTEGER NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY, room_id TEXT NOT NULL, day TEXT NOT NULL,
            start_hour INTEGER NOT NULL, end_hour INTEGER NOT NULL,
            purpose TEXT NOT NULL, FOREIGN KEY(room_id) REFERENCES rooms(id)
        )""")
        count = db.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        if count == 0:
            db.executemany(
                "INSERT INTO rooms(id, building, capacity) VALUES (?, ?, ?)",
                [
                    ("B205", "Building B", 30),
                    ("A101", "Building A", 80),
                    ("C310", "Building C", 120),
                    ("D410", "Building D", 200),
                ],
            )


@app.on_event("startup")
def on_startup():
    initialize_database()


def row_to_booking(row: sqlite3.Row) -> Booking:
    return Booking(
        id=row["id"], room_id=row["room_id"], day=date.fromisoformat(row["day"]),
        start_hour=row["start_hour"], end_hour=row["end_hour"], purpose=row["purpose"],
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/rooms", response_model=RoomIn, status_code=status.HTTP_201_CREATED)
def create_room(room: RoomIn):
    with connect() as db:
        try:
            db.execute(
                "INSERT INTO rooms(id, building, capacity) VALUES (?, ?, ?)",
                (room.id, room.building, room.capacity),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"Room {room.id} already exists")
    return room


@app.get("/rooms", response_model=list[RoomIn])
def list_rooms():
    with connect() as db:
        rows = db.execute("SELECT id, building, capacity FROM rooms ORDER BY capacity, id").fetchall()
    return [RoomIn(**dict(row)) for row in rows]


@app.get("/rooms/{room_id}", response_model=RoomIn)
def get_room(room_id: str):
    with connect() as db:
        row = db.execute("SELECT id, building, capacity FROM rooms WHERE id=?", (room_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Room {room_id} not found")
    return RoomIn(**dict(row))


@app.put("/bookings/{booking_id}", response_model=Booking)
def put_booking(booking_id: str, body: BookingIn, response: Response):
    """Client-selected ID makes identical retries return the existing booking."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        room = db.execute("SELECT id FROM rooms WHERE id=?", (body.room_id,)).fetchone()
        if room is None:
            raise HTTPException(404, f"Room {body.room_id} not found")

        existing = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if existing is not None:
            stored = row_to_booking(existing)
            if BookingIn(**stored.model_dump(exclude={"id"})) == body:
                response.status_code = status.HTTP_200_OK
                return stored
            raise HTTPException(409, f"Booking id {booking_id} already used with different data")

        conflict = db.execute(
            """SELECT id FROM bookings
               WHERE room_id=? AND day=? AND start_hour < ? AND ? < end_hour
               LIMIT 1""",
            (body.room_id, body.day.isoformat(), body.end_hour, body.start_hour),
        ).fetchone()
        if conflict is not None:
            raise HTTPException(409, f"Booking overlaps existing booking {conflict['id']}")

        db.execute(
            """INSERT INTO bookings(id, room_id, day, start_hour, end_hour, purpose)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (booking_id, body.room_id, body.day.isoformat(), body.start_hour,
             body.end_hour, body.purpose),
        )
        response.status_code = status.HTTP_201_CREATED
        return Booking(id=booking_id, **body.model_dump())


@app.get("/bookings/{booking_id}", response_model=Booking)
def get_booking(booking_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Booking {booking_id} not found")
    return row_to_booking(row)


@app.get("/bookings", response_model=list[Booking])
def list_bookings(room_id: Optional[str] = None, day: Optional[date] = None):
    query = "SELECT * FROM bookings"
    clauses, values = [], []
    if room_id is not None:
        clauses.append("room_id=?")
        values.append(room_id)
    if day is not None:
        clauses.append("day=?")
        values.append(day.isoformat())
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY start_hour, id"
    with connect() as db:
        rows = db.execute(query, values).fetchall()
    return [row_to_booking(row) for row in rows]


@app.delete("/bookings/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: str):
    with connect() as db:
        cursor = db.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        if cursor.rowcount == 0:
            raise HTTPException(404, f"Booking {booking_id} not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
