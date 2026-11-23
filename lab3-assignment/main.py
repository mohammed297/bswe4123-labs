"""Exam Scheduler Service. Run on port 8001; Room Booking runs on port 8000."""
from __future__ import annotations

import os
import time
from datetime import date
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator

ROOM_BOOKING_URL = os.getenv("ROOM_BOOKING_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "2.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "4"))
BACKOFF_BASE_SECONDS = 0.5

app = FastAPI(title="Exam Scheduler Service", version="1.0.0")


class ExamRequest(BaseModel):
    exam_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    course_code: str = Field(min_length=1, max_length=30)
    day: date
    start_hour: int = Field(ge=8, le=20)
    end_hour: int = Field(ge=8, le=20)
    students: int = Field(gt=0, le=1000)

    @model_validator(mode="after")
    def validate_hours(self):
        if self.end_hour <= self.start_hour:
            raise ValueError("end_hour must be greater than start_hour")
        return self


class ExamResult(BaseModel):
    exam_id: str
    course_code: str
    day: date
    start_hour: int
    end_hour: int
    students: int
    room: dict[str, Any]
    booking_id: str
    booking_status: int


def retryable_request(method: str, path: str, **kwargs) -> httpx.Response:
    """Retry transport failures/timeouts and 5xx only; never retry 4xx."""
    url = f"{ROOM_BOOKING_URL}{path}"
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = httpx.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if response.status_code < 500:
                return response
            reason = f"HTTP {response.status_code}"
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            reason = f"{type(exc).__name__}: {exc}"

        if attempt >= MAX_RETRIES:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Room Booking Service unavailable after {attempt + 1} attempts ({reason})",
            )

        wait_seconds = BACKOFF_BASE_SECONDS * (2 ** attempt)
        print(
            f"[retry] {method} {path}: attempt {attempt + 1}/{MAX_RETRIES + 1} failed ({reason}); "
            f"retrying in {wait_seconds:.1f}s",
            flush=True,
        )
        time.sleep(wait_seconds)

    raise HTTPException(503, "Room Booking Service unavailable")


def checked_json(response: httpx.Response, expected_statuses: set[int] | None = None):
    if response.status_code >= 500:
        raise HTTPException(503, "Room Booking Service returned a server error")
    if expected_statuses is not None and response.status_code not in expected_statuses:
        if response.status_code == 404:
            raise HTTPException(503, "Room Booking Service returned an unexpected 404")
        if response.status_code == 409:
            raise HTTPException(409, "Room Booking Service reported a booking conflict")
        raise HTTPException(503, f"Unexpected Room Booking Service status {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise HTTPException(503, "Room Booking Service returned invalid JSON")


def booking_payload(exam: ExamRequest, room_id: str) -> dict[str, Any]:
    return {
        "room_id": room_id,
        "day": exam.day.isoformat(),
        "start_hour": exam.start_hour,
        "end_hour": exam.end_hour,
        "purpose": f"Exam {exam.course_code} - {exam.students} students",
    }



def find_existing_exam_booking(exam: ExamRequest, booking_id: str):
    """Return the existing booking and room, or None when this exam is not booked."""
    existing_response = retryable_request("GET", f"/bookings/{booking_id}")
    if existing_response.status_code == 404:
        return None
    existing = checked_json(existing_response, {200})
    expected = booking_payload(exam, existing["room_id"])
    comparable = {key: existing[key] for key in expected}
    expected_purpose = f"Exam {exam.course_code} - {exam.students} students"
    if comparable != expected or existing["purpose"] != expected_purpose:
        raise HTTPException(409, "This exam_id has already been used with different exam details")
    room_response = retryable_request("GET", f"/rooms/{existing['room_id']}")
    room = checked_json(room_response, {200})
    return existing, room

def make_result(
    exam: ExamRequest, booking: dict[str, Any], booking_status: int,
    room: dict[str, Any],
) -> ExamResult:
    return ExamResult(
        exam_id=exam.exam_id,
        course_code=exam.course_code,
        day=exam.day,
        start_hour=exam.start_hour,
        end_hour=exam.end_hour,
        students=exam.students,
        room=room,
        booking_id=booking["id"],
        booking_status=booking_status,
    )


@app.get("/config")
def get_config():
    return {
        "room_booking_url": ROOM_BOOKING_URL,
        "timeout_seconds": REQUEST_TIMEOUT,
        "max_retries": MAX_RETRIES,
        "backoff_base_seconds": BACKOFF_BASE_SECONDS,
        "retry_delays_seconds": [BACKOFF_BASE_SECONDS * (2 ** i) for i in range(MAX_RETRIES)],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/exams", response_model=ExamResult, status_code=status.HTTP_201_CREATED)
def schedule_exam(exam: ExamRequest, response: Response):
    booking_id = f"exam-{exam.exam_id}"
    expected_purpose = f"Exam {exam.course_code} - {exam.students} students"

    # First check the deterministic booking ID. This handles a retry after the
    # room service committed the booking but its HTTP reply was lost.
    existing_record = find_existing_exam_booking(exam, booking_id)
    if existing_record is not None:
        existing, room = existing_record
        response.status_code = status.HTTP_200_OK
        return make_result(exam, existing, 200, room)

    rooms_response = retryable_request("GET", "/rooms")
    rooms = checked_json(rooms_response, {200})
    bookings_response = retryable_request("GET", "/bookings", params={"day": exam.day.isoformat()})
    bookings = checked_json(bookings_response, {200})

    suitable_rooms = sorted(
        (room for room in rooms if room["capacity"] >= exam.students),
        key=lambda room: (room["capacity"], room["id"]),
    )
    if not suitable_rooms:
        raise HTTPException(409, "No room is large enough for this exam")

    for room in suitable_rooms:
        occupied = any(
            booking["room_id"] == room["id"]
            and exam.start_hour < booking["end_hour"]
            and booking["start_hour"] < exam.end_hour
            for booking in bookings
        )
        if occupied:
            continue

        response = retryable_request(
            "PUT", f"/bookings/{booking_id}", json=booking_payload(exam, room["id"])
        )
        if response.status_code == 201:
            booking = checked_json(response, {201})
            return make_result(exam, booking, 201, room)
        if response.status_code == 200:
            booking = checked_json(response, {200})
            return make_result(exam, booking, 200, room)
        if response.status_code == 409:
            # Another scheduler may have created this exact exam between our
            # initial check and PUT. Re-read its deterministic ID before trying
            # another room, so concurrent duplicate requests return one booking.
            existing_record = find_existing_exam_booking(exam, booking_id)
            if existing_record is not None:
                existing, existing_room = existing_record
                return make_result(exam, existing, 200, existing_room)
            continue
        if response.status_code == 404:
            # The room may have been removed between listing and booking.
            continue
        checked_json(response, {201, 200})

    raise HTTPException(409, "No free room large enough for this exam")
