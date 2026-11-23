"""Client script: exercises every success and error case of the API.

Start the service first (SQLite keeps data across service restarts):
    uvicorn main:app --port 8000
Then run:
    python test_bookings.py
"""
import httpx
import uuid
from datetime import date, timedelta

BASE = "http://127.0.0.1:8000"
mismatches = 0


def show(label: str, response: httpx.Response, expected: int):
    global mismatches
    ok = "OK " if response.status_code == expected else "MISMATCH"
    if response.status_code != expected:
        mismatches += 1
    print(f"[{ok}] {response.status_code} (expected {expected})  {label}")


RUN_ID = uuid.uuid4().hex[:8]
RUN_DAY = (date(2027, 1, 1) + timedelta(days=uuid.uuid4().int % 300)).isoformat()
NEXT_DAY = (date.fromisoformat(RUN_DAY) + timedelta(days=1)).isoformat()
RETRY_DAY = (date.fromisoformat(RUN_DAY) + timedelta(days=4)).isoformat()


def bid(name):
    return f"{RUN_ID}-{name}"


def booking(room="B205", day=None, start=10, end=12, purpose="Study group"):
    return {"room_id": room, "day": day or RUN_DAY, "start_hour": start,
            "end_hour": end, "purpose": purpose}


with httpx.Client(base_url=BASE, timeout=5.0) as c:
    print("--- Rooms ---")
    # B205 and A101 are seeded by the service. Use fresh IDs for create tests
    # so this client remains repeatable even when the SQLite DB is persistent.
    room1 = "X" + str(100 + uuid.uuid4().int % 900)
    room2 = "Y" + str(100 + uuid.uuid4().int % 900)
    show("POST /rooms (create a new room)",
         c.post("/rooms", json={"id": room1, "building": "Test X", "capacity": 30}), 201)
    show("POST /rooms (create another room)",
         c.post("/rooms", json={"id": room2, "building": "Test Y", "capacity": 80}), 201)
    show("POST /rooms duplicate id -> 409",
         c.post("/rooms", json={"id": room1, "building": "Test X", "capacity": 30}), 409)
    show("POST /rooms capacity=0 -> 422",
         c.post("/rooms", json={"id": "C300", "building": "C", "capacity": 0}), 422)
    show("POST /rooms bad id format -> 422",
         c.post("/rooms", json={"id": "room-1", "building": "C", "capacity": 10}), 422)
    show("GET /rooms", c.get("/rooms"), 200)
    show("GET /rooms/B205", c.get("/rooms/B205"), 200)
    show("GET /rooms/Z999 unknown -> 404", c.get("/rooms/Z999"), 404)

    print("--- Bookings: success ---")
    show("PUT /bookings/b1  B205 10-12 (create)",
         c.put(f"/bookings/{bid('b1')}", json=booking()), 201)
    show("PUT /bookings/b2  B205 12-13 (adjacent, allowed)",
         c.put(f"/bookings/{bid('b2')}", json=booking(start=12, end=13, purpose="Meeting")), 201)
    show("PUT /bookings/b3  same hours, different room (allowed)",
         c.put(f"/bookings/{bid('b3')}", json=booking(room="A101")), 201)
    show("PUT /bookings/b4  same hours, different day (allowed)",
         c.put(f"/bookings/{bid('b4')}", json=booking(day=NEXT_DAY)), 201)
    show("GET /bookings/b1", c.get(f"/bookings/{bid('b1')}"), 200)
    show("GET /bookings?room_id=B205&day=<test day>",
         c.get("/bookings", params={"room_id": "B205", "day": RUN_DAY}), 200)

    print("--- Bookings: errors ---")
    show("PUT overlap 11-13 with b1/b2 -> 409",
         c.put(f"/bookings/{bid('b5')}", json=booking(start=11, end=13)), 409)
    show("PUT overlap 9-11 with b1 -> 409",
         c.put(f"/bookings/{bid('b6')}", json=booking(start=9, end=11)), 409)
    show("PUT unknown room -> 404",
         c.put(f"/bookings/{bid('b7')}", json=booking(room="Z999")), 404)
    show("PUT end before start (12-10) -> 422",
         c.put(f"/bookings/{bid('b8')}", json=booking(start=12, end=10)), 422)
    show("PUT end == start (10-10) -> 422",
         c.put(f"/bookings/{bid('b9')}", json=booking(start=10, end=10)), 422)
    show("PUT start before 8:00 -> 422",
         c.put(f"/bookings/{bid('b10')}", json=booking(start=7, end=9)), 422)
    show("PUT end after 20:00 -> 422",
         c.put(f"/bookings/{bid('b11')}", json=booking(start=19, end=21)), 422)
    show("PUT bad date -> 422",
         c.put(f"/bookings/{bid('b12')}", json=booking(day="not-a-date")), 422)
    show("PUT empty purpose -> 422",
         c.put(f"/bookings/{bid('b13')}", json=booking(start=15, end=16, purpose="")), 422)
    show("PUT missing field -> 422",
         c.put(f"/bookings/{bid('b14')}", json={"room_id": "B205"}), 422)
    show("PUT reuse id b1 with different data -> 409",
         c.put(f"/bookings/{bid('b1')}", json=booking(start=15, end=16)), 409)
    show("GET /bookings/nope unknown -> 404", c.get("/bookings/nope"), 404)
    show("DELETE /bookings/nope unknown -> 404", c.delete("/bookings/nope"), 404)

    print("--- Delete ---")
    show("DELETE /bookings/b2", c.delete(f"/bookings/{bid('b2')}"), 204)
    show("GET /bookings/b2 after delete -> 404", c.get(f"/bookings/{bid('b2')}"), 404)
    show("PUT slot 12-13 free again after delete",
         c.put(f"/bookings/{bid('b15')}", json=booking(start=12, end=13, purpose="Reused")), 201)

    print("--- Step 4: safe retry (same request sent twice) ---")
    before = len(c.get("/bookings").json())
    req = booking(room="A101", day=RETRY_DAY, start=14, end=16, purpose="Extra lab")
    show("PUT /bookings/retry-1 first send", c.put(f"/bookings/{bid('retry-1')}", json=req), 201)
    show("PUT /bookings/retry-1 second send (lost reply, retry)",
         c.put(f"/bookings/{bid('retry-1')}", json=req), 200)
    show("PUT /bookings/retry-1 third send", c.put(f"/bookings/{bid('retry-1')}", json=req), 200)
    after = len(c.get("/bookings").json())
    created = after - before
    print(f"Bookings created by 3 identical requests: {created} (expected 1)")
    if created != 1:
        mismatches += 1

print(f"\nMismatches: {mismatches}")
