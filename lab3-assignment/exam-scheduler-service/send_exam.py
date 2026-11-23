"""Send one exam while manually stopping/restarting the Room Booking Service.

Run while the scheduler is up and Room Booking is temporarily stopped:
    python send_exam.py
Restart Room Booking before MAX_RETRIES is exhausted.
"""
import time
import httpx

payload = {
    "exam_id": "RESTART-DEMO-01",
    "course_code": "NET301",
    "day": "2026-12-20",
    "start_hour": 14,
    "end_hour": 16,
    "students": 20,
}
start = time.perf_counter()
try:
    response = httpx.post("http://127.0.0.1:8001/exams", json=payload, timeout=60.0)
    elapsed = time.perf_counter() - start
    print(f"POST /exams -> {response.status_code} in {elapsed:.2f}s")
    print(response.text)
except httpx.HTTPError as exc:
    print(f"Client request failed: {exc}")
