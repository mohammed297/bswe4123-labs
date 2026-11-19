#!/usr/bin/env python3
"""Poll three services and report UP, SLOW, SUSPECT, or DOWN."""
import time
from datetime import datetime

import httpx

SERVICES = {
    "8001": "http://127.0.0.1:8001/health",
    "8002": "http://127.0.0.1:8002/health",
    "8003": "http://127.0.0.1:8003/health",
}

CHECK_INTERVAL_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 1.0
SLOW_THRESHOLD_SECONDS = 0.5
FAILURES_BEFORE_DOWN = 3

# Consecutive failure count for each service.
failure_counts = {name: 0 for name in SERVICES}


def check_service(client: httpx.Client, name: str, url: str) -> str:
    started = time.perf_counter()
    try:
        response = client.get(url)
        elapsed = time.perf_counter() - started
        response.raise_for_status()

        payload = response.json()
        if payload.get("status") != "ok":
            raise ValueError("Unexpected health response")

        # Any successful response resets the consecutive-failure counter.
        failure_counts[name] = 0
        state = "SLOW" if elapsed > SLOW_THRESHOLD_SECONDS else "UP"
        return f"{state} ({elapsed * 1000:.0f} ms)"

    except (httpx.HTTPError, ValueError) as exc:
        failure_counts[name] += 1
        failures = failure_counts[name]

        if failures >= FAILURES_BEFORE_DOWN:
            return f"DOWN ({failures} consecutive failures)"
        return f"SUSPECT ({failures}/{FAILURES_BEFORE_DOWN} failures)"


def main():
    print("Health monitor started. Press Ctrl+C to stop.")
    print(
        f"Interval={CHECK_INTERVAL_SECONDS:.0f}s | "
        f"Timeout={REQUEST_TIMEOUT_SECONDS:.1f}s | "
        f"Slow threshold={SLOW_THRESHOLD_SECONDS * 1000:.0f}ms | "
        f"Down after={FAILURES_BEFORE_DOWN} consecutive failures"
    )

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            while True:
                round_started = time.monotonic()
                timestamp = datetime.now().strftime("%H:%M:%S")
                results = [
                    f"{name}: {check_service(client, name, url)}"
                    for name, url in SERVICES.items()
                ]
                print(f"[{timestamp}] " + " | ".join(results), flush=True)

                elapsed = time.monotonic() - round_started
                time.sleep(max(0.0, CHECK_INTERVAL_SECONDS - elapsed))
    except KeyboardInterrupt:
        print("\nMonitor stopped.")


if __name__ == "__main__":
    main()
