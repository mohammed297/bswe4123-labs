"""Client script: exercises every success and error case of the API.

Start the service first (fresh start, state is in memory):
    uvicorn main:app --port 8000
Then run:
    python test_bookings.py
"""
import httpx

BASE = "http://127.0.0.1:8000"
mismatches = 0


def show(label: str, response: httpx.Response, expected: int):
    global mismatches
    ok = "OK " if response.status_code == expected else "MISMATCH"
    if response.status_code != expected:
        mismatches += 1
    print(f"[{ok}] {response.status_code} (expected {expected})  {label}")


def booking(room="B205", day="2026-12-01", start=10, end=12, purpose="Study group"):
    return {"room_id": room, "day": day, "start_hour": start,
            "end_hour": end, "purpose": purpose}


with httpx.Client(base_url=BASE, timeout=5.0) as c:
    print("--- Rooms ---")
    show("POST /rooms (create B205)",
         c.post("/rooms", json={"id": "B205", "building": "B", "capacity": 30}), 201)
    show("POST /rooms (create A101)",
         c.post("/rooms", json={"id": "A101", "building": "A", "capacity": 80}), 201)
    show("POST /rooms duplicate id -> 409",
         c.post("/rooms", json={"id": "B205", "building": "B", "capacity": 30}), 409)
    show("POST /rooms capacity=0 -> 422",
         c.post("/rooms", json={"id": "C300", "building": "C", "capacity": 0}), 422)
    show("POST /rooms bad id format -> 422",
         c.post("/rooms", json={"id": "room-1", "building": "C", "capacity": 10}), 422)
    show("GET /rooms", c.get("/rooms"), 200)
    show("GET /rooms/B205", c.get("/rooms/B205"), 200)
    show("GET /rooms/Z999 unknown -> 404", c.get("/rooms/Z999"), 404)

    print("--- Bookings: success ---")
    show("PUT /bookings/b1  B205 10-12 (create)",
         c.put("/bookings/b1", json=booking()), 201)
    show("PUT /bookings/b2  B205 12-13 (adjacent, allowed)",
         c.put("/bookings/b2", json=booking(start=12, end=13, purpose="Meeting")), 201)
    show("PUT /bookings/b3  same hours, different room (allowed)",
         c.put("/bookings/b3", json=booking(room="A101")), 201)
    show("PUT /bookings/b4  same hours, different day (allowed)",
         c.put("/bookings/b4", json=booking(day="2026-12-02")), 201)
    show("GET /bookings/b1", c.get("/bookings/b1"), 200)
    show("GET /bookings?room_id=B205&day=2026-12-01",
         c.get("/bookings", params={"room_id": "B205", "day": "2026-12-01"}), 200)
    show("GET /bookings with invalid day -> 422",
         c.get("/bookings", params={"day": "not-a-date"}), 422)

    print("--- Bookings: errors ---")
    show("PUT overlap 11-13 with b1/b2 -> 409",
         c.put("/bookings/b5", json=booking(start=11, end=13)), 409)
    show("PUT overlap 9-11 with b1 -> 409",
         c.put("/bookings/b6", json=booking(start=9, end=11)), 409)
    show("PUT unknown room -> 404",
         c.put("/bookings/b7", json=booking(room="Z999")), 404)
    show("PUT end before start (12-10) -> 422",
         c.put("/bookings/b8", json=booking(start=12, end=10)), 422)
    show("PUT end == start (10-10) -> 422",
         c.put("/bookings/b9", json=booking(start=10, end=10)), 422)
    show("PUT start before 8:00 -> 422",
         c.put("/bookings/b10", json=booking(start=7, end=9)), 422)
    show("PUT end after 20:00 -> 422",
         c.put("/bookings/b11", json=booking(start=19, end=21)), 422)
    show("PUT bad date -> 422",
         c.put("/bookings/b12", json=booking(day="not-a-date")), 422)
    show("PUT empty purpose -> 422",
         c.put("/bookings/b13", json=booking(start=15, end=16, purpose="")), 422)
    show("PUT missing field -> 422",
         c.put("/bookings/b14", json={"room_id": "B205"}), 422)
    show("PUT reuse id b1 with different data -> 409",
         c.put("/bookings/b1", json=booking(start=15, end=16)), 409)
    show("GET /bookings/nope unknown -> 404", c.get("/bookings/nope"), 404)
    show("DELETE /bookings/nope unknown -> 404", c.delete("/bookings/nope"), 404)

    print("--- Delete ---")
    show("DELETE /bookings/b2", c.delete("/bookings/b2"), 204)
    show("GET /bookings/b2 after delete -> 404", c.get("/bookings/b2"), 404)
    show("PUT slot 12-13 free again after delete",
         c.put("/bookings/b15", json=booking(start=12, end=13, purpose="Reused")), 201)

    print("--- Step 4: safe retry (same request sent twice) ---")
    before = len(c.get("/bookings").json())
    req = booking(room="A101", day="2026-12-05", start=14, end=16, purpose="Extra lab")
    show("PUT /bookings/retry-1 first send", c.put("/bookings/retry-1", json=req), 201)
    show("PUT /bookings/retry-1 second send (lost reply, retry)",
         c.put("/bookings/retry-1", json=req), 200)
    show("PUT /bookings/retry-1 third send", c.put("/bookings/retry-1", json=req), 200)
    after = len(c.get("/bookings").json())
    created = after - before
    print(f"Bookings created by 3 identical requests: {created} (expected 1)")
    if created != 1:
        mismatches += 1

print(f"\nMismatches: {mismatches}")
