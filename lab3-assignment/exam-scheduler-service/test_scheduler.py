"""Integration checks for the Exam Scheduler Service.

Start Room Booking on port 8000 and Exam Scheduler on port 8001 first.
Run: python test_scheduler.py
"""
import httpx
import uuid

BASE = "http://127.0.0.1:8001"
failures = 0


def show(label: str, response: httpx.Response, expected: int):
    global failures
    ok = response.status_code == expected
    print(f"[{'OK' if ok else 'FAIL'}] {response.status_code} (expected {expected}) {label}")
    if not ok:
        failures += 1
    return response


exam = {
    "exam_id": "CS101-FINAL-" + uuid.uuid4().hex[:8],
    "course_code": "CS101",
    "day": "2026-12-15",
    "start_hour": 10,
    "end_hour": 12,
    "students": 25,
}

with httpx.Client(timeout=10.0) as client:
    show("GET /config", client.get(f"{BASE}/config"), 200)

    first = show("POST /exams first request", client.post(f"{BASE}/exams", json=exam), 201)
    if first.status_code == 201:
        room_id = first.json()["room"]["id"]
        print(f"     Selected room: {room_id} (smallest room that fits 25 students)")

    second = show("POST /exams same exam_id and same body (safe retry)",
                  client.post(f"{BASE}/exams", json=exam), 200)
    if first.status_code == 201 and second.status_code == 200:
        print(f"     Same booking ID: {first.json()['booking_id'] == second.json()['booking_id']}")

    different = {**exam, "course_code": "MATH202"}
    show("POST /exams reuse exam_id with different data", client.post(f"{BASE}/exams", json=different), 409)

    too_many = {**exam, "exam_id": "BIG-EXAM", "students": 1000}
    show("POST /exams no room large enough", client.post(f"{BASE}/exams", json=too_many), 409)

    invalid = {**exam, "exam_id": "INVALID-EXAM", "start_hour": 13, "end_hour": 12}
    show("POST /exams invalid time range", client.post(f"{BASE}/exams", json=invalid), 422)

print(f"\nFailures: {failures}")
