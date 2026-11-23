# Lab Assignment 2: A Campus Room Booking Service

A REST service built with FastAPI and Pydantic for booking university rooms. The rule that matters: two bookings of the same room on the same day must never overlap. A booking from 10 to 12 and another from 12 to 13 do **not** overlap.

## Project Files

| File | Description |
|---|---|
| `main.py` | The FastAPI service (models, validation, endpoints, overlap check). |
| `test_bookings.py` | `httpx` client that exercises every success and error case and prints each status code. |
| `requirements.txt` | Dependencies: `fastapi`, `uvicorn`, `httpx`. |

## How to Run

```bash
python -m pip install -r requirements.txt

# Terminal 1: start the service (data is kept in memory, so restart it for a clean run)
uvicorn main:app --port 8000

# Terminal 2: run the client script
python test_bookings.py
```

Interactive API docs are available at `http://127.0.0.1:8000/docs`.

---

## 1. API Design

A booking is created with `PUT /bookings/{booking_id}`, where the **client chooses the id**. This is what makes creation safe to retry (see section 4).

**Room body:** `{"id": "B205", "building": "B", "capacity": 30}`
**Booking body:** `{"room_id": "B205", "day": "2026-12-01", "start_hour": 10, "end_hour": 12, "purpose": "Study group"}`

| # | Operation | Method | URI | Request body | Success | Error status codes |
|---|---|---|---|---|---|---|
| 1 | Create a room | POST | `/rooms` | Room | `201 Created` | `409` room id already exists; `422` invalid data (bad id format, capacity <= 0) |
| 2 | List rooms | GET | `/rooms` | none | `200 OK` | none |
| 3 | Get one room | GET | `/rooms/{room_id}` | none | `200 OK` | `404` unknown room |
| 4 | Create a booking (idempotent) | PUT | `/bookings/{booking_id}` | Booking | `201 Created` (new) or `200 OK` (exact retry) | `404` unknown room; `409` overlaps an existing booking, or the id is already used with different data; `422` invalid data (end <= start, hours outside 8-20, bad date, empty purpose, missing field) |
| 5 | Get one booking | GET | `/bookings/{booking_id}` | none | `200 OK` | `404` unknown booking |
| 6 | List bookings (optional filters `room_id`, `day`) | GET | `/bookings` | none | `200 OK` | `422` bad `day` format |
| 7 | Cancel a booking | DELETE | `/bookings/{booking_id}` | none | `204 No Content` | `404` unknown booking |

### Validation rules (Pydantic)

- Room `id` must match one letter plus three digits (for example `B205`); `capacity` must be between 1 and 1000.
- `start_hour` and `end_hour` must be integers between 8 and 20.
- A `model_validator` rejects `end_hour <= start_hour` with 422.
- `purpose` must be non-empty; `day` must be a valid ISO date.

### Overlap rule

Time ranges are treated as half-open intervals `[start, end)`. Two bookings conflict only if they are for the same room, on the same day, and:

```python
a.start_hour < b.end_hour and b.start_hour < a.end_hour
```

So 10-12 and 12-13 do not conflict (`10 < 13` is true, but `12 < 12` is false), while 10-12 and 11-13 do.

### Order of checks in `PUT /bookings/{id}`

1. Pydantic validation (automatic `422`).
2. Room exists, otherwise `404`.
3. Is this booking id already stored? If the data is identical, return the stored booking (`200`); if different, `409`.
4. Overlap check against other bookings, `409` on conflict.
5. Store and return `201`.

The order of steps 3 and 4 matters, and is explained in section 4.

---

## 2. Implementation Notes

- **Storage:** in-memory dictionaries (`rooms`, `bookings`). This is enough for the lab; a real service would use a database.
- **Concurrency:** handlers are plain `def` functions, so FastAPI runs them in a thread pool. The "check for overlap, then insert" sequence is wrapped in a `threading.Lock`. Without it, two simultaneous requests could both pass the overlap check and double-book the room, which is exactly the bug this service exists to prevent. (With multiple server processes, the lock would not be enough and the database would need a uniqueness or exclusion constraint instead.)

---

## 3. Client Script Output

`test_bookings.py` shows every success and error case and prints the status code of each call. Output from a fresh server start:

```text
--- Rooms ---
[OK ] 201 (expected 201)  POST /rooms (create B205)
[OK ] 201 (expected 201)  POST /rooms (create A101)
[OK ] 409 (expected 409)  POST /rooms duplicate id -> 409
[OK ] 422 (expected 422)  POST /rooms capacity=0 -> 422
[OK ] 422 (expected 422)  POST /rooms bad id format -> 422
[OK ] 200 (expected 200)  GET /rooms
[OK ] 200 (expected 200)  GET /rooms/B205
[OK ] 404 (expected 404)  GET /rooms/Z999 unknown -> 404
--- Bookings: success ---
[OK ] 201 (expected 201)  PUT /bookings/b1  B205 10-12 (create)
[OK ] 201 (expected 201)  PUT /bookings/b2  B205 12-13 (adjacent, allowed)
[OK ] 201 (expected 201)  PUT /bookings/b3  same hours, different room (allowed)
[OK ] 201 (expected 201)  PUT /bookings/b4  same hours, different day (allowed)
[OK ] 200 (expected 200)  GET /bookings/b1
[OK ] 200 (expected 200)  GET /bookings?room_id=B205&day=2026-12-01
[OK ] 422 (expected 422)  GET /bookings with invalid day -> 422
--- Bookings: errors ---
[OK ] 409 (expected 409)  PUT overlap 11-13 with b1/b2 -> 409
[OK ] 409 (expected 409)  PUT overlap 9-11 with b1 -> 409
[OK ] 404 (expected 404)  PUT unknown room -> 404
[OK ] 422 (expected 422)  PUT end before start (12-10) -> 422
[OK ] 422 (expected 422)  PUT end == start (10-10) -> 422
[OK ] 422 (expected 422)  PUT start before 8:00 -> 422
[OK ] 422 (expected 422)  PUT end after 20:00 -> 422
[OK ] 422 (expected 422)  PUT bad date -> 422
[OK ] 422 (expected 422)  PUT empty purpose -> 422
[OK ] 422 (expected 422)  PUT missing field -> 422
[OK ] 409 (expected 409)  PUT reuse id b1 with different data -> 409
[OK ] 404 (expected 404)  GET /bookings/nope unknown -> 404
[OK ] 404 (expected 404)  DELETE /bookings/nope unknown -> 404
--- Delete ---
[OK ] 204 (expected 204)  DELETE /bookings/b2
[OK ] 404 (expected 404)  GET /bookings/b2 after delete -> 404
[OK ] 201 (expected 201)  PUT slot 12-13 free again after delete
--- Step 4: safe retry (same request sent twice) ---
[OK ] 201 (expected 201)  PUT /bookings/retry-1 first send
[OK ] 200 (expected 200)  PUT /bookings/retry-1 second send (lost reply, retry)
[OK ] 200 (expected 200)  PUT /bookings/retry-1 third send
Bookings created by 3 identical requests: 1 (expected 1)

Mismatches: 0
```

---

## 4. Safe Retry: Idempotent Booking Creation

### The problem

Suppose the app sends "book B205, 14-16" and the server creates the booking, but the reply is lost on the network. The app cannot tell whether the booking was made, so it sends the request again. With a plain `POST /bookings`, where the server picks the id, the server cannot tell a retry from a brand-new request, so the same intent could be stored twice.

### The design

Creation uses **`PUT /bookings/{booking_id}` with an id chosen by the client** (for example a UUID generated once, when the user taps "Book", and reused for every retry of that action).

- The id identifies the *intent*, not the server's record. All retries of one intent carry the same id.
- First request: the id is new, so the booking is created and the server replies `201 Created`.
- Retry with the same id and the same body: the server finds the stored booking and returns it with `200 OK`. **Nothing new is created.** The app gets the same booking back whether it received the first reply or not.
- Same id with a different body: this is a client bug (or an id collision), not a retry, so the server answers `409` instead of silently overwriting or ignoring the data.

PUT is also defined by HTTP as idempotent: sending the same request several times has the same effect as sending it once, which is why it fits here.

### Why the retry check comes before the overlap check

A retry asks for exactly the slot that its own first attempt already holds. If the overlap check ran first, the retry would conflict with the booking it created and wrongly return `409`. So the server first asks "have I already stored this id?" and only runs the overlap check for ids it has not seen.

### Demonstration

The same request was sent three times (last block of the output above):

```text
[OK ] 201 (expected 201)  PUT /bookings/retry-1 first send
[OK ] 200 (expected 200)  PUT /bookings/retry-1 second send (lost reply, retry)
[OK ] 200 (expected 200)  PUT /bookings/retry-1 third send
Bookings created by 3 identical requests: 1 (expected 1)
```

The script counts the bookings before and after: three identical requests created exactly one booking.

### Trade-offs and limits

- The client must generate unique ids. A UUID makes collisions practically impossible; a predictable id such as `b1` risks clashing with another user's booking (the server would then return `409`, which is safe but confusing).
- The comparison is on the full request body, so a retry must be byte-for-byte equivalent in meaning. If the user edits the form between attempts, it is a new intent and needs a new id.
- Idempotency here relies on the booking record staying stored. After `DELETE`, a retry of the original request with the same id would create the booking again; a production system might keep deleted ids for a while for this reason.

---

## Conclusion

The service rejects invalid data with 422, unknown rooms and bookings with 404, and conflicting bookings with 409, while allowing back-to-back bookings. Making creation a client-id PUT, with the retry check placed before the overlap check, lets the app safely resend a booking after a lost reply without ever creating a duplicate.
