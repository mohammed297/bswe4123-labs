"""Measure POST /exams elapsed time for the currently configured services."""
import time
import uuid
import httpx

payload = {
    "exam_id": "MEASURE-" + uuid.uuid4().hex[:10],
    "course_code": "MEAS101",
    "day": "2026-12-28",
    "start_hour": 9,
    "end_hour": 10,
    "students": 20,
}
start = time.perf_counter()
response = httpx.post("http://127.0.0.1:8001/exams", json=payload, timeout=60.0)
elapsed = time.perf_counter() - start
print(f"status_code={response.status_code}")
print(f"response_time_seconds={elapsed:.3f}")
print(response.text)
