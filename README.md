# Lab Assignment 3: The Exam Scheduler Service

Two FastAPI services work together to schedule university exams. The Exam Scheduler asks the Room Booking Service for rooms and existing bookings, selects the smallest room with enough capacity that is free for the requested time, and creates the booking.

## Project structure

```text
lab3-assignment/
├── room-booking-service/
│   ├── main.py
│   ├── requirements.txt
│   ├── test_bookings.py
│   └── .gitignore
└── exam-scheduler-service/
    ├── main.py
    ├── requirements.txt
    ├── .env.example
    ├── test_scheduler.py
    ├── send_exam.py
    ├── measure_response.py
    └── .gitignore
```

The Room Booking Service is the Lab 2 service adapted for this assignment. Its API remains compatible with Lab 2, and it uses SQLite so rooms and bookings survive a service restart. On the first start, it creates four sample rooms if the database has no rooms:

| Room | Building | Capacity |
|---|---|---:|
| B205 | Building B | 30 |
| A101 | Building A | 80 |
| C310 | Building C | 120 |
| D410 | Building D | 200 |

The SQLite database is created automatically as `room_booking.db` inside `room-booking-service/`. It is runtime data and is excluded from Git.

## Requirements

- Python 3.10 or newer
- FastAPI, Uvicorn, Pydantic 2, and HTTPX (installed from the two `requirements.txt` files)

## Run both services (Windows PowerShell)

Open two terminals in VS Code. Keep both services running while testing.

### Terminal 1 — Room Booking Service (port 8000)

```powershell
cd lab3-assignment/room-booking-service
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ROOM_SERVICE_DELAY_SECONDS = "0"
uvicorn main:app --host 127.0.0.1 --port 8000
```

### Terminal 2 — Exam Scheduler Service (port 8001)

```powershell
cd lab3-assignment/exam-scheduler-service
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:ROOM_BOOKING_URL = "http://127.0.0.1:8000"
$env:REQUEST_TIMEOUT = "2.0"
$env:MAX_RETRIES = "4"
uvicorn main:app --host 127.0.0.1 --port 8001
```

API documentation:

- Room Booking Service: <http://127.0.0.1:8000/docs>
- Exam Scheduler Service: <http://127.0.0.1:8001/docs>

## 1. Exam Scheduler API

### `POST /exams`

Example request:

```json
{
  "exam_id": "CS101-FINAL-01",
  "course_code": "CS101",
  "day": "2026-12-15",
  "start_hour": 10,
  "end_hour": 12,
  "students": 25
}
```

Example successful response (first request):

```json
{
  "exam_id": "CS101-FINAL-01",
  "course_code": "CS101",
  "day": "2026-12-15",
  "start_hour": 10,
  "end_hour": 12,
  "students": 25,
  "room": {"id": "B205", "building": "Building B", "capacity": 30},
  "booking_id": "exam-CS101-FINAL-01",
  "booking_status": 201
}
```

| Method | URI | Success status | Error status | Description |
|---|---|---:|---|---|
| POST | `/exams` | `201 Created` for a new exam; `200 OK` for an identical retry | `409 Conflict` no suitable free room or exam ID reused with different details; `422` invalid exam data; `503 Service Unavailable` Room Booking Service remains unavailable | Schedule an exam and return its selected room and booking ID |
| GET | `/config` | `200 OK` | — | Show the Room Booking URL, timeout, retry count, and backoff values currently in use |
| GET | `/health` | `200 OK` | — | Scheduler health check |

The Room Booking Service endpoints used by the scheduler are:

| Method | URI | Purpose |
|---|---|---|
| GET | `/bookings/{booking_id}` | Check whether this exam was already booked |
| GET | `/rooms` | Retrieve rooms and capacities |
| GET | `/bookings?day=YYYY-MM-DD` | Retrieve bookings for the exam day |
| GET | `/rooms/{room_id}` | Retrieve full details for an already-booked room |
| PUT | `/bookings/{booking_id}` | Create the booking idempotently |

## 2. Environment configuration

The Exam Scheduler reads all connection and retry settings from environment variables when it starts:

| Environment variable | Default | Meaning |
|---|---|---|
| `ROOM_BOOKING_URL` | `http://127.0.0.1:8000` | Base address of the Room Booking Service |
| `REQUEST_TIMEOUT` | `2.0` | HTTP timeout in seconds for each request attempt |
| `MAX_RETRIES` | `4` | Number of retries after the first attempt; total attempts are `MAX_RETRIES + 1` |

The backoff starts at 0.5 seconds and doubles after each failed attempt. For four retries, the waits are 0.5, 1, 2, and 4 seconds. `GET /config` returns the actual values in use, including the retry delays.

The Room Booking Service has one additional environment variable:

| Environment variable | Default | Meaning |
|---|---:|---|
| `ROOM_SERVICE_DELAY_SECONDS` | `0` | Artificial delay, in seconds, added to each incoming request. Used for the performance experiment. |
| `ROOM_DB_PATH` | `room-booking-service/room_booking.db` | Optional SQLite database path; useful for isolated test runs. |

## 3. Retry behavior and safe booking

The scheduler retries a Room Booking Service request only when it fails due to:

- a connection error;
- a timeout;
- an HTTP 5xx server response.

It does **not** retry 404 or 409 responses. A 404 from `GET /bookings/{booking_id}` is the normal result when an exam has not been booked yet, so the scheduler proceeds to room selection. A 409 from booking creation means the candidate room became unavailable or conflicts with another booking, so the scheduler tries the next suitable room instead of retrying the same conflicting request.

### Why the booking is safe to retry

The scheduler derives a deterministic booking ID from the exam ID: `exam-{exam_id}`. It first asks the Room Booking Service whether that booking ID already exists. If it exists with the same exam details, the scheduler returns the existing booking and room with `200 OK`. If the ID exists with different details, it returns `409 Conflict`.

For a new booking, the scheduler calls `PUT /bookings/{booking_id}`. The Room Booking Service checks the ID before checking time overlap:

- First request: stores the booking and returns `201 Created`.
- Same ID and same booking data: returns the existing booking with `200 OK`; it does not insert another row.
- Same ID but different booking data: returns `409 Conflict`.

This protects against the important lost-reply case: the Room Booking Service might commit the booking, then the network reply might time out. When the office repeats `POST /exams` with the same `exam_id`, the scheduler finds and returns the original booking rather than selecting another room. SQLite persistence also means the booking remains present if the Room Booking Service process is restarted.

### Automated service checks

With the Room Booking Service running, open a third terminal, activate its environment, and run the Lab 2 regression test:

```powershell
cd lab3-assignment/room-booking-service
.\.venv\Scripts\Activate.ps1
python test_bookings.py
```

The test checks room creation/listing, booking creation, adjacent bookings, overlap rejection, validation errors, deletion, and idempotent PUT retries. It should finish with `Mismatches: 0`.

### Automated scheduler checks

With both services running, open a third terminal, activate the scheduler environment, and run:

```powershell
cd lab3-assignment/exam-scheduler-service
.\.venv\Scripts\Activate.ps1
python test_scheduler.py
```

Verified output (the generated exam ID is unique on each run):

```text
[OK] 200 (expected 200) GET /config
[OK] 201 (expected 201) POST /exams first request
     Selected room: B205 (smallest room that fits 25 students)
[OK] 200 (expected 200) POST /exams same exam_id and same body (safe retry)
     Same booking ID: True
[OK] 409 (expected 409) POST /exams reuse exam_id with different data
[OK] 409 (expected 409) POST /exams no room large enough
[OK] 422 (expected 422) POST /exams invalid time range

Failures: 0
```

### Stop/restart demonstration

This test demonstrates the scheduler retrying while the Room Booking Service is stopped, then succeeding after it is restarted.

1. Start the Exam Scheduler Service with `MAX_RETRIES=5` and `REQUEST_TIMEOUT=1` in Terminal 2.
2. Stop the Room Booking Service in Terminal 1 with `Ctrl+C`.
3. In a third terminal, run `python send_exam.py`. It sends one exam and waits for the scheduler response.
4. While it is retrying, restart the Room Booking Service in Terminal 1 with the same database path and `ROOM_SERVICE_DELAY_SECONDS=0`.

For the recorded run, the Room Booking Service was restarted while the scheduler was waiting between retries. Scheduler log:

```text
[retry] GET /bookings/exam-RESTART-DEMO-01: attempt 1/6 failed (ConnectError: [Errno 111] Connection refused); retrying in 0.5s
[retry] GET /bookings/exam-RESTART-DEMO-01: attempt 2/6 failed (ConnectError: [Errno 111] Connection refused); retrying in 1.0s
[retry] GET /bookings/exam-RESTART-DEMO-01: attempt 3/6 failed (ConnectError: [Errno 111] Connection refused); retrying in 2.0s
INFO: 127.0.0.1 - "POST /exams HTTP/1.1" 201 Created
```

Client output:

```text
POST /exams -> 201 in 3.71s
{"exam_id":"RESTART-DEMO-01","course_code":"NET301","day":"2026-12-20","start_hour":14,"end_hour":16,"students":20,"room":{"id":"B205","building":"Building B","capacity":30},"booking_id":"exam-RESTART-DEMO-01","booking_status":201}
```

The first three connection attempts failed while the Room Booking Service was down. After it restarted, the next attempt succeeded and the exam was booked.

## 4. Delay and timeout experiment

`ROOM_SERVICE_DELAY_SECONDS` adds a delay to every Room Booking Service request. `REQUEST_TIMEOUT` controls how long the scheduler waits for each individual attempt. The `measure_response.py` client measures the complete `POST /exams` duration, including the scheduler's internal calls and any backoff waits.

To run one combination, stop both services, set the environment variables below, and start them again. Run `python measure_response.py` from the scheduler folder. Repeat with the next combination. The three measurements below were taken with the same database during one experiment; therefore the second exam used the next available room after the first exam occupied B205.

| Run | Room service delay | Scheduler timeout | Max retries | POST `/exams` status | Response time |
|---|---:|---:|---:|---:|---:|
| A | 0.00 s | 2.00 s | 2 | `201 Created` | 0.211 s |
| B | 0.25 s | 1.00 s | 2 | `201 Created` | 1.208 s |
| C | 0.75 s | 0.30 s | 1 | `503 Service Unavailable` | 1.256 s |

### Explanation of the trade-off

- **Run A:** With no artificial delay and a generous timeout, the scheduler completes all Room Booking calls quickly and successfully.
- **Run B:** The 0.25-second delay is below the 1-second timeout, so each individual call succeeds. However, the scheduler makes several calls (check the exam booking, list rooms, list that day's bookings, and create the booking), so the delays accumulate and the complete request takes longer.
- **Run C:** Each 0.75-second service delay is longer than the 0.30-second timeout. The scheduler times out, retries once, and then returns `503` when the service still cannot answer within the configured timeout. The retry improves resilience to temporary failures, but it cannot make a consistently slow service meet a timeout that is too short.

The trade-off is between responsiveness and tolerance of slow dependencies. A short timeout gives the client a quick failure but can reject a service that would eventually respond. A longer timeout and more retries tolerate temporary slowness/outages but increase the maximum time the office waits.

## Files for the submission

- `room-booking-service/`: the Room Booking Service version used by the scheduler, plus the Lab 2 HTTPX regression test (`test_bookings.py`).
- `exam-scheduler-service/`: the Exam Scheduler Service, integration test, restart demonstration client, and response-time measurement client.
- `README.md`: run commands, API description, configuration, retry demonstration log, experiment table, and explanations.

Submit the GitHub folder link:

`https://github.com/<your-username>/bswe4123-labs/tree/main/lab3-assignment`
